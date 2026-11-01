/* Hiriq — SVG icon sprite.
   Load this right after <body>. Then use an icon anywhere with:
   <svg class="i" width="20" height="20" aria-hidden="true"><use href="#i-check"></use></svg> */
(function () {
  var paths = {
    check: '<path d="M5 12l4.5 4.5L19 7" stroke-width="2.4"/>',
    arrow: '<path d="M5 12h14M13 6l6 6-6 6" stroke-width="2.4"/>',
    mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 7l9 6 9-6"/>',
    phone: '<rect x="7" y="2" width="10" height="20" rx="2.5"/><path d="M11 18h2"/>',
    eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    shield: '<path d="M12 3l8 3v6c0 4.5-3.2 8-8 9-4.8-1-8-4.5-8-9V6l8-3z"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4.4 3.6-7 8-7s8 2.6 8 7"/>',
    briefcase: '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2"/>',
    upload: '<path d="M12 16V4M7 9l5-5 5 5M4 20h16"/>',
    link: '<circle cx="8" cy="12" r="4"/><circle cx="16" cy="12" r="4"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16h.01"/>',
    warn: '<path d="M12 3l10 18H2L12 3z"/><path d="M12 10v4M12 17h.01"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>',
    plus: '<path d="M12 5v14M5 12h14" stroke-width="2.4"/>',
    close: '<path d="M6 6l12 12M18 6L6 18"/>',
    ban: '<circle cx="12" cy="12" r="9"/><path d="M5.6 5.6l12.8 12.8"/>',
    trash: '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/>',
    logout: '<path d="M15 4h4v16h-4M10 8l-4 4 4 4M6 12h11"/>'
  };
  var symbols = Object.keys(paths)
    .map(function (name) {
      return (
        '<symbol id="i-' + name + '" viewBox="0 0 24 24">' +
        '<g fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
        paths[name] +
        "</g></symbol>"
      );
    })
    .join("");
  document.body.insertAdjacentHTML(
    "afterbegin",
    '<svg width="0" height="0" style="position:absolute" aria-hidden="true">' + symbols + "</svg>"
  );
})();
