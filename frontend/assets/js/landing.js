/* Hiriq — landing page behaviour: marquees, workspace tabs, hero tilt, score count-up. */
(function () {
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---------- Marquees: render items twice so the loop is seamless ----------
  document.querySelectorAll(".marquee").forEach(function (m) {
    var items = (m.getAttribute("data-items") || "").split(",");
    var track = m.querySelector(".marquee-track");
    items.concat(items).forEach(function (text, i) {
      var span = document.createElement("span");
      span.textContent = text;
      if (i >= items.length) span.setAttribute("aria-hidden", "true");
      track.appendChild(span);
    });
  });

  // ---------- Workspace tabs (arrow keys move between tabs) ----------
  var tabs = Array.prototype.slice.call(document.querySelectorAll('[role="tab"]'));
  function selectTab(tab) {
    tabs.forEach(function (t) {
      var on = t === tab;
      t.setAttribute("aria-selected", on ? "true" : "false");
      t.tabIndex = on ? 0 : -1;
      var panel = document.getElementById(t.getAttribute("aria-controls"));
      panel.hidden = !on;
      panel.classList.remove("animate");
      if (on) {
        void panel.offsetWidth; // restart the entrance animation
        panel.classList.add("animate");
      }
    });
  }
  tabs.forEach(function (tab, i) {
    tab.addEventListener("click", function () { selectTab(tab); });
    tab.addEventListener("keydown", function (e) {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      var next = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
      selectTab(next);
      next.focus();
    });
  });

  // ---------- Hero card tilts toward the cursor ----------
  var area = document.getElementById("hero-visual");
  var tilt = document.getElementById("hero-tilt");
  if (area && tilt && !reduceMotion) {
    area.addEventListener("mousemove", function (e) {
      var r = area.getBoundingClientRect();
      var x = (e.clientX - r.left) / r.width - 0.5;
      var y = (e.clientY - r.top) / r.height - 0.5;
      tilt.style.transform = "perspective(1100px) rotateX(" + (-y * 10).toFixed(2) + "deg) rotateY(" + (x * 12).toFixed(2) + "deg)";
    });
    area.addEventListener("mouseleave", function () { tilt.style.transform = ""; });
  }

  // ---------- Score counts up from 0 while the ring draws ----------
  var num = document.getElementById("score-num");
  if (num && !reduceMotion) {
    var target = parseInt(num.getAttribute("data-target"), 10);
    num.textContent = "0";
    setTimeout(function () {
      var start = 0;
      function tick(t) {
        if (!start) start = t;
        var p = Math.min(1, (t - start) / 1600);
        num.textContent = String(Math.round((1 - Math.pow(1 - p, 3)) * target));
        if (p < 1) requestAnimationFrame(tick);
      }
      requestAnimationFrame(tick);
    }, 600);
  }
})();
