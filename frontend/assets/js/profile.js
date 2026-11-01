/* Hiriq — "Complete your profile" page. Needs a signed-in session (api mode). */
(function () {
  var cfg = window.HIRIQ_CONFIG;
  var $ = function (sel) { return document.querySelector(sel); };
  var box = $("#profile-message");

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function notify(kind, text) {
    box.innerHTML = text
      ? '<div class="notice notice-' + kind + '" role="' + (kind === "error" ? "alert" : "status") + '"><span>' + escapeHtml(text) + "</span></div>"
      : "";
  }

  var session = window.HiriqAuth.current();
  if (cfg.mode !== "api" || !session) { window.location.replace("login.html"); return; }
  if (session.role === "admin") { window.location.replace("admin.html"); return; }

  document.querySelectorAll("[data-phone]").forEach(function (input) {
    input.addEventListener("input", function () { input.value = input.value.replace(/[^\d ]/g, ""); });
  });

  // Longest country code first, so +971 is not mistaken for +9.
  var CODES = ["+971", "+91", "+44", "+1"];
  function splitPhone(e164) {
    for (var i = 0; i < CODES.length; i++) {
      if (e164.indexOf(CODES[i]) === 0) return { code: CODES[i], rest: e164.slice(CODES[i].length) };
    }
    return null;
  }

  var dob = $("#dob");
  dob.max = new Date().toISOString().slice(0, 10);
  function showUsername(name) {
    if (!name) return;
    $("#username-value").textContent = name;
    $("#username-row").hidden = false;
    $("#dob-hint").textContent = "Your username does not change if you edit this. It is not shown to other users.";
  }
  var MIN_AGE = 16;
  function checkDob(value) {
    if (!value) return "";
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
    if (!m) return "Enter a valid date of birth.";
    var d = new Date(+m[1], +m[2] - 1, +m[3]), now = new Date();
    if (isNaN(d.getTime()) || d > now || +m[1] < 1900) return "Enter a valid date of birth.";
    var age = now.getFullYear() - d.getFullYear() - ((now.getMonth() < d.getMonth() || (now.getMonth() === d.getMonth() && now.getDate() < d.getDate())) ? 1 : 0);
    return age < MIN_AGE ? "You must be at least " + MIN_AGE + " to use Hiriq." : "";
  }

  // Fill in whatever we already know (for example from Google or sign-up).
  window.HiriqAuth.getMe().then(function (res) {
    if (!res.ok) {
      if (res.code === "not_signed_in" || /not signed in/i.test(res.error || "")) window.location.replace("login.html");
      return;
    }
    var me = res.me;
    if (me.user) $("#profile-lead").textContent = "Welcome, " + me.user + ". Your date of birth gives you a username; the rest is optional.";
    showUsername(me.username);
    if (me.dob) $("#dob").value = me.dob;
    if (me.phone) {
      var p = splitPhone(me.phone);
      if (p) { $("#country").value = p.code; $("#phone").value = p.rest; }
    }
    if (me.designation) $("#designation").value = me.designation;
    if (me.company) $("#company").value = me.company;
  });

  $("#profile-form").addEventListener("submit", function (e) {
    e.preventDefault();
    var digits = $("#phone").value.replace(/\D/g, "").replace(/^0+/, "");
    if (digits && digits.length < 7) { notify("error", "That mobile number looks too short. Leave it empty to skip it."); return; }
    var dobError = checkDob(dob.value);
    if (dobError) { notify("error", dobError); return; }
    var btn = $("#profile-save");
    btn.disabled = true;
    window.HiriqAuth.updateProfile({
      dob: dob.value,
      phone: digits ? $("#country").value + digits : "",
      designation: $("#designation").value,
      company: $("#company").value
    }).then(function (res) {
      btn.disabled = false;
      if (!res.ok) {
        if (res.code === "not_signed_in") { window.location.replace("login.html"); return; }
        notify("error", res.error);
        return;
      }
      showUsername(res.me && res.me.username);
      notify("good", "Profile saved" + (res.me && res.me.username ? ". Your username is " + res.me.username : "") + ". The candidate and recruiter dashboards come next.");
    });
  });
})();
