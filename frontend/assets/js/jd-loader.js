/* Hiriq — recruiter: the "writing your job description" loader.
   Free models can take up to a minute, so instead of a spinner the recruiter gets something to look at and use:
     - a live preview page: the facts block (from their own form, exactly what the JD will open with) is already
       written, and the sections the AI is writing shimmer underneath
     - a real elapsed timer (no fake percentages: Hiriq never shows invented numbers)
     - a tip carousel about writing better JDs (next / previous / dots, pauses when touched)
     - "while you wait" checks computed from the form; click one that needs work to jump to that field
   Usage (see recruiter-jobs.js):
       var loader = HiriqJDLoader.start({ area, facts, sections, checks, onCancel });
       loader.finish(text)   // success: fades out and types the text into the textarea
       loader.fail()         // error: removes the loader, shows the textarea again
       loader.cancelled      // true after the recruiter pressed Cancel
   Plain ES5, no dependencies. Styles are in recruiter.css (".jdl-*"). */
window.HiriqJDLoader = (function () {
  var TIPS = [
    "Lead with what the person will do, not a list of tools.",
    "Fewer must-haves bring in more good candidates. Keep the rest under nice to have.",
    "A salary range saves time for you and for the candidate.",
    "Read the draft out loud. If you stumble on a line, so will a candidate.",
    "Describe the work, not the perfect person. Skip words like “rockstar” or “young team”.",
    "Hiriq never scores on name, gender, photo, college or date of birth.",
    "Nothing goes live until you press Publish. The draft is yours to edit."
  ];
  // Widths for the shimmering placeholder lines. Fixed, so the page does not jump around between renders.
  var LINES = [96, 88, 72, 93, 64, 84, 58];
  var reduce = !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function clock(sec) { return Math.floor(sec / 60) + ":" + ("0" + (sec % 60)).slice(-2); }

  function start(opts) {
    var area = opts.area;
    var facts = opts.facts || [];
    var sections = opts.sections || [];
    var tipIndex = Math.floor(Math.random() * TIPS.length);
    var tipHeld = false;      // the recruiter touched the carousel: stop auto-rotating
    var began = Date.now();
    var timer = null, tipTimer = null, done = false;

    var host = document.createElement("div");
    host.className = "jdl";
    host.setAttribute("aria-live", "off"); // the page's main region is a live region; the ticking timer must not be read out

    var paper = "";
    if (facts.length) {
      paper += '<div class="jdl-facts">' + facts.map(function (f) {
        return "<div><span>" + esc(f[0]) + "</span> " + esc(f[1]) + "</div>";
      }).join("") + "</div>";
    }
    sections.forEach(function (title, s) {
      var count = 3 + (s % 2);
      var lines = "";
      for (var i = 0; i < count; i++) {
        lines += '<i class="jdl-line" style="width:' + LINES[(s * 3 + i) % LINES.length] + "%;animation-delay:" + ((s * 4 + i) * 0.18).toFixed(2) + 's"></i>';
      }
      paper += '<div class="jdl-sec"><h3>' + esc(title) + "</h3>" + lines + "</div>";
    });

    host.innerHTML =
      '<span class="jdl-sr" role="status">Writing the job description. This can take up to a minute.</span>' +
      '<div class="jdl-head" aria-hidden="true"><span class="jdl-orb"><span></span></span>' +
      '<div class="jdl-title"><strong>Writing your job description</strong>' +
      '<small>Elapsed <b class="jdl-time">0:00</b><span class="jdl-slow"></span></small></div>' +
      '<button type="button" class="btn-link jdl-cancel">Cancel</button></div>' +
      '<div class="jdl-bar" aria-hidden="true"><i></i></div>' +
      '<div class="jdl-paper" aria-hidden="true">' + paper +
      '<p class="jdl-note">The facts at the top come straight from your form. The AI writes the sections below, and you edit them before anything goes live.</p></div>' +
      '<div class="jdl-side">' +
      '<div class="jdl-tip"><span class="jdl-kicker">Tip</span><p class="jdl-tip-text"></p>' +
      '<div class="jdl-tip-nav"><button type="button" class="jdl-nav" data-dir="-1" aria-label="Previous tip">‹</button>' +
      '<span class="jdl-dots"></span><button type="button" class="jdl-nav" data-dir="1" aria-label="Next tip">›</button></div></div>' +
      '<div class="jdl-checks"><span class="jdl-kicker">While you wait</span><div class="jdl-check-list"></div>' +
      '<small class="jdl-check-note">Fix anything marked below for the next rewrite. This one is already on its way.</small></div></div>';

    area.style.display = "none";
    area.parentNode.insertBefore(host, area);

    var $ = function (sel) { return host.querySelector(sel); };
    var tipText = $(".jdl-tip-text"), dots = $(".jdl-dots"), timeEl = $(".jdl-time"), slowEl = $(".jdl-slow");

    // ---- tips ----
    dots.innerHTML = TIPS.map(function (_, i) { return '<button type="button" class="jdl-dot" data-tip="' + i + '" aria-label="Tip ' + (i + 1) + '"></button>'; }).join("");
    function showTip(i, swap) {
      tipIndex = (i + TIPS.length) % TIPS.length;
      var paint = function () {
        tipText.textContent = TIPS[tipIndex];
        Array.prototype.forEach.call(dots.children, function (d, n) { d.setAttribute("aria-current", String(n === tipIndex)); });
        tipText.classList.remove("jdl-out");
      };
      if (swap && !reduce) { tipText.classList.add("jdl-out"); setTimeout(paint, 160); } else { paint(); }
    }
    showTip(tipIndex, false);
    host.addEventListener("click", function (e) {
      var nav = e.target.closest(".jdl-nav"), dot = e.target.closest(".jdl-dot");
      if (nav) { tipHeld = true; showTip(tipIndex + Number(nav.getAttribute("data-dir")), true); }
      else if (dot) { tipHeld = true; showTip(Number(dot.getAttribute("data-tip")), true); }
    });
    tipTimer = setInterval(function () { if (!tipHeld && !done) showTip(tipIndex + 1, true); }, 7000);

    // ---- checks (recomputed every second, so edits to the form show up) ----
    var checkSig = "";
    function paintChecks() {
      var list = typeof opts.checks === "function" ? opts.checks() : (opts.checks || []);
      var sig = JSON.stringify(list);
      if (sig === checkSig) return;
      checkSig = sig;
      $(".jdl-check-list").innerHTML = list.map(function (c) {
        return '<button type="button" class="jdl-check ' + (c.ok ? "ok" : "todo") + '" data-focus="' + esc(c.focus || "") + '"' + (c.ok ? " tabindex=\"-1\"" : "") + ">" +
          '<span class="jdl-tick" aria-hidden="true">' + (c.ok ? "✓" : "+") + "</span><span>" + esc(c.text) + "</span></button>";
      }).join("");
    }
    host.addEventListener("click", function (e) {
      var b = e.target.closest(".jdl-check.todo");
      if (!b) return;
      var target = document.getElementById(b.getAttribute("data-focus"));
      if (target) { target.scrollIntoView({ block: "center", behavior: reduce ? "auto" : "smooth" }); target.focus({ preventScroll: true }); }
    });

    // ---- timer ----
    function tick() {
      if (!host.isConnected) { teardown(); return; } // the page was re-rendered or the recruiter navigated away
      var sec = Math.floor((Date.now() - began) / 1000);
      timeEl.textContent = clock(sec);
      slowEl.textContent = sec >= 45 ? " · Taking longer than usual. Your form is untouched if it fails."
        : sec >= 20 ? " · Still working. Free models are slow at busy times." : "";
      paintChecks();
    }
    timer = setInterval(tick, 1000);
    tick();

    function teardown() {
      done = true;
      clearInterval(timer);
      clearInterval(tipTimer);
    }
    function remove(fade) {
      if (fade && !reduce) {
        host.classList.add("jdl-leave");
        setTimeout(function () { if (host.parentNode) host.parentNode.removeChild(host); }, 260);
      } else if (host.parentNode) {
        host.parentNode.removeChild(host);
      }
    }

    var api = {
      cancelled: false,

      /** Success: fade the loader out and write the text into the textarea, line by line (instantly if the recruiter touches it). */
      finish: function (text, after) {
        teardown();
        remove(true);
        area.style.display = "";
        var lines = String(text || "").split("\n");
        if (reduce || lines.length < 4) { area.value = text; if (after) after(); return; }
        var shown = 0, step = Math.max(1, Math.ceil(lines.length / 40)), stopped = false;
        area.value = "";
        function finishNow() {
          if (stopped) return;
          stopped = true;
          clearInterval(reveal);
          ["mousedown", "keydown", "touchstart"].forEach(function (n) { area.removeEventListener(n, finishNow); });
          area.value = text;
          area.scrollTop = 0;
          if (after) after();
        }
        var reveal = setInterval(function () {
          shown = Math.min(lines.length, shown + step);
          area.value = lines.slice(0, shown).join("\n");
          area.scrollTop = area.scrollHeight;
          if (shown >= lines.length) finishNow();
        }, 28);
        ["mousedown", "keydown", "touchstart"].forEach(function (n) { area.addEventListener(n, finishNow); });
      },

      /** Error: take the loader away and give the textarea back untouched. */
      fail: function () { teardown(); remove(false); area.style.display = ""; }
    };

    $(".jdl-cancel").addEventListener("click", function () {
      if (api.cancelled || done) return;
      api.cancelled = true;
      teardown();
      remove(false);
      area.style.display = "";
      if (opts.onCancel) opts.onCancel();
    });

    return api;
  }

  return { start: start };
})();
