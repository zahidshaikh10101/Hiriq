/* Hiriq — legal pages: nav line on scroll, and the table of contents follows the section being read. */
(function () {
  var navBar = document.getElementById("nav-bar");
  function navState() { if (navBar) navBar.classList.toggle("scrolled", window.scrollY > 8); }
  window.addEventListener("scroll", navState, { passive: true });
  navState();

  var links = Array.prototype.slice.call(document.querySelectorAll(".legal-toc a"));
  var sections = links.map(function (a) { return document.querySelector(a.getAttribute("href")); }).filter(Boolean);
  if (!sections.length || !("IntersectionObserver" in window)) return;

  function mark(id) {
    links.forEach(function (a) { a.classList.toggle("active", a.getAttribute("href") === "#" + id); });
  }
  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) { if (e.isIntersecting) mark(e.target.id); });
  }, { rootMargin: "-90px 0px -65% 0px", threshold: 0 });
  sections.forEach(function (s) { io.observe(s); });
  mark(sections[0].id);
})();
