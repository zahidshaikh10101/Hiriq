/* Hiriq — candidate workspace: the "working on it" loader.
   Reading a resume or writing a letter can take up to a minute on the free AI models. Instead of one line of text the
   candidate gets something to look at and use, in the same style as the recruiter's job-description loader:
     - a preview page of what is being made, with its sections shimmering until the answer arrives
     - a real elapsed timer (never a made-up percentage)
     - a tip carousel for this kind of task (next / previous / dots; stops rotating once touched)
     - "While you wait": small things to do now. Tick them off; they are only for the candidate and are not saved.
   Usage (see candidate.js):
       var loader = HiriqCandLoader.start({ container: element, kind: "prep", onCancel: fn });
       loader.cancelled          // true after Cancel was pressed: ignore the reply when it arrives
       loader.stop()             // optional tidy-up; the loader also removes itself when its container is redrawn
   Plain ES5, no dependencies. Styles: the ".jdl-*" rules in recruiter.css (already loaded) plus ".cl-*" in candidate.css. */
window.HiriqCandLoader = (function () {
  var KINDS = {
    upload: {
      title: "Reading your resume", sections: ["Contact details", "Skills", "Work history", "Education"],
      note: "The AI reads your resume and fills in your profile. You check and correct it afterwards.",
      tips: ["Your name, gender, photo, college and age are never used to score you.",
             "Skills you can point to in a project or a job count for more than a long skills list.",
             "Dates on each job let Hiriq count your experience for you.",
             "Only the text of your resume is kept. The file itself is not stored.",
             "You can fix anything the reader got wrong on the next screen."],
      todo: ["Have your LinkedIn and GitHub links ready", "Think of the two results you are proudest of", "Decide if you want recruiters to find you"]
    },
    paste: {
      title: "Reading the job description", sections: ["Role", "Required skills", "Nice to have", "Experience"],
      note: "Only the pasted text goes to the AI reader, never your name or contact details. Nothing is saved.",
      tips: ["Required skills count for more than nice-to-haves in your fit.",
             "Where you live is not part of your score.",
             "A missing skill is not a no. See if you have a related tool.",
             "The more of the post you paste, the better the reading."],
      todo: ["Note the three skills you most want to show", "Open your resume and check those skills are in it", "Think of a project that proves the top skill"]
    },
    tailor: {
      title: "Tailoring your resume", sections: ["Summary", "Lines reworded", "Skills to put first", "Gaps to be honest about"],
      note: "The AI only rewords lines you already wrote. Anything that adds a number or a skill you do not have is thrown away.",
      tips: ["Lead each line with a strong verb, then the tool, then the result.",
             "Keep your numbers exactly as they are. Never round them up.",
             "A skill the job wants and you lack stays a gap. Hiriq never writes it in for you.",
             "Your original resume is never changed. This is a saved copy.",
             "Read the result out loud before you send it."],
      todo: ["Re-read the job's required skills", "Pick the one line you want the recruiter to remember", "Check your email and phone are current"]
    },
    prep: {
      title: "Preparing your interview questions", sections: ["Technical", "Behavioural", "About the role", "Stories to prepare", "Questions to ask them"],
      note: "Likely questions for this job, tied to lines you already wrote. They are not a promise of what you will be asked.",
      tips: ["Answer behavioural questions with a real situation, what you did, and the result.",
             "If you have not used a tool, say so, and describe the closest thing you have done.",
             "Prepare two or three short stories. Most questions can be answered with one of them.",
             "Ask what success looks like in the first 90 days.",
             "Say numbers out loud only if they are on your resume."],
      todo: ["Find a quiet place to practise out loud", "Write down your best project in one sentence", "Look up the company and what it sells", "Set a time to practise tomorrow"]
    },
    letter: {
      title: "Writing your cover letter", sections: ["Opening", "What you bring", "Closing"],
      note: "Written only from your resume. Your name and contact details are filled in for you.",
      tips: ["Keep it to one page. Hiring managers read the first lines and skim the rest.",
             "Name the role and say why you fit in the first two sentences.",
             "Read it through and make it sound like you before you send it.",
             "Check the date and the greeting. Use the hiring manager's name if you know it.",
             "You can edit the letter here and download it as a PDF."],
      todo: ["Find the hiring manager's name if you can", "Check the date at the top", "Decide how you want to end: a call, a coffee, an email"]
    },
    fit: {
      title: "Checking your fit", sections: ["Reading the post", "Comparing your skills"],
      note: "The post is read by the AI, then compared with your resume by the same rules as every other job.",
      tips: ["Required skills count for more than nice-to-haves.", "Where you live is not scored.", "Open the posting while you wait and check the apply link."],
      todo: ["Open the posting in another tab", "Check the closing date"]
    }
  };
  var LINES = [96, 88, 72, 93, 64, 84, 58];
  var reduce = !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function clock(sec) { return Math.floor(sec / 60) + ":" + ("0" + (sec % 60)).slice(-2); }

  function start(opts) {
    var K = KINDS[opts.kind] || KINDS.fit;
    var box = opts.container;
    var tipIndex = Math.floor(Math.random() * K.tips.length);
    var tipHeld = false, done = false, began = Date.now(), timer = null, tipTimer = null;

    var host = document.createElement("div");
    host.className = "jdl";
    host.setAttribute("aria-live", "off");

    var paper = "";
    K.sections.forEach(function (title, s) {
      var count = 2 + (s % 2), lines = "";
      for (var i = 0; i < count; i++) {
        lines += '<i class="jdl-line" style="width:' + LINES[(s * 3 + i) % LINES.length] + "%;animation-delay:" + ((s * 4 + i) * 0.18).toFixed(2) + 's"></i>';
      }
      paper += '<div class="jdl-sec"><h3>' + esc(title) + "</h3>" + lines + "</div>";
    });

    host.innerHTML =
      '<span class="jdl-sr" role="status">' + esc(K.title) + ". This can take up to a minute.</span>" +
      '<div class="jdl-head" aria-hidden="true"><span class="jdl-orb"><span></span></span>' +
      '<div class="jdl-title"><strong>' + esc(K.title) + "</strong><small>Elapsed <b class=\"jdl-time\">0:00</b><span class=\"jdl-slow\"></span></small></div>" +
      '<button type="button" class="btn-link jdl-cancel">Cancel</button></div>' +
      '<div class="jdl-bar" aria-hidden="true"><i></i></div>' +
      '<div class="jdl-paper" aria-hidden="true">' + paper + '<p class="jdl-note">' + esc(K.note) + "</p></div>" +
      '<div class="jdl-side">' +
      '<div class="jdl-tip"><span class="jdl-kicker">Tip</span><p class="jdl-tip-text"></p>' +
      '<div class="jdl-tip-nav"><button type="button" class="jdl-nav" data-dir="-1" aria-label="Previous tip">‹</button>' +
      '<span class="jdl-dots"></span><button type="button" class="jdl-nav" data-dir="1" aria-label="Next tip">›</button></div></div>' +
      '<div class="jdl-checks"><span class="jdl-kicker">While you wait</span><div class="jdl-check-list">' +
      K.todo.map(function (t) {
        return '<button type="button" class="jdl-check todo" aria-pressed="false"><span class="jdl-tick" aria-hidden="true">+</span><span>' + esc(t) + "</span></button>";
      }).join("") + '</div><small class="jdl-check-note">Tick these off as you go. They are just for you.</small></div></div>';

    box.innerHTML = "";
    box.appendChild(host);
    if (host.scrollIntoView) host.scrollIntoView({ block: "nearest", behavior: reduce ? "auto" : "smooth" });   // it may be above the fold

    var $ = function (sel) { return host.querySelector(sel); };
    var tipText = $(".jdl-tip-text"), dots = $(".jdl-dots"), timeEl = $(".jdl-time"), slowEl = $(".jdl-slow");

    dots.innerHTML = K.tips.map(function (_, i) { return '<button type="button" class="jdl-dot" data-tip="' + i + '" aria-label="Tip ' + (i + 1) + '"></button>'; }).join("");
    function showTip(i, swap) {
      tipIndex = (i + K.tips.length) % K.tips.length;
      var paint = function () {
        tipText.textContent = K.tips[tipIndex];
        Array.prototype.forEach.call(dots.children, function (d, n) { d.setAttribute("aria-current", String(n === tipIndex)); });
        tipText.classList.remove("jdl-out");
      };
      if (swap && !reduce) { tipText.classList.add("jdl-out"); setTimeout(paint, 160); } else { paint(); }
    }
    showTip(tipIndex, false);

    host.addEventListener("click", function (e) {
      var nav = e.target.closest(".jdl-nav"), dot = e.target.closest(".jdl-dot"), chk = e.target.closest(".jdl-check");
      if (nav) { tipHeld = true; showTip(tipIndex + Number(nav.getAttribute("data-dir")), true); }
      else if (dot) { tipHeld = true; showTip(Number(dot.getAttribute("data-tip")), true); }
      else if (chk) {
        var ok = chk.classList.toggle("ok");
        chk.classList.toggle("todo", !ok);
        chk.setAttribute("aria-pressed", String(ok));
        chk.querySelector(".jdl-tick").textContent = ok ? "✓" : "+";
      }
    });
    tipTimer = setInterval(function () { if (!tipHeld && !done) showTip(tipIndex + 1, true); }, 7000);

    function teardown() { done = true; clearInterval(timer); clearInterval(tipTimer); }
    function tick() {
      if (!host.isConnected) { teardown(); return; }     // the page was redrawn: the work finished or failed
      var sec = Math.floor((Date.now() - began) / 1000);
      timeEl.textContent = clock(sec);
      slowEl.textContent = sec >= 45 ? " · Taking longer than usual. Nothing is lost if it fails."
        : sec >= 20 ? " · Still working. Free models are slow at busy times." : "";
    }
    timer = setInterval(tick, 1000);

    var api = {
      cancelled: false,
      stop: function () { teardown(); if (host.parentNode) host.parentNode.removeChild(host); }
    };
    $(".jdl-cancel").addEventListener("click", function () {
      if (api.cancelled || done) return;
      api.cancelled = true;
      api.stop();
      if (opts.onCancel) opts.onCancel();
    });
    return api;
  }

  return { start: start };
})();
