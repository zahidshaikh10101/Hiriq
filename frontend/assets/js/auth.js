/* Hiriq — login and signup page behaviour.
   One file for both pages: each block only runs if its elements exist.
   Demo mode keeps the design-preview behaviour; api mode talks to the backend (see config.js).
   Verification is by an emailed code. A phone number is optional and added on complete-profile.html. */
(function () {
  var cfg = window.HIRIQ_CONFIG;
  var API = cfg.mode === "api";
  var $ = function (sel) { return document.querySelector(sel); };
  var $$ = function (sel) { return Array.prototype.slice.call(document.querySelectorAll(sel)); };

  function icon(name, size) {
    return '<svg class="i" width="' + size + '" height="' + size + '" aria-hidden="true"><use href="#i-' + name + '"></use></svg>';
  }
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  /** Show a message box. kind: info | error | good. lines: string or array of strings. */
  function notify(box, kind, lines) {
    if (!box) return;
    if (!lines) { box.innerHTML = ""; return; }
    var list = Array.isArray(lines) ? lines : [lines];
    var body = list.length > 1
      ? "<ul>" + list.map(function (l) { return "<li>" + escapeHtml(l) + "</li>"; }).join("") + "</ul>"
      : "<span>" + escapeHtml(list[0]) + "</span>";
    box.innerHTML = '<div class="notice notice-' + kind + '" role="' + (kind === "error" ? "alert" : "status") + '">' + icon("info", 18) + body + "</div>";
  }

  var msgBox = $("#login-message") || $("#signup-message") || $("#forgot-message");
  var isSignupPage = !!$("#signup-form");
  var signupRole = "candidate";

  // ---------- Shared: show/hide password ----------
  $$("[data-toggle-pw]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var input = document.getElementById(btn.getAttribute("data-toggle-pw"));
      var show = input.type === "password";
      input.type = show ? "text" : "password";
      btn.setAttribute("aria-label", show ? "Hide password" : "Show password");
    });
  });

  // ---------- Shared: phone inputs accept digits and spaces only ----------
  $$("[data-phone]").forEach(function (input) {
    input.addEventListener("input", function () {
      input.value = input.value.replace(/[^\d ]/g, "");
    });
  });

  function phoneDigits() { var el = $("#phone"); return el ? el.value.replace(/\D/g, "") : ""; }
  /** "+91" + "098765 43210" -> "+919876543210" (leading zeros are never part of an international number). "" if blank. */
  function fullPhone() {
    var d = phoneDigits().replace(/^0+/, "");
    return d ? $("#country").value + d : "";
  }

  // ---------- Shared: date of birth (must be a real date and at least 18 years ago) ----------
  var MIN_AGE = 18;
  function checkDob(value) {
    if (!value) return "Add your date of birth.";
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
    if (!m) return "Enter your date of birth.";
    var d = new Date(+m[1], +m[2] - 1, +m[3]);
    var now = new Date();
    if (isNaN(d.getTime()) || d > now || +m[1] < 1900) return "Enter a valid date of birth.";
    var age = now.getFullYear() - d.getFullYear() - ((now.getMonth() < d.getMonth() || (now.getMonth() === d.getMonth() && now.getDate() < d.getDate())) ? 1 : 0);
    return age < MIN_AGE ? "You must be at least " + MIN_AGE + " to use Hiriq." : "";
  }
  var dobInput = $("#dob");
  if (dobInput) dobInput.max = new Date().toISOString().slice(0, 10);

  // ---------- Shared: six code boxes (auto-advance, backspace goes back, paste fills all) ----------
  function createOtp(wrap) {
    for (var n = 1; n <= 6; n++) {
      wrap.insertAdjacentHTML("beforeend",
        '<input class="field" inputmode="numeric" maxlength="1" aria-label="Digit ' + n + ' of 6"' + (n === 1 ? ' autocomplete="one-time-code"' : ' autocomplete="off"') + ">");
    }
    var boxes = Array.prototype.slice.call(wrap.querySelectorAll("input"));
    boxes.forEach(function (box, i) {
      box.addEventListener("input", function () {
        box.value = box.value.replace(/\D/g, "").slice(-1);
        if (box.value && i < 5) boxes[i + 1].focus();
      });
      box.addEventListener("keydown", function (e) {
        if (e.key === "Backspace" && !box.value && i > 0) boxes[i - 1].focus();
      });
      box.addEventListener("paste", function (e) {
        var digits = (e.clipboardData.getData("text") || "").replace(/\D/g, "").slice(0, 6);
        if (!digits) return;
        e.preventDefault();
        boxes.forEach(function (b, j) { b.value = digits[j] || ""; });
        boxes[Math.min(digits.length, 5)].focus();
      });
    });
    return {
      code: function () { return boxes.map(function (b) { return b.value; }).join(""); },
      clear: function () { boxes.forEach(function (b) { b.value = ""; }); },
      focus: function () { boxes[0].focus(); }
    };
  }

  /** 30-second "Resend code" countdown inside `box`; returns a stop function. */
  function startCountdown(box, onResend) {
    var secs = 30;
    var timer = null;
    function paint() {
      box.innerHTML = secs > 0
        ? 'Resend code in&nbsp;<span class="mono">0:' + (secs < 10 ? "0" : "") + secs + "</span>"
        : '<button type="button" class="link-btn" data-resend-btn>Resend code</button>';
      if (secs === 0) box.querySelector("[data-resend-btn]").addEventListener("click", onResend);
    }
    paint();
    timer = setInterval(function () {
      secs--;
      paint();
      if (secs <= 0) clearInterval(timer);
    }, 1000);
    return function () { clearInterval(timer); };
  }

  function swapIn(el) {
    el.hidden = false;
    el.classList.remove("swap"); void el.offsetWidth; el.classList.add("swap");
  }

  // ---------- Shared: after a successful sign-in ----------
  // Right after signing up we send people to finish their profile; on a normal log in we only remind them.
  function afterSignIn(res, justSignedUp) {
    if (res.role === "admin") { window.location.href = "admin.html"; return; }
    if (res.role === "recruiter" && !(res.needsProfile && justSignedUp)) { window.location.href = "recruiter.html"; return; }
    if (res.needsProfile && justSignedUp) { window.location.href = "complete-profile.html"; return; }
    if (res.role === "candidate") { window.location.href = "candidate.html"; return; }
    notify(msgBox, "good", res.needsProfile
      ? "Signed in. Open complete-profile.html to add your date of birth (it creates your username) and your phone."
      : "Signed in. The candidate and recruiter dashboards come next.");
  }

  // ---------- Shared: Google ----------
  function onGoogleCredential(resp) {
    var consentBox = $("#consent");
    if (isSignupPage && !consentBox.checked) {
      notify(msgBox, "error", "Accept the Terms and Privacy Policy first, then choose Google again.");
      return;
    }
    window.HiriqAuth.google(resp.credential, {
      mode: isSignupPage ? "signup" : "login",
      role: signupRole,
      consent: isSignupPage && consentBox.checked
    }).then(function (res) {
      if (!res.ok) { notify(msgBox, "error", res.error); return; }
      afterSignIn(res, isSignupPage);
    });
  }

  function loadGoogleScript(onLoad, onFail) {
    if (window.google && window.google.accounts) { onLoad(); return; }
    var s = document.createElement("script");
    s.src = "https://accounts.google.com/gsi/client";
    s.async = true;
    s.defer = true;
    s.onload = onLoad;
    s.onerror = onFail;
    document.head.appendChild(s);
  }

  // On the sign-up page Google stays switched off until the Terms box is ticked, so nobody has to click twice.
  var consentGate = [];
  function syncConsentGate() {
    var box = $("#consent");
    if (!isSignupPage || !box) return;
    consentGate.forEach(function (el) {
      var on = box.checked;
      if (el.tagName === "BUTTON") { el.disabled = !on; }
      else { el.style.pointerEvents = on ? "" : "none"; el.setAttribute("aria-disabled", on ? "false" : "true"); }
      el.style.opacity = on ? "" : "0.45";
      el.title = on ? "" : "Tick the box above to continue";
    });
  }
  if (isSignupPage && $("#consent")) $("#consent").addEventListener("change", syncConsentGate);

  $$("[data-google]").forEach(function (btn) {
    function previewNote() {
      notify(msgBox, "info", !API
        ? 'Google sign-in works once the backend is connected: set mode to "api" in assets/js/config.js.'
        : "Add your Google client ID as googleClientId in assets/js/config.js to turn this on.");
    }
    if (!API || !cfg.googleClientId) { btn.addEventListener("click", previewNote); consentGate.push(btn); syncConsentGate(); return; }

    var width = Math.min(400, btn.offsetWidth || 340);
    consentGate.push(btn);
    syncConsentGate();
    btn.addEventListener("click", function () {
      notify(msgBox, "error", "Google sign-in could not load. Check your connection, and open this page from " + cfg.apiBase + ".");
    });
    loadGoogleScript(function () {
      window.google.accounts.id.initialize({ client_id: cfg.googleClientId, callback: onGoogleCredential });
      var holder = document.createElement("div");
      holder.style.cssText = "display:flex;justify-content:center;min-height:44px";
      btn.parentNode.insertBefore(holder, btn.nextSibling);
      consentGate.push(holder);
      syncConsentGate();
      window.google.accounts.id.renderButton(holder, {
        type: "standard", theme: "filled_black", size: "large", shape: "pill", logo_alignment: "left",
        text: isSignupPage ? "signup_with" : "continue_with", width: width
      });
      btn.hidden = true;
    }, function () { /* the click handler above explains it */ });
  });

  // ================= LOGIN =================
  var emailForm = $("#email-form");
  if (emailForm) {
    emailForm.addEventListener("submit", function (e) {
      e.preventDefault();
      var id = $("#identifier").value;
      var pw = $("#password").value;
      if (!id.trim() || !pw) {
        notify(msgBox, "error", "Enter your email or username and your password.");
        return;
      }
      var btn = $("#login-btn");
      btn.disabled = true;
      btn.textContent = "Signing in…";
      window.HiriqAuth.login(id, pw).then(function (res) {
        btn.disabled = false;
        btn.textContent = "Log in";
        if (!res.ok) {
          notify(msgBox, "error", res.error);
          return;
        }
        afterSignIn(res, false);
      });
    });

    if (/[?&]reset=1/.test(window.location.search)) {
      notify(msgBox, "good", "Your password was changed. Log in with the new one.");
    }

    // Already signed in as admin? Offer a shortcut.
    var s = window.HiriqAuth.current();
    if (s && s.role === "admin") {
      msgBox.innerHTML = '<div class="notice notice-good" role="status">' + icon("check", 18) +
        '<span>You are signed in as admin. <a href="admin.html">Open the admin dashboard</a></span></div>';
    }
  }

  // ================= SIGNUP =================
  var signupForm = $("#signup-form");
  if (signupForm) {
    $$("[data-role]").forEach(function (card) {
      card.addEventListener("click", function () {
        signupRole = card.getAttribute("data-role");
        $$("[data-role]").forEach(function (c) {
          c.setAttribute("aria-pressed", c === card ? "true" : "false");
        });
        ["candidate", "recruiter"].forEach(function (r) {
          var el = $("#aside-" + r);
          el.hidden = r !== signupRole;
          el.classList.remove("animate");
          if (r === signupRole) { void el.offsetWidth; el.classList.add("animate"); }
        });
      });
    });

    // Password strength meter
    var LEVELS = [
      { word: "Not set", color: "rgb(234 242 255 / .62)" },
      { word: "Too weak", color: "#FF7A90" },
      { word: "Fair", color: "#FFB547" },
      { word: "Good", color: "#6AA8FF" },
      { word: "Strong", color: "#2EE6A8" }
    ];
    function strength(pw) {
      if (!pw) return 0;
      var s = 0;
      if (pw.length >= 8) s++;
      if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) s++;
      if (/\d/.test(pw)) s++;
      if (/[^A-Za-z0-9]/.test(pw)) s++;
      if (pw.length < 8) s = Math.min(s, 1);
      return Math.max(1, s);
    }
    var pwInput = $("#new-password");
    var segs = $$(".strength .segs span");
    var word = $("#strength-word");
    pwInput.addEventListener("input", function () {
      var lvl = strength(pwInput.value);
      var c = LEVELS[lvl].color;
      segs.forEach(function (s, i) {
        var on = i < lvl;
        s.style.background = on ? c : "";
        s.style.boxShadow = on ? "0 0 10px " + c : "";
      });
      word.textContent = LEVELS[lvl].word;
      word.style.color = c;
    });

    // Step 2: the code we email
    var otpBlock = $("#signup-otp-form");
    var signupOtp = createOtp($("#signup-otp"));
    var signupEmail = "";
    var stopSignupTimer = function () {};

    function showSignupOtp(masked) {
      notify(msgBox, null);
      $("#signup-sent-to").textContent = masked || signupEmail;
      $("#signup-step1").style.display = "none";
      swapIn(otpBlock);
      signupOtp.clear();
      signupOtp.focus();
      stopSignupTimer();
      stopSignupTimer = startCountdown($("#signup-resend"), resendSignupCode);
    }
    function resendSignupCode() {
      window.HiriqAuth.resendSignupCode(signupEmail).then(function (res) {
        if (!res.ok) { notify(msgBox, "error", res.error); }
        else { notify(msgBox, "good", "A new code is on its way."); }
        stopSignupTimer();
        stopSignupTimer = startCountdown($("#signup-resend"), resendSignupCode);
      });
    }
    $("#signup-change").addEventListener("click", function () {
      stopSignupTimer();
      notify(msgBox, null);
      otpBlock.hidden = true;
      $("#signup-step1").style.display = "contents";
    });

    signupForm.addEventListener("submit", function (e) {
      e.preventDefault();
      var errors = [];
      if (!$("#name").value.trim()) errors.push("Add your full name.");
      if (!/^\S+@\S+\.\S+$/.test($("#email").value)) errors.push("Add a valid email address.");
      var dobError = checkDob($("#dob").value);
      if (dobError) errors.push(dobError);
      if (phoneDigits() && phoneDigits().length < 7) errors.push("That mobile number looks too short. Leave it empty to add it later.");
      if (pwInput.value.length < 8) errors.push("Use a password of at least 8 characters.");
      if (!$("#consent").checked) errors.push("Accept the Terms and Privacy Policy to continue.");
      if (errors.length) {
        notify(msgBox, "error", errors);
        return;
      }
      if (!API) {
        notify(msgBox, "good", "Looks good. Account creation will work once the backend is connected (" + signupRole + ").");
        return;
      }
      var btn = signupForm.querySelector('button[type="submit"]');
      btn.disabled = true;
      signupEmail = $("#email").value.trim().toLowerCase();
      window.HiriqAuth.signup({
        name: $("#name").value, email: signupEmail, dob: $("#dob").value, phone: fullPhone(), password: pwInput.value,
        role: signupRole, consent: $("#consent").checked
      }).then(function (res) {
        btn.disabled = false;
        if (!res.ok) { notify(msgBox, "error", res.error); return; }
        showSignupOtp(res.emailMasked);
      });
    });

    otpBlock.addEventListener("submit", function (e) {
      e.preventDefault();
      var code = signupOtp.code();
      if (code.length !== 6) {
        notify(msgBox, "error", "Enter all 6 digits of the code.");
        return;
      }
      window.HiriqAuth.verifyEmail(signupEmail, code).then(function (res) {
        if (!res.ok) { notify(msgBox, "error", res.error); return; }
        stopSignupTimer();
        otpBlock.hidden = true;
        afterSignIn(res, true);
        if (!res.needsProfile) {
          notify(msgBox, "good", "Email verified. Your account is ready" + (res.username ? ". Your username is " + res.username : "") +
            ". The candidate and recruiter dashboards come next.");
        }
      });
    });
  }

  // ================= FORGOT PASSWORD =================
  var forgotForm = $("#forgot-form");
  if (forgotForm) {
    var resetForm = $("#reset-form");
    var resetOtp = createOtp($("#reset-otp"));
    var forgotEmail = "";
    var stopResetTimer = function () {};

    function showReset(masked) {
      notify(msgBox, null);
      $("#reset-sent-to").textContent = masked || forgotEmail;
      forgotForm.hidden = true;
      $("#forgot-lead").textContent = "Enter the 6-digit code from the email and choose a new password.";
      swapIn(resetForm);
      resetOtp.clear();
      resetOtp.focus();
      stopResetTimer();
      stopResetTimer = startCountdown($("#reset-resend"), resendResetCode);
    }
    function resendResetCode() {
      window.HiriqAuth.forgotPassword(forgotEmail).then(function (res) {
        notify(msgBox, res.ok ? "good" : "error", res.ok ? "If that address has an account, a new code is on its way." : res.error);
        stopResetTimer();
        stopResetTimer = startCountdown($("#reset-resend"), resendResetCode);
      });
    }
    $("#reset-change").addEventListener("click", function () {
      stopResetTimer();
      notify(msgBox, null);
      resetForm.hidden = true;
      forgotForm.hidden = false;
      $("#forgot-lead").textContent = "Enter the email you signed up with. We will email you a 6-digit code.";
    });

    forgotForm.addEventListener("submit", function (e) {
      e.preventDefault();
      var email = $("#forgot-email").value.trim().toLowerCase();
      if (!/^\S+@\S+\.\S+$/.test(email)) { notify(msgBox, "error", "Add a valid email address."); return; }
      if (!API) { notify(msgBox, "info", 'Password reset needs the backend: set mode to "api" in assets/js/config.js.'); return; }
      var btn = $("#forgot-btn");
      btn.disabled = true;
      forgotEmail = email;
      window.HiriqAuth.forgotPassword(email).then(function (res) {
        btn.disabled = false;
        if (!res.ok) { notify(msgBox, "error", res.error); return; }
        showReset(res.emailMasked);
      });
    });

    resetForm.addEventListener("submit", function (e) {
      e.preventDefault();
      var code = resetOtp.code();
      var pw = $("#reset-password").value;
      if (code.length !== 6) { notify(msgBox, "error", "Enter all 6 digits of the code."); return; }
      if (pw.length < 8) { notify(msgBox, "error", "Use a password of at least 8 characters."); return; }
      var btn = $("#reset-btn");
      btn.disabled = true;
      window.HiriqAuth.resetPassword(forgotEmail, code, pw).then(function (res) {
        btn.disabled = false;
        if (!res.ok) { notify(msgBox, "error", res.error); return; }
        stopResetTimer();
        window.location.href = "login.html?reset=1";
      });
    });
  }
})();
