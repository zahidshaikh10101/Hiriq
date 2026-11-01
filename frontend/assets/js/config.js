/* Hiriq — frontend settings. This is the only file you edit to switch modes.

   mode "demo" : no backend needed. Admin login is checked in the browser
                 against the hash below. This is NOT real security: anyone can
                 read this file. It exists so the UI works before the backend.
   mode "api"  : the Python (FastAPI) backend in /backend handles sign-up, login,
                 Google sign-in and phone codes. Start it, open the site from
                 http://localhost:8000 (not by double-clicking the file), then set mode to "api". */
window.HIRIQ_CONFIG = {
  mode: "api",
  apiBase: "http://localhost:8000",

  // Google Cloud Console -> Credentials -> OAuth client ID (Web). Same value as GOOGLE_CLIENT_ID in backend/.env.
  // Not a secret. Leave empty to keep the Google button as a design preview.
  googleClientId: "143459147516-amaonhssmqcpb88a8i77kdn3fm3dhobl.apps.googleusercontent.com",

  // Demo admin. Username "admin"; the password is stored only as a SHA-256 hash.
  // To change it, put the new hash here (see README for a one-line way to make one).
  demoAdmin: {
    username: "admin",
    passwordSha256: "6e84e4756c64bf352c3da57a78ad3c5c5eff96e8ee34a5fc8e132b54cf52ba1d"
  },

  sessionHours: 8
};
