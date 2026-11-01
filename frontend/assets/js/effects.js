/* Hiriq — shared visual effects.
   - Fills <div class="space-bg" data-stars="60"> with stars, glow orbs, meteors, cursor light
   - Fades in [data-reveal] elements as they scroll into view */
(function () {
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Deterministic random so the starfield looks the same on every load
  function seeded(seed) {
    var s = seed;
    return function () {
      s = (s * 9301 + 49297) % 233280;
      return s / 233280;
    };
  }

  function buildBackground(el) {
    var count = parseInt(el.getAttribute("data-stars") || "60", 10);
    var rnd = seeded(parseInt(el.getAttribute("data-seed") || "7", 10));
    var html = '<div class="grid"></div>';
    for (var i = 0; i < count; i++) {
      var size = rnd() > 0.8 ? 3 : 2;
      html +=
        '<span class="star" style="left:' + (rnd() * 100).toFixed(2) + "%;top:" + (rnd() * 100).toFixed(2) +
        "%;width:" + size + "px;height:" + size + "px;animation-delay:" + (rnd() * 4).toFixed(2) + 's"></span>';
    }
    html += '<div class="orb o1"></div><div class="orb o2"></div><div class="orb o3"></div>';
    if (el.getAttribute("data-meteors") !== "off") {
      html +=
        '<span class="meteor" style="top:60px;left:78%"></span>' +
        '<span class="meteor" style="top:20px;left:95%;animation-delay:3.3s"></span>' +
        '<span class="meteor" style="top:260px;left:62%;animation-delay:6.6s"></span>';
    }
    var spotlight = el.getAttribute("data-spotlight") !== "off";
    if (spotlight) html += '<div class="spotlight"></div>';
    el.innerHTML = html;

    if (spotlight && !reduceMotion) {
      var light = el.querySelector(".spotlight");
      var frame = 0;
      window.addEventListener(
        "mousemove",
        function (e) {
          cancelAnimationFrame(frame);
          frame = requestAnimationFrame(function () {
            light.style.setProperty("--mx", e.clientX + "px");
            light.style.setProperty("--my", e.clientY + "px");
          });
        },
        { passive: true }
      );
    }
  }

  function setupReveal() {
    var items = document.querySelectorAll("[data-reveal]");
    if (!("IntersectionObserver" in window) || reduceMotion) {
      items.forEach(function (el) { el.classList.add("in-view"); });
      return;
    }
    var io = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add("in-view");
            io.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.12 }
    );
    items.forEach(function (el) { io.observe(el); });
  }

  document.querySelectorAll(".space-bg").forEach(buildBackground);
  setupReveal();
})();
