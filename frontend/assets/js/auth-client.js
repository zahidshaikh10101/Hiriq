/* Hiriq — auth client. Works in both modes set in config.js.
   window.HiriqAuth.login(username, password) -> Promise<{ ok, error, code }>
   window.HiriqAuth.current()                 -> session object or null
   window.HiriqAuth.requireAdmin()            -> redirects to login.html if not an admin
   window.HiriqAuth.logout()
   api mode only:
   window.HiriqAuth.signup(fields)             -> Promise<{ ok, error, code, emailMasked }>  (emails a code; needs name, email, password, dob)
   window.HiriqAuth.verifyEmail(email, code)   -> Promise<{ ok, error, role, needsProfile, username }>   (signs the user in)
   window.HiriqAuth.resendSignupCode(email)    -> Promise<{ ok, error }>
   window.HiriqAuth.forgotPassword(email)      -> Promise<{ ok, error, emailMasked }>   (emails a reset code; same answer for any address)
   window.HiriqAuth.resetPassword(email, code, newPassword) -> Promise<{ ok, error, code }>
   window.HiriqAuth.google(credential, opts)   -> Promise<{ ok, error, code, role, needsProfile, username }>
   window.HiriqAuth.getMe()                    -> Promise<{ ok, error, me }>
   window.HiriqAuth.updateProfile(fields)      -> Promise<{ ok, error, code, me }>  (dob, phone, designation, company)
   window.HiriqAuth.api(method, path, body)    -> Promise<{ ok, status, data, error, code }>  (any call with the signed-in token) */
(function () {
  var cfg = window.HIRIQ_CONFIG;
  var KEY = "hiriq_session";

  // ---- SHA-256 in plain JS (crypto.subtle is not available on every file:// page) ----
  function sha256(ascii) {
    function rrot(v, n) { return (v >>> n) | (v << (32 - n)); }
    var bytes = unescape(encodeURIComponent(ascii)); // UTF-8
    var k = [], h = [], i, j, primes = 0;
    var isComposite = {};
    for (var c = 2; primes < 64; c++) {
      if (!isComposite[c]) {
        for (i = 0; i < 313; i += c) isComposite[i] = c;
        if (primes < 8) h[primes] = (Math.pow(c, 0.5) * 4294967296) | 0;
        k[primes++] = (Math.pow(c, 1 / 3) * 4294967296) | 0;
      }
    }
    var words = [], bitLen = bytes.length * 8;
    bytes += "\x80";
    while ((bytes.length % 64) - 56) bytes += "\x00";
    for (i = 0; i < bytes.length; i++) words[i >> 2] |= bytes.charCodeAt(i) << ((3 - i) % 4) * 8;
    words[words.length] = (bitLen / 4294967296) | 0;
    words[words.length] = bitLen;
    for (j = 0; j < words.length; ) {
      var w = words.slice(j, (j += 16)), old = h.slice(0);
      for (i = 0; i < 64; i++) {
        var w15 = w[i - 15], w2 = w[i - 2];
        var a = h[0], e = h[4];
        var t1 = h[7] + (rrot(e, 6) ^ rrot(e, 11) ^ rrot(e, 25)) + ((e & h[5]) ^ (~e & h[6])) + k[i] +
          (w[i] = i < 16 ? w[i] : (w[i - 16] + (rrot(w15, 7) ^ rrot(w15, 18) ^ (w15 >>> 3)) + w[i - 7] + (rrot(w2, 17) ^ rrot(w2, 19) ^ (w2 >>> 10))) | 0);
        var t2 = (rrot(a, 2) ^ rrot(a, 13) ^ rrot(a, 22)) + ((a & h[1]) ^ (a & h[2]) ^ (h[1] & h[2]));
        h = [(t1 + t2) | 0].concat(h);
        h[4] = (h[4] + t1) | 0;
        h.length = 8;
      }
      for (i = 0; i < 8; i++) h[i] = (h[i] + old[i]) | 0;
    }
    var hex = "";
    for (i = 0; i < 8; i++) for (j = 3; j + 1; j--) {
      var b = (h[i] >> (j * 8)) & 255;
      hex += (b < 16 ? "0" : "") + b.toString(16);
    }
    return hex;
  }

  function save(session) {
    try { sessionStorage.setItem(KEY, JSON.stringify(session)); } catch (e) { /* storage blocked */ }
  }
  function load() {
    try { return JSON.parse(sessionStorage.getItem(KEY) || "null"); } catch (e) { return null; }
  }
  function clear() {
    try { sessionStorage.removeItem(KEY); } catch (e) { /* ignore */ }
  }

  function current() {
    var s = load();
    if (!s || !s.exp || s.exp < Date.now()) return null;
    return s;
  }

  // ---- API helpers ----
  var DEMO_MSG = 'This needs the backend. Start it and set mode to "api" in assets/js/config.js.';

  /** JSON request. Resolves { ok, status, data, error, code } and never rejects. */
  function request(method, path, body, token) {
    var headers = { "Content-Type": "application/json" };
    if (token) headers.Authorization = "Bearer " + token;
    var opts = { method: method, headers: headers };
    if (body !== undefined) opts.body = JSON.stringify(body);
    return fetch(cfg.apiBase + path, opts)
      .then(function (res) {
        return res.json().catch(function () { return {}; }).then(function (data) {
          var out = { ok: res.ok, status: res.status, data: data };
          if (!res.ok) {
            var d = data && data.detail;
            if (d && typeof d === "object" && !Array.isArray(d)) { out.error = d.message; out.code = d.code; }
            else if (Array.isArray(d) && d[0] && d[0].msg) out.error = d[0].msg;
            else if (typeof d === "string") out.error = d;
            out.error = out.error || "Something went wrong. Try again.";
          }
          return out;
        });
      })
      .catch(function () {
        return { ok: false, status: 0, data: {}, error: "Could not reach the backend at " + cfg.apiBase + ". Is it running?" };
      });
  }
  function post(path, body, token) { return request("POST", path, body, token); }

  function saveFromLogin(user, data) {
    var seconds = data.expires_in || cfg.sessionHours * 3600;
    save({ user: data.name || user, role: data.role, token: data.access_token, exp: Date.now() + seconds * 1000, mode: "api" });
  }

  function login(username, password) {
    var user = String(username || "").trim().toLowerCase();

    if (cfg.mode === "api") {
      return post("/api/auth/login", { username: user, password: password }).then(function (r) {
        if (!r.ok) return { ok: false, error: r.error, code: r.code };
        saveFromLogin(user, r.data);
        return { ok: true, role: r.data.role, needsProfile: !!r.data.needs_profile };
      });
    }

    // demo mode
    var expires = Date.now() + cfg.sessionHours * 3600 * 1000;
    var da = cfg.demoAdmin;
    var ok = !!da && user === da.username && sha256(password) === da.passwordSha256;
    if (!ok) return Promise.resolve({ ok: false, error: "That username and password do not match." });
    save({ user: user, role: "admin", exp: expires, mode: "demo" });
    return Promise.resolve({ ok: true, role: "admin" });
  }

  function demoOnly() { return Promise.resolve({ ok: false, error: DEMO_MSG }); }

  // Secret from POST /signup. It stays in this page only; verifying needs it together with the emailed code, so a sign-up
  // someone else restarts for your email cannot be completed with your code.
  var signupToken = "";

  function signup(f) {
    if (cfg.mode !== "api") return demoOnly();
    return post("/api/auth/signup", {
      name: f.name, email: f.email, dob: f.dob, phone: f.phone || "", password: f.password,
      role: f.role, consent: !!f.consent
    }).then(function (r) {
      if (r.ok) signupToken = r.data.signup_token || "";
      return r.ok ? { ok: true, emailMasked: r.data.email_masked } : { ok: false, error: r.error, code: r.code };
    });
  }

  function verifyEmail(email, code) {
    if (cfg.mode !== "api") return demoOnly();
    return post("/api/auth/signup/verify-email", { email: email, code: code, token: signupToken }).then(function (r) {
      if (!r.ok) return { ok: false, error: r.error, code: r.code };
      saveFromLogin("", r.data);
      return { ok: true, role: r.data.role, needsPhone: !!r.data.needs_phone, needsProfile: !!r.data.needs_profile, username: r.data.username || "" };
    });
  }

  function resendSignupCode(email) {
    if (cfg.mode !== "api") return demoOnly();
    return post("/api/auth/signup/resend", { email: email }).then(function (r) { return { ok: r.ok, error: r.error }; });
  }

  function forgotPassword(email) {
    if (cfg.mode !== "api") return demoOnly();
    return post("/api/auth/password/forgot", { email: email }).then(function (r) {
      return r.ok ? { ok: true, emailMasked: r.data.email_masked } : { ok: false, error: r.error, code: r.code };
    });
  }

  function resetPassword(email, code, newPassword) {
    if (cfg.mode !== "api") return demoOnly();
    return post("/api/auth/password/reset", { email: email, code: code, new_password: newPassword }).then(function (r) {
      return r.ok ? { ok: true } : { ok: false, error: r.error, code: r.code };
    });
  }

  function authed(method, path, body) {
    var s = current();
    if (!s || !s.token) return Promise.resolve({ ok: false, status: 401, error: "Please log in again.", code: "not_signed_in" });
    return request(method, path, body, s.token);
  }

  function getMe() {
    if (cfg.mode !== "api") return demoOnly();
    return authed("GET", "/api/auth/me").then(function (r) { return r.ok ? { ok: true, me: r.data } : { ok: false, error: r.error, code: r.code }; });
  }

  /** fields: { phone, designation, company }; phone "" clears it. */
  function updateProfile(fields) {
    if (cfg.mode !== "api") return demoOnly();
    return authed("PUT", "/api/auth/profile", fields).then(function (r) {
      return r.ok ? { ok: true, me: r.data } : { ok: false, error: r.error, code: r.code };
    });
  }

  /** opts: { mode: "login" | "signup", role, consent } */
  function google(credential, opts) {
    if (cfg.mode !== "api") return demoOnly();
    opts = opts || {};
    return post("/api/auth/google", {
      credential: credential, mode: opts.mode || "login", role: opts.role || "candidate", consent: !!opts.consent
    }).then(function (r) {
      if (!r.ok) return { ok: false, error: r.error, code: r.code };
      saveFromLogin("", r.data);
      return { ok: true, role: r.data.role, needsPhone: !!r.data.needs_phone, needsProfile: !!r.data.needs_profile, username: r.data.username || "" };
    });
  }

  function logout() {
    clear();
    window.location.href = "login.html";
  }

  function requireAdmin() {
    var s = current();
    if (!s || s.role !== "admin") {
      window.location.replace("login.html");
      return null;
    }
    // In api mode, double-check the token with the backend.
    if (s.mode === "api") {
      fetch(cfg.apiBase + "/api/auth/me", { headers: { Authorization: "Bearer " + s.token } })
        .then(function (res) { if (!res.ok) logout(); })
        .catch(function () { /* backend offline: keep the page, calls will fail visibly */ });
    }
    return s;
  }

  window.HiriqAuth = {
    login: login, logout: logout, current: current, requireAdmin: requireAdmin, sha256: sha256,
    signup: signup, verifyEmail: verifyEmail, resendSignupCode: resendSignupCode, google: google,
    getMe: getMe, updateProfile: updateProfile, forgotPassword: forgotPassword, resetPassword: resetPassword,
    api: function (method, path, body) { return cfg.mode === "api" ? authed(method, path, body) : demoOnly(); }
  };
})();
