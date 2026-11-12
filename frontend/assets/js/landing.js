/* Hiriq — landing page behaviour: marquees, tabs, pricing toggle, nav, hero tilt, score count-up. */
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

  // ---------- Tabs: every tablist works on its own (arrow keys move between its tabs) ----------
  function selectTab(tabs, tab) {
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
  document.querySelectorAll('[role="tablist"]').forEach(function (list) {
    var tabs = Array.prototype.slice.call(list.querySelectorAll('[role="tab"]'));
    tabs.forEach(function (tab, i) {
      tab.addEventListener("click", function () { selectTab(tabs, tab); });
      tab.addEventListener("keydown", function (e) {
        if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
        var next = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
        selectTab(tabs, next);
        next.focus();
      });
    });
  });

  // ---------- Nav: a quiet line under the bar once the page has moved ----------
  var navBar = document.getElementById("nav-bar");
  function navState() { if (navBar) navBar.classList.toggle("scrolled", window.scrollY > 8); }
  window.addEventListener("scroll", navState, { passive: true });
  navState();

  // ---------- Pricing: monthly or one yearly payment with 20% off ----------
  var YEARLY_DISCOUNT = 0.2;
  var sw = document.getElementById("bill-switch");
  var billing = document.getElementById("billing");
  function rupees(n) { return "\u20B9" + Math.round(n).toLocaleString("en-IN"); }
  function renderPrices(yearly) {
    document.querySelectorAll(".price-card").forEach(function (card) {
      var amt = card.querySelector(".amt[data-month]");
      var sub = card.querySelector(".price-sub");
      var per = card.querySelector(".per");
      if (!amt) return; // Enterprise has no fixed price
      var monthly = parseInt(amt.getAttribute("data-month"), 10);
      if (!monthly) return; // Free stays free
      var year = Math.round(monthly * 12 * (1 - YEARLY_DISCOUNT));
      amt.textContent = rupees(yearly ? year : monthly);
      amt.classList.toggle("hl", yearly);
      if (per) per.textContent = yearly ? "/year" : "/month";
      if (sub) {
        sub.innerHTML = yearly
          ? "One payment for 12 months, about " + rupees(year / 12) + "/month" +
            '<span class="save-line">20% off. You save ' + rupees(monthly * 12 - year) + "</span>"
          : "Billed monthly";
      }
    });
    billing.classList.toggle("yearly", yearly);
    document.getElementById("bill-monthly").classList.toggle("on", !yearly);
    document.getElementById("bill-yearly").classList.toggle("on", yearly);
    sw.setAttribute("aria-checked", yearly ? "true" : "false");
  }
  if (sw && billing) {
    sw.addEventListener("click", function () { renderPrices(sw.getAttribute("aria-checked") !== "true"); });
    document.getElementById("bill-monthly").addEventListener("click", function () { renderPrices(false); });
    document.getElementById("bill-yearly").addEventListener("click", function () { renderPrices(true); });
    renderPrices(false);
  }

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