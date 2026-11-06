/* Hiriq — frontend settings. This is the only file you edit to switch modes.

   mode "demo" : no backend needed. Admin login is checked in the browser
                 against the hash below. This is NOT real security: anyone can
                 read this file. It exists so the UI works before the backend.
   mode "api"  : the Python (FastAPI) backend in /backend handles sign-up, login,
                 Google sign-in and phone codes. Start it, open the site from
                 http://localhost:8000 (not by double-clicking the file), then set mode to "api". */
window.HIRIQ_CONFIG = {
  mode: "api",
  // Where the API lives. On localhost (or a file) it is the backend on port 8000; once the site is deployed the API is
  // expected on the same address as the pages. To point somewhere else, set window.HIRIQ_API_BASE before this file loads.
  apiBase: (function () {
    if (window.HIRIQ_API_BASE) return String(window.HIRIQ_API_BASE).replace(/\/+$/, "");
    var l = window.location, local = /^(localhost|127\.0\.0\.1)$/.test(l.hostname);
    return /^https?:$/.test(l.protocol) && !local ? l.origin : "http://localhost:8000";
  })(),

  // Google Cloud Console -> Credentials -> OAuth client ID (Web). Same value as GOOGLE_CLIENT_ID in backend/.env.
  // Not a secret. Leave empty to keep the Google button as a design preview.
  googleClientId: "143459147516-amaonhssmqcpb88a8i77kdn3fm3dhobl.apps.googleusercontent.com",

  // Demo-mode admin (only used when mode is "demo"; anyone can read this file, so never reuse a real password).
  // Off by default. To turn it on, replace null with { username: "admin", passwordSha256: "<hash>" }, where the hash is made with:
  //   node -e "console.log(require('crypto').createHash('sha256').update('your-demo-password').digest('hex'))"
  demoAdmin: null,

  sessionHours: 8
};
