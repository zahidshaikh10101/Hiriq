/* Job preferences card on My profile: places, roles, job types, work modes.
   Add, edit (remove and re-add) and delete happen on the page; one Save sends the whole set. Saving starts a small first fetch of
   outside jobs on the server, so there is nothing to wait for here. window.HiriqPrefs.mount(el, { api, esc, explain }). */
(function () {
  "use strict";
  var LABEL = { "full-time": "Full-time", "part-time": "Part-time", contract: "Contract", internship: "Internship", onsite: "On-site", hybrid: "Hybrid", remote: "Remote" };

  function mount(el, h) {
    var esc = h.esc, S = null, dirty = false;

    function load() {
      el.innerHTML = '<div class="card card-stack"><h2 class="card-title">Job preferences</h2><p class="faint" role="status">Loading…</p></div>';
      h.api("GET", "/api/candidate/preferences").then(function (r) {
        if (!r.ok) { el.innerHTML = '<div class="card card-stack"><h2 class="card-title">Job preferences</h2><p class="faint">' + esc(h.explain(r)) + "</p></div>"; return; }
        S = r.data; dirty = false; draw();
      });
    }

    function tagBlock(key, title, hint, ph) {
      var chips = S[key].map(function (v, i) {
        return '<span class="pref-chip">' + esc(v) + '<button type="button" data-rm="' + key + '" data-i="' + i + '" aria-label="Remove ' + esc(v) + '">×</button></span>';
      }).join("");
      var full = S[key].length >= S.limits[key];
      return '<div class="stack-2"><label class="label" for="pf-' + key + '">' + title + ' <span class="faint">(up to ' + S.limits[key] + ")</span></label>" +
        '<div class="chips-row">' + (chips || '<span class="faint">' + hint + "</span>") + "</div>" +
        '<div class="inline-form"><input class="field field-sm" id="pf-' + key + '" maxlength="80" placeholder="' + ph + '"' + (full ? " disabled" : "") + '>' +
        '<button type="button" class="btn btn-outline" data-add="' + key + '"' + (full ? " disabled" : "") + ">Add</button></div></div>";
    }

    function toggles(key, title) {
      return '<div class="stack-2"><span class="label">' + title + '</span><div class="chips-row">' + S.options[key].map(function (o) {
        return '<button type="button" class="pref-toggle" data-tg="' + key + '" data-v="' + o + '" aria-pressed="' + (S[key].indexOf(o) >= 0) + '">' + LABEL[o] + "</button>";
      }).join("") + "</div></div>";
    }

    function draw(note) {
      var when = S.last_refreshed_at ? "Jobs last refreshed " + new Date(S.last_refreshed_at).toLocaleString() + "." : "Your job list has not been refreshed yet.";
      el.innerHTML = '<div class="card card-stack"><div class="row-between"><h2 class="card-title">Job preferences</h2>' +
        '<button type="button" class="btn-link" id="pf-clear"' + (S.roles.length + S.locations.length + S.job_types.length + S.work_modes.length ? "" : " disabled") + ">Clear all</button></div>" +
        '<span class="card-sub">Tell us what you are looking for and Find work uses it to pick jobs for you. Leave a list empty if you have no preference.</span>' +
        '<div id="pf-msg" aria-live="polite">' + (note || "") + "</div>" +
        tagBlock("roles", "Roles", "No roles yet", "e.g. Data Analyst") + tagBlock("locations", "Places", "No places yet", "e.g. Pune") +
        toggles("job_types", "Job type") + toggles("work_modes", "Work mode") +
        '<div class="row-between"><span class="faint" style="font-size:13px">' + esc(when) + '</span><button type="button" class="btn btn-grad" id="pf-save">Save preferences</button></div></div>';
      wire();
    }

    function msg(kind, text) {
      var m = el.querySelector("#pf-msg");
      if (m) m.innerHTML = '<div class="notice notice-' + kind + '" role="' + (kind === "error" ? "alert" : "status") + '" style="animation:none"><span>' + esc(text) + "</span></div>";
    }

    function add(key) {
      var inp = el.querySelector("#pf-" + key), v = inp.value.replace(/\s+/g, " ").trim();
      if (!v) return;
      if (S[key].some(function (x) { return x.toLowerCase() === v.toLowerCase(); })) { inp.value = ""; return; }
      if (S[key].length >= S.limits[key]) return;
      S[key].push(v); dirty = true; draw(); el.querySelector("#pf-" + key).focus();
    }

    function wire() {
      Array.prototype.forEach.call(el.querySelectorAll("[data-add]"), function (b) { b.addEventListener("click", function () { add(b.getAttribute("data-add")); }); });
      Array.prototype.forEach.call(el.querySelectorAll(".inline-form input"), function (i) {
        i.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); add(i.id.replace("pf-", "")); } });
      });
      Array.prototype.forEach.call(el.querySelectorAll("[data-rm]"), function (b) {
        b.addEventListener("click", function () { S[b.getAttribute("data-rm")].splice(+b.getAttribute("data-i"), 1); dirty = true; draw(); });
      });
      Array.prototype.forEach.call(el.querySelectorAll("[data-tg]"), function (b) {
        b.addEventListener("click", function () {
          var list = S[b.getAttribute("data-tg")], v = b.getAttribute("data-v"), at = list.indexOf(v);
          if (at >= 0) list.splice(at, 1); else list.push(v);
          dirty = true; b.setAttribute("aria-pressed", at < 0);
        });
      });
      el.querySelector("#pf-save").addEventListener("click", save);
      el.querySelector("#pf-clear").addEventListener("click", function () {
        if (!window.confirm("Clear all your job preferences?")) return;
        h.api("DELETE", "/api/candidate/preferences").then(function (r) { if (r.ok) { S = r.data; draw('<div class="notice notice-good" style="animation:none"><span>Preferences cleared.</span></div>'); } else msg("error", h.explain(r)); });
      });
    }

    function save() {
      var btn = el.querySelector("#pf-save"); btn.disabled = true;
      h.api("PUT", "/api/candidate/preferences", { roles: S.roles, locations: S.locations, job_types: S.job_types, work_modes: S.work_modes }).then(function (r) {
        if (!r.ok) { btn.disabled = false; msg("error", h.explain(r)); return; }
        S = r.data; dirty = false;
        draw('<div class="notice notice-good" style="animation:none"><span>Saved.' + (r.data.fetching ? " We are fetching jobs for you now; they will show up in Find work shortly." : "") + "</span></div>");
      });
    }

    load();
  }
  window.HiriqPrefs = { mount: mount };
})();
