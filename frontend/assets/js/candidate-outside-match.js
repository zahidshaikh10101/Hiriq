/* Hiriq — candidate workspace. Live data from the backend (/api/candidate/*).
   Views are chosen by the URL hash: #profile #insights #jobs #jobs/<id>.
   Profile (resume upload, edit, who can see you), Insights (what your resume shows and what open jobs ask for) and
   Jobs & match (open jobs, your fit with the reasons, a match for any job description you paste, and Apply) are live.
   Apply and the Applications page are in candidate-apply.js.
   Nothing here is estimated: a part the resume cannot answer is shown as "not assessed", never as zero. */
(function () {
  var view = document.getElementById("view");
  var cfg = window.HIRIQ_CONFIG;
  var session = window.HiriqAuth.current();

  var MAX_BYTES = 5 * 1024 * 1024;
  var OK_EXT = /\.(pdf|docx|txt)$/i;

  // ---------- helpers ----------
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function icon(name, size) {
    return '<svg class="i" width="' + size + '" height="' + size + '" aria-hidden="true"><use href="#i-' + name + '"></use></svg>';
  }
  function $(sel) { return view.querySelector(sel); }
  function ago(iso) {
    if (!iso) return "never";
    var s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
    if (s < 60) return "just now";
    if (s < 3600) return Math.floor(s / 60) + " min ago";
    if (s < 86400) return Math.floor(s / 3600) + " h ago";
    if (s < 172800) return "yesterday";
    if (s < 30 * 86400) return Math.floor(s / 86400) + " days ago";
    return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
  }
  function years(n) { return n == null ? "—" : (n === 1 ? "1 yr" : +Number(n).toFixed(1) + " yrs"); }
  function chips(list, max, cls) {
    list = list || [];
    var shown = list.slice(0, max).map(function (s) { return '<span class="chip ' + (cls || "chip-neutral") + '">' + esc(s) + "</span>"; }).join(" ");
    var more = list.length > max ? ' <span class="faint">+' + (list.length - max) + "</span>" : "";
    return shown ? shown + more : '<span class="faint">none</span>';
  }
  function header(title, badge) {
    return '<header class="page-head"><div class="stack-2"><span class="faint" style="font-size:13px">Candidate workspace</span><h1>' + esc(title) + "</h1></div>" +
      '<div class="head-tools">' + (badge || "") + "</div></header>";
  }
  var LIVE = '<span class="live-badge"><span class="dot pulse" style="background:rgb(var(--a4))"></span>Live data</span>';
  function notice(kind, text) {
    return '<div class="notice notice-' + kind + '" role="' + (kind === "error" ? "alert" : "status") + '" style="animation:none">' + icon("info", 18) + "<span>" + esc(text) + "</span></div>";
  }
  function loading(title) {
    view.innerHTML = '<div class="view">' + header(title) + '<div class="card loading" role="status">Loading…</div></div>';
  }
  function failure(title, message) {
    view.innerHTML = '<div class="view">' + header(title) + notice("error", message) + "</div>";
  }
  function explain(r) {
    var d = r.data && r.data.detail;
    if (Array.isArray(d) && d.length) {
      return d.slice(0, 3).map(function (e) { return String(e.msg || "").replace(/^Value error, /, ""); }).join(" ");
    }
    return r.error || "Something went wrong. Try again.";
  }
  function api(method, path, body) {
    return window.HiriqAuth.api(method, path, body).then(function (r) {
      if (!r.ok && (r.status === 401 || r.code === "not_signed_in")) { window.HiriqAuth.logout(); }
      return r;
    });
  }
  // Long AI work: show the loader (preview, timer, tips, tick list). Falls back to a plain notice if the loader script is missing.
  function work(container, kind, onCancel) {
    if (!window.HiriqCandLoader) { container.innerHTML = notice("info", "Working on it. This can take up to a minute…"); return { cancelled: false, stop: function () {} }; }
    return window.HiriqCandLoader.start({ container: container, kind: kind, onCancel: function () {
      container.innerHTML = notice("info", "Cancelled. The request may still count toward your hourly limit.");
      if (onCancel) onCancel();
    } });
  }
  var navId = 0;   // a newer navigation cancels slower responses from an older one

  // =====================================================
  // PROFILE
  // =====================================================
  function renderProfile(note) {
    var mine = ++navId;
    loading("My profile");
    api("GET", "/api/candidate/me").then(function (r) {
      if (mine !== navId) return;
      if (!r.ok) { failure("My profile", r.status === 403 ? "This area is for candidate accounts." : r.error); return; }
      drawProfile(r.data, note);
    });
  }

  function profileSummary(me) {
    var rows = [
      ["Role", [me.current_title, me.current_company].filter(Boolean).join(" at ") || "—"],
      ["Location", me.location || "—"], ["Experience", years(me.total_experience_years) + (me.experience_basis === "edited" ? " (entered by you)" : "")],
      ["Qualification", me.qualification || "—"], ["Email", me.email || "—"], ["Phone", me.phone || "—"]
    ];
    var links = [["LinkedIn", me.linkedin_url], ["GitHub", me.github_url], ["Website", me.portfolio_url]].filter(function (l) { return /^https?:\/\//i.test(l[1] || ""); })
      .map(function (l) { return '<a class="btn-link" href="' + esc(l[1]) + '" target="_blank" rel="noopener noreferrer">' + l[0] + "</a>"; }).join(" · ");
    return '<dl class="kv">' + rows.map(function (r) { return "<div><dt>" + r[0] + "</dt><dd>" + esc(r[1]) + "</dd></div>"; }).join("") + "</dl>" +
      (links ? '<p style="margin:0">' + links + "</p>" : "") +
      '<div class="stack-2"><span class="card-sub">Skills</span><div class="chips-row">' + chips(me.skills, 40) + "</div></div>";
  }

  function drawProfile(me, note) {
    var dz = '<div class="dropzone" id="dz"><span class="dz-icon">' + icon("upload", 26) + "</span>" +
      '<span class="dz-text"><strong>' + (me.has_resume ? "Upload a new resume to replace this one" : "Drop your resume here, or choose a file") + "</strong>" +
      '<span class="faint">PDF, Word (.docx) or text, up to 5 MB. Only the text is kept; the file itself is not stored.</span></span>' +
      '<button type="button" class="btn btn-grad" id="pick">Choose a file</button>' +
      '<input type="file" id="file-input" accept=".pdf,.docx,.txt,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain" hidden></div>';
    var resumeLine = me.has_resume
      ? '<div class="row-between"><span class="cell-stack"><strong>' + esc(me.file_name || "Your resume") + '</strong><small>Read by ' + esc(me.parsed_by || "the AI reader") + '. Check the details below and fix anything it got wrong.</small></span>' +
        '<button type="button" class="btn-link" id="remove">Remove resume</button></div>'
      : '<p class="empty-inline">No resume yet. Upload one and your profile fills itself in; you can correct it afterwards.</p>';
    var canShow = me.has_profile;
    view.innerHTML = '<div class="view">' + header("My profile", LIVE) + '<div id="msg" aria-live="polite">' + (note ? notice(note[0], note[1]) : "") + "</div>" +
      '<div class="card card-stack"><div class="stack-2"><h2 class="card-title">Your resume</h2></div>' + resumeLine + dz + "</div>" +
      '<div class="card card-stack"><div class="switch-row"><div class="stack-2"><h2 class="card-title">Visible to recruiters</h2>' +
      '<span class="card-sub">Off by default. When on, recruiters can find you by title, skills and experience. They never see your email, phone or links unless you apply to their job.</span></div>' +
      '<button type="button" role="switch" class="switch" id="vis" aria-checked="' + !!me.visible_to_recruiters + '" aria-label="Visible to recruiters"' + (canShow ? "" : " disabled") + "></button></div>" +
      (canShow ? "" : '<p class="privacy-note">Add your resume or some skills first. Then you can choose to be found.</p>') + "</div>" +
      '<div class="card card-stack" id="profile-card"><div class="row-between"><h2 class="card-title">Profile details</h2><button type="button" class="btn-link" id="btn-edit">Edit</button></div>' + profileSummary(me) + "</div>" +
      '<p class="privacy-note">Your name, gender, photo, college and age are never used to score you. Nothing here contacts a recruiter for you.</p></div>';

    var input = $("#file-input"), dzEl = $("#dz");
    $("#pick").addEventListener("click", function () { input.click(); });
    input.addEventListener("change", function () { if (input.files[0]) upload(input.files[0]); input.value = ""; });
    ["dragenter", "dragover"].forEach(function (ev) { dzEl.addEventListener(ev, function (e) { e.preventDefault(); dzEl.classList.add("over"); }); });
    ["dragleave", "drop"].forEach(function (ev) { dzEl.addEventListener(ev, function (e) { e.preventDefault(); dzEl.classList.remove("over"); }); });
    dzEl.addEventListener("drop", function (e) { var f = e.dataTransfer && e.dataTransfer.files[0]; if (f) upload(f); });
    var rm = $("#remove");
    if (rm) rm.addEventListener("click", function () {
      if (!window.confirm("Remove your resume and profile details? You will also be hidden from recruiters, and any applications you sent are withdrawn.")) return;
      api("DELETE", "/api/candidate/resume").then(function (r) { r.ok ? drawProfile(r.data, ["good", "Your resume was removed."]) : ($("#msg").innerHTML = notice("error", explain(r))); });
    });
    $("#vis").addEventListener("click", function () {
      var next = this.getAttribute("aria-checked") !== "true";
      api("PUT", "/api/candidate/visibility", { visible: next }).then(function (r) {
        if (!r.ok) { $("#msg").innerHTML = notice("error", explain(r)); return; }
        drawProfile(r.data, ["good", next ? "Recruiters can now find your profile." : "You are hidden from recruiters."]);
      });
    });
    $("#btn-edit").addEventListener("click", function () { drawEdit(me); });
  }

  function upload(file) {
    var msg = $("#msg");
    var problem = /\.doc$/i.test(file.name) ? "Old .doc files are not supported. Save it as .docx or PDF first."
      : !OK_EXT.test(file.name) ? "Only PDF, Word (.docx) and text files are supported."
      : !file.size ? "This file is empty." : file.size > MAX_BYTES ? "This file is larger than 5 MB." : "";
    if (problem) { msg.innerHTML = notice("error", problem); return; }
    var s = window.HiriqAuth.current();
    if (!s) { window.HiriqAuth.logout(); return; }
    var loader = work(msg, "upload");
    fetch(cfg.apiBase + "/api/candidate/resume", {
      method: "POST",
      headers: { Authorization: "Bearer " + s.token, "X-Filename": encodeURIComponent(file.name), "Content-Type": "application/octet-stream" },
      body: file
    }).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (data) { return { ok: res.ok, status: res.status, data: data }; });
    }).catch(function () {
      return { ok: false, status: 0, data: {}, error: "Could not reach the backend. Is it running?" };
    }).then(function (r) {
      if (loader.cancelled) return;
      loader.stop();
      if (r.status === 401) { window.HiriqAuth.logout(); return; }
      if (!r.ok) {
        var d = r.data && r.data.detail;
        var text = r.error || (d && typeof d === "object" && !Array.isArray(d) ? d.message : (r.status === 413 ? "This file is larger than 5 MB." : "Something went wrong. Try again."));
        var m = $("#msg"); if (m) m.innerHTML = notice("error", text);
        return;
      }
      drawProfile(r.data, ["good", r.data.already_added ? "That is the resume you already have, so nothing changed." : "Resume read. Check the details below."]);
    });
  }

  function drawEdit(me) {
    function field(id, label, value, attrs) {
      return '<div class="field-group"><label class="label" for="e-' + id + '">' + label + '</label><input class="field field-sm" id="e-' + id + '" value="' + esc(value == null ? "" : value) + '" ' + (attrs || "") + "></div>";
    }
    $("#profile-card").innerHTML = '<div class="row-between"><h2 class="card-title">Edit profile</h2></div><form id="edit-form" class="card-stack" novalidate>' +
      field("name", "Full name *", me.full_name, 'maxlength="160" required') + field("title", "Current or target role", me.current_title, 'maxlength="160"') +
      field("company", "Current company", me.current_company, 'maxlength="160"') + field("loc", "Location", me.location, 'maxlength="160"') +
      field("years", "Experience (years)", me.total_experience_years, 'type="number" min="0" max="60" step="0.1" inputmode="decimal"') +
      field("qual", "Highest qualification", me.qualification, 'maxlength="200"') + field("email", "Email", me.email, 'type="email" maxlength="320"') +
      field("phone", "Phone", me.phone, 'maxlength="30"') + field("li", "LinkedIn link", me.linkedin_url, 'maxlength="300" placeholder="https://www.linkedin.com/in/…"') +
      field("gh", "GitHub link", me.github_url, 'maxlength="300" placeholder="https://github.com/…"') + field("site", "Website or portfolio", me.portfolio_url, 'maxlength="300" placeholder="https://yourname.dev"') +
      '<div class="field-group"><label class="label" for="e-skills">Skills (separate with commas)</label><textarea class="field" id="e-skills" rows="3">' + esc((me.skills || []).join(", ")) + "</textarea></div>" +
      '<div id="edit-msg" aria-live="polite"></div><div class="actions-bar"><button type="submit" class="btn btn-grad" id="btn-save">Save changes</button><button type="button" class="btn btn-outline" id="btn-cancel">Cancel</button></div></form>';
    $("#e-name").focus();
    $("#btn-cancel").addEventListener("click", function () { drawProfile(me); });
    $("#edit-form").addEventListener("submit", function (e) {
      e.preventDefault();
      var v = function (id) { return $("#e-" + id).value.trim(); };
      var yrs = v("years");
      var body = {
        full_name: v("name"), current_title: v("title"), current_company: v("company"), location: v("loc"), qualification: v("qual"),
        email: v("email"), phone: v("phone"), linkedin_url: v("li"), github_url: v("gh"), portfolio_url: v("site"),
        total_experience_years: yrs === "" ? null : Number(yrs),
        skills: v("skills").split(/[,;\n]/).map(function (s) { return s.trim(); }).filter(Boolean)
      };
      var btn = $("#btn-save"); btn.disabled = true;
      api("PUT", "/api/candidate/profile", body).then(function (r) {
        btn.disabled = false;
        if (!r.ok) { $("#edit-msg").innerHTML = notice("error", explain(r)); return; }
        drawProfile(r.data, ["good", "Saved."]);
      });
    });
  }

  // =====================================================
  // INSIGHTS
  // =====================================================
  var STATE_TEXT = { shown: "Shown in your work", listed_only: "Listed only", not_shown: "Not shown", no_resume: "No resume text" };
  var STATE_CLASS = { shown: "good", listed_only: "near", not_shown: "miss", no_resume: "" };
  var SKILL_STATUS = {
    listed: ["Listed", "good"], implied: ["Implied by a related skill", "good"], text: ["Found in your resume", "good"],
    related: ["Related tool, half credit", "near"], ai_related: ["Related tool, half credit", "near"], missing: ["Not found", "miss"]
  };

  function renderInsights() {
    var mine = ++navId;
    loading("Insights");
    api("GET", "/api/candidate/insights").then(function (r) {
      if (mine !== navId) return;
      if (!r.ok) { failure("Insights", r.error); return; }
      drawInsights(r.data);
    });
  }

  function drawInsights(D) {
    var c = D.completeness;
    var empty = D.has_profile ? "" : notice("info", "Upload your resume or add some skills on My profile and these insights fill in.");
    var done = '<div class="card card-stack"><div class="row-between"><div class="stack-2"><h2 class="card-title">Profile completeness</h2><span class="card-sub">How much of your profile is filled in. This describes your profile, not you.</span></div>' +
      '<span class="mono" style="font-size:22px">' + c.percent + '%</span></div><div class="progress" role="img" aria-label="' + c.percent + ' percent complete"><span style="width:' + c.percent + '%"></span></div>' +
      '<ul class="checklist">' + c.items.map(function (i) {
        return '<li class="' + (i.done ? "done" : "") + '"><span class="tick">' + (i.done ? icon("check", 11) : "") + "</span><span>" + esc(i.label) + (i.hint ? "<small>" + esc(i.hint) + "</small>" : "") + "</span></li>";
      }).join("") + "</ul></div>";

    var sk = D.skills, skillsHtml;
    if (!sk.count) skillsHtml = '<p class="empty-inline">No skills on file yet.</p>';
    else {
      skillsHtml = '<span class="card-sub">' + sk.shown + " shown in your work, " + sk.listed_only + " only listed in a skills line. Skills you can point to in a project or job are the strongest.</span>" +
        '<div class="chips-row">' + sk.by_category.map(function (g) { return '<span class="chip chip-violet">' + esc(g.category) + " · " + g.count + "</span>"; }).join(" ") + "</div>" +
        '<ul class="skill-rows">' + sk.items.map(function (s) {
          return '<li class="skill-row"><span class="skill-main"><strong>' + esc(s.skill) + "</strong><small class=\"faint\">" + esc(s.category) + "</small>" +
            (s.evidence && s.state === "shown" ? "<blockquote>" + esc(s.evidence) + "</blockquote>" : "") + '</span><span class="status-chip ' + (STATE_CLASS[s.state] || "") + '">' + esc(STATE_TEXT[s.state] || s.state) + "</span></li>";
        }).join("") + "</ul>";
    }

    var ex = D.experience;
    var expHtml = '<div class="chips-row"><span class="chip chip-cyan">' + years(ex.years) + ' of experience</span>' +
      (ex.basis === "dates" ? '<span class="chip chip-neutral">counted from your job dates</span>' : ex.basis === "edited" ? '<span class="chip chip-neutral">entered by you</span>' : "") + "</div>" +
      (ex.employers.length ? ex.employers.map(function (e) {
        return '<div class="employer"><strong>' + esc(e.title || "Role") + "</strong> at " + esc(e.company) + "<br><small>" + esc([e.start, e.end || (e.start ? "present" : "")].filter(Boolean).join(" – ")) + "</small></div>";
      }).join("") : '<p class="empty-inline">No work history on file.</p>');

    var mk = D.market, marketHtml;
    if (!mk.open_jobs) marketHtml = '<p class="empty-inline">No open jobs on Hiriq yet, so there is nothing to compare with.</p>';
    else if (!mk.in_demand.length) marketHtml = '<p class="empty-inline">' + mk.open_jobs + " open job" + (mk.open_jobs === 1 ? "" : "s") + ". Add your skills to see how they line up.</p>";
    else {
      marketHtml = '<span class="card-sub">What ' + mk.open_jobs + " open job" + (mk.open_jobs === 1 ? "" : "s") + " ask for most, and whether your resume shows it.</span>" +
        '<ul class="skill-rows">' + mk.in_demand.map(function (m) {
          var st = SKILL_STATUS[m.status] || [m.status, ""];
          return '<li class="skill-row"><span class="skill-main"><strong>' + esc(m.skill) + '</strong><small class="faint">asked by ' + m.jobs + " job" + (m.jobs === 1 ? "" : "s") + "</small>" +
            (m.evidence ? "<blockquote>" + esc(m.evidence) + "</blockquote>" : "") + '</span><span class="status-chip ' + st[1] + '">' + st[0] + "</span></li>";
        }).join("") + "</ul>" +
        (mk.gaps.length ? '<p class="privacy-note">Skills to build or to show in your work: ' + mk.gaps.map(function (g) { return esc(g.skill); }).join(", ") + ".</p>" : "") +
        '<a class="btn-link" href="#jobs">See the jobs and score your fit</a>';
    }

    view.innerHTML = '<div class="view">' + header("Insights", LIVE) + empty + done +
      '<div class="row"><div class="card card-stack grow-2"><h2 class="card-title">Your skills</h2>' + skillsHtml + "</div>" +
      '<div class="card card-stack grow-1"><h2 class="card-title">Experience</h2>' + expHtml + "</div></div>" +
      '<div class="card card-stack"><h2 class="card-title">Skills in demand</h2>' + marketHtml + "</div>" +
      '<p class="privacy-note">Never used to score you: ' + esc(D.not_scored.join(", ")) + ".</p></div>";
  }

  // =====================================================
  // MATCH RESULT (shared by an open job and a pasted job description)
  // =====================================================
  var PART_LABEL = { skills: "Skills", qualification: "Qualification", experience: "Experience", location: "Location", keywords: "Keywords" };

  function skillRows(list) {
    return list.map(function (s) {
      var st = SKILL_STATUS[s.status] || [s.status, ""];
      var via = s.via && (s.status === "implied" || s.status === "related") ? " (" + esc(s.via) + ")" : "";
      return '<li class="skill-row"><span class="skill-main"><strong>' + esc(s.skill) + "</strong>" + (s.evidence ? "<blockquote>" + esc(s.evidence) + "</blockquote>" : "") +
        '</span><span class="status-chip ' + st[1] + '">' + st[0] + via + "</span></li>";
    }).join("");
  }

  function matchHtml(m) {
    var e = m.explanation || {}, parts = m.parts || {}, sk = e.skills || { required: [], nice: [] };
    var cls = m.score >= 70 ? "strong" : m.score < 40 ? "low" : "";
    var met = sk.required.filter(function (r) { return r.credit >= 1; }).length;
    var partRows = Object.keys(PART_LABEL).filter(function (k) { return !parts[k] || parts[k].weight !== 0; }).map(function (k) {
      var p = parts[k] || {}, assessed = p.assessed, reason = k === "skills" ? (sk.required.length ? met + " of " + sk.required.length + " required skills found" : "") : ((e[k] && e[k].reason) || "");
      return '<div class="part' + (assessed ? "" : " off") + '"><div class="part-top"><strong>' + PART_LABEL[k] + ' <small>(' + (p.weight == null ? "" : p.weight + "%") + ')</small></strong><span class="mono">' +
        (assessed ? Math.round(p.score) : "not assessed") + '</span></div><div class="bar"><span style="width:' + (assessed ? Math.max(2, p.score) : 0) + '%"></span></div>' + (reason ? "<small>" + esc(reason) + "</small>" : "") + "</div>";
    }).join("");
    return (m.stale ? notice("warn", "Your profile or this job changed since this score was made. Match again to refresh it.") : "") +
      '<div class="fit-hero"><span class="fit-score ' + cls + '">' + Math.round(m.score) + "<small>of 100</small></span><div class=\"fit-text\"><strong>" + esc(m.summary || e.summary || "") + "</strong>" +
      (m.assessed_weight != null && m.assessed_weight < 100 ? '<small class="faint">Based on ' + m.assessed_weight + "% of the criteria; the rest could not be assessed.</small>" : "") + "</div></div>" +
      '<div class="parts">' + partRows + "</div>" +
      '<div class="stack-2"><h3 class="card-title" style="font-size:15px">Required skills</h3></div>' + (sk.required.length ? '<ul class="skill-rows">' + skillRows(sk.required) + "</ul>" : '<p class="empty-inline">None listed.</p>') +
      (sk.nice.length ? '<div class="stack-2"><h3 class="card-title" style="font-size:15px">Nice to have</h3></div><ul class="skill-rows">' + skillRows(sk.nice) + "</ul>" : "");
  }

  // =====================================================
  // JOBS
  // =====================================================
  var searchText = "";

  function renderJobs() {
    var mine = ++navId;
    loading("Jobs & match");
    api("GET", "/api/candidate/jobs" + (searchText ? "?q=" + encodeURIComponent(searchText) : "")).then(function (r) {
      if (mine !== navId) return;
      if (!r.ok) { failure("Jobs & match", r.error); return; }
      drawJobs(r.data);
    });
  }

  function jobMeta(j) {
    var exp = j.experience_min != null ? j.experience_min + (j.experience_max != null ? "–" + j.experience_max : "+") + " yrs" : "";
    return [j.company, j.location, j.work_mode, j.employment_type, exp].filter(Boolean).map(function (x) { return "<span>" + esc(x) + "</span>"; }).join("");
  }

  function jobCard(j) {
    var f = j.fit;
    var side = f
      ? '<span class="score-chip' + (f.score >= 70 ? " strong" : "") + '">' + f.score + "</span><small class=\"faint\">" + f.required_met + " of " + f.required_total + " required</small>" +
        (f.stale ? '<span class="stale-note">out of date</span>' : "")
      : '<small class="faint">not scored yet</small>';
    return '<article class="card job-card"><div class="stack-2" style="flex:1;min-width:240px"><h3><a href="#jobs/' + esc(j.id) + '">' + esc(j.title) + '</a></h3><div class="job-meta">' + jobMeta(j) + "</div>" +
      '<div class="chips-row">' + chips(j.skills_required, 8, "chip-cyan") + "</div></div>" +
      '<div class="fit-side">' + side + '<a class="btn btn-outline" href="#jobs/' + esc(j.id) + '" style="min-height:38px">' + (f ? "See why" : "Open") + "</a></div></article>";
  }

  function drawJobs(D) {
    var list = D.jobs.length ? '<div class="job-list">' + D.jobs.map(jobCard).join("") + "</div>"
      : '<div class="card"><p class="empty-inline">' + (searchText ? "No open jobs match that search." : "No open jobs on Hiriq yet. Check back soon, or paste a job description above to see how you fit.") + "</p></div>";
    var needProfile = D.has_profile ? "" : notice("info", "Add your resume or skills on My profile first, then you can score jobs.");
    view.innerHTML = '<div class="view">' + header("Jobs & match", LIVE) + needProfile + '<div id="msg" aria-live="polite"></div>' +
      '<details class="card card-stack"><summary class="card-title" style="cursor:pointer">Match a job description you paste</summary>' +
      '<p class="privacy-note">Paste the whole post from anywhere. Only the pasted text goes to the AI reader, never your name or contact details. Nothing is saved.</p>' +
      '<textarea class="field paste-box" id="paste" placeholder="Paste the job description here" maxlength="12000"></textarea>' +
      '<div class="actions-bar"><button type="button" class="btn btn-grad" id="paste-go"' + (D.has_profile ? "" : " disabled") + '>Match this job</button></div><div id="paste-out" class="card-stack" aria-live="polite"></div></details>' +
      '<div class="toolbar"><input class="field field-sm" id="q" type="search" placeholder="Search title, skill, city or company" value="' + esc(searchText) + '" aria-label="Search jobs">' +
      '<button type="button" class="btn btn-outline" id="score-all"' + (D.has_profile && D.total ? "" : " disabled") + '>Score all open jobs</button>' +
      '<span class="faint" style="font-size:13px">' + D.total + " open job" + (D.total === 1 ? "" : "s") + (D.scored ? " · " + D.scored + " scored" : "") + "</span></div>" + list + "</div>";

    var q = $("#q"), timer = null;
    q.addEventListener("input", function () { clearTimeout(timer); timer = setTimeout(function () { searchText = q.value.trim(); renderJobs(); }, 350); });
    $("#score-all").addEventListener("click", function () {
      this.disabled = true;
      api("POST", "/api/candidate/jobs/match").then(function (r) {
        if (!r.ok) { $("#msg").innerHTML = notice("error", explain(r)); $("#score-all").disabled = false; return; }
        drawJobs(r.data);
        $("#msg").innerHTML = notice("good", "Scored " + r.data.ran + " job" + (r.data.ran === 1 ? "" : "s") + (r.data.skipped_no_skills ? ". " + r.data.skipped_no_skills + " had no skills listed yet." : "."));
      });
    });
    $("#paste-go").addEventListener("click", function () {
      var btn = this, out = $("#paste-out");
      btn.disabled = true;
      var loader = work(out, "paste", function () { btn.disabled = false; });
      api("POST", "/api/candidate/match/paste", { text: $("#paste").value }).then(function (r) {
        if (loader.cancelled) return;
        btn.disabled = false;
        if (!r.ok) { out.innerHTML = notice("error", explain(r)); return; }
        var d = r.data, rd = d.read || {};
        out.innerHTML = '<div class="stack-2"><h3 class="card-title" style="font-size:15px">What we understood' + (rd.title ? " — " + esc(rd.title) : "") + '</h3>' +
          '<div class="chips-row">' + chips(rd.skills_required, 15, "chip-cyan") + "</div>" +
          '<small class="faint">' + [rd.experience_min != null ? rd.experience_min + (rd.experience_max != null ? "–" + rd.experience_max : "+") + " years" : "", rd.qualification, rd.location, rd.work_mode].filter(Boolean).map(esc).join(" · ") + "</small></div>" +
          matchHtml({ score: d.score, parts: d.parts, explanation: d.explanation, summary: d.summary, assessed_weight: d.assessed_weight });
      });
    });
  }

  // ---------- one job ----------
  function renderJob(id) {
    var mine = ++navId;
    loading("Job");
    api("GET", "/api/candidate/jobs/" + encodeURIComponent(id)).then(function (r) {
      if (mine !== navId) return;
      if (!r.ok) { failure("Job", r.status === 404 ? "That job is not open any more." : r.error); return; }
      drawJob(r.data);
    });
  }

  function drawJob(J) {
    var salary = J.salary_min || J.salary_max ? (J.salary_currency || "") + " " + [J.salary_min, J.salary_max].filter(Boolean).map(function (n) { return Number(n).toLocaleString("en-IN"); }).join(" – ") + " a year" : "";
    var fit = J.fit;
    var matchBlock = fit
      ? matchHtml({ score: fit.score, parts: fit.parts, explanation: fit.explanation, summary: fit.summary, assessed_weight: fit.assessed_weight, stale: fit.stale })
      : '<p class="empty-inline">' + (J.has_profile ? "You have not scored this job yet." : "Add your resume or skills on My profile first, then score this job.") + "</p>";
    view.innerHTML = '<div class="view">' + header(J.title, LIVE) + '<p style="margin:0"><a class="btn-link" href="#jobs">Back to jobs</a></p><div id="msg" aria-live="polite"></div>' +
      '<div class="card card-stack"><div class="job-meta">' + jobMeta(J) + (salary ? "<span>" + esc(salary) + "</span>" : "") + (J.posted_at ? "<span>Posted " + ago(J.posted_at) + "</span>" : "") + "</div>" +
      '<div class="stack-2"><span class="card-sub">Required skills</span><div class="chips-row">' + chips(J.skills_required, 30, "chip-cyan") + "</div></div>" +
      (J.skills_nice.length ? '<div class="stack-2"><span class="card-sub">Nice to have</span><div class="chips-row">' + chips(J.skills_nice, 30) + "</div></div>" : "") +
      (J.qualification ? '<p style="margin:0" class="muted">Qualification: ' + esc(J.qualification) + "</p>" : "") +
      (J.has_profile ? '<p style="margin:0"><a class="btn-link" href="#resume" id="tailor-link">Tailor my resume</a> · <a class="btn-link" href="#prep" id="prep-link">Prepare for the interview</a> · <a class="btn-link" href="#letters" id="letter-link">Write a cover letter</a></p>' : "") +
      (J.description ? '<details><summary class="card-sub" style="cursor:pointer">Read the job description</summary><p style="white-space:pre-wrap;font-size:14px;line-height:1.6">' + esc(J.description) + "</p></details>" : "") + "</div>" +
      '<div class="card card-stack" id="fit-card"><div class="row-between"><div class="stack-2"><h2 class="card-title">Your fit</h2>' + (fit ? '<span class="card-sub">Scored ' + ago(fit.computed_at) + ". Where you live is not scored. Weights: skills 42, qualification 21, experience 32, keywords 5.</span>" : "") +
      '</div><button type="button" class="btn btn-grad" id="match"' + (J.has_profile ? "" : " disabled") + ">" + (fit ? "Match again" : "Match me to this job") + "</button></div>" + matchBlock + "</div>" +
      '<div id="job-actions"></div></div>';
    if (apply) apply.jobActions(J, $("#job-actions"));
    var tl = $("#tailor-link");
    if (tl) tl.addEventListener("click", function () { preselectJob = J.id; });
    ["prep-link", "letter-link"].forEach(function (id) { var a = document.getElementById(id); if (a) a.addEventListener("click", function () { DOC_PRESELECT = J.id; }); });
    $("#match").addEventListener("click", function () {
      this.disabled = true;
      api("POST", "/api/candidate/jobs/" + encodeURIComponent(J.id) + "/match").then(function (r) {
        if (!r.ok) { $("#msg").innerHTML = notice("error", explain(r)); $("#match").disabled = false; return; }
        drawJob(r.data);
      });
    });
  }


  // =====================================================
  // TAILOR RESUME
  // =====================================================
  var preselectJob = "";
  var REWRITE_ERR = { no_resume: "Upload your resume on My profile first. Tailoring rewords lines you already wrote." };

  function renderResume() {
    var mine = ++navId;
    loading("Tailor resume");
    Promise.all([api("GET", "/api/candidate/versions"), api("GET", "/api/candidate/jobs")]).then(function (rs) {
      if (mine !== navId) return;
      if (!rs[0].ok) { failure("Tailor resume", rs[0].error); return; }
      drawResume(rs[0].data, rs[1].ok ? rs[1].data.jobs : []);
    });
  }

  function drawResume(D, jobs) {
    var opts = jobs.map(function (j) { return '<option value="' + esc(j.id) + '">' + esc(j.title + (j.company ? " · " + j.company : "")) + "</option>"; }).join("");
    var noResume = D.has_resume ? "" : notice("info", REWRITE_ERR.no_resume);
    var list = D.versions.length
      ? '<ul class="skill-rows">' + D.versions.map(function (v) {
        return '<li class="skill-row"><span class="skill-main"><strong><a href="#resume/' + esc(v.id) + '">' + esc(v.label) + "</a></strong><small class=\"faint\">" +
          ago(v.created_at) + " · " + v.rewrites + " line" + (v.rewrites === 1 ? "" : "s") + " reworded" + "</small></span>" +
          '<span class="mono">' + (v.score_before == null ? "" : Math.round(v.score_before) + " → " + Math.round(v.score_after)) + "</span></li>";
      }).join("") + "</ul>"
      : '<p class="empty-inline">No tailored resumes yet.</p>';
    view.innerHTML = '<div class="view">' + header("Tailor resume", LIVE) + '<div id="msg" aria-live="polite">' + noResume + "</div>" +
      '<div class="card card-stack"><h2 class="card-title">Tailor to a job</h2>' +
      '<p class="privacy-note">The AI only rewords lines you already wrote. It cannot add a number, tool or result your resume does not have, and anything that does is thrown away. Your original resume is never changed.</p>' +
      '<div class="field-group"><label class="label" for="t-job">An open job on Hiriq</label><select class="field field-sm" id="t-job"><option value="">Choose a job</option>' + opts + "</select></div>" +
      '<div class="field-group"><label class="label" for="t-text">…or paste a job description</label><textarea class="field paste-box" id="t-text" maxlength="12000" placeholder="Paste the whole post"></textarea></div>' +
      '<div class="actions-bar"><button type="button" class="btn btn-grad" id="t-go"' + (D.has_resume ? "" : " disabled") + ">Tailor my resume</button></div></div>" +
      '<div class="card card-stack"><div class="row-between"><h2 class="card-title">Saved versions</h2><span class="faint" style="font-size:13px">' + D.versions.length + " of " + D.max + "</span></div>" + list + "</div></div>";
    if (preselectJob) { $("#t-job").value = preselectJob; preselectJob = ""; }
    $("#t-go").addEventListener("click", function () {
      var jobId = $("#t-job").value, text = $("#t-text").value.trim();
      var body = jobId && !text ? { job_id: jobId } : !jobId && text ? { text: text } : null;
      if (!body) { $("#msg").innerHTML = notice("error", "Choose an open job, or paste a job description, not both."); return; }
      var btn = this; btn.disabled = true;
      var loader = work($("#msg"), "tailor", function () { btn.disabled = false; });
      api("POST", "/api/candidate/rewrite", body).then(function (r) {
        if (loader.cancelled) return;
        if (!r.ok) { btn.disabled = false; $("#msg").innerHTML = notice("error", (r.data && r.data.detail && r.data.detail.message) || explain(r)); return; }
        window.location.hash = "#resume/" + r.data.id;
      });
    });
  }

  function renderVersion(id) {
    var mine = ++navId;
    loading("Tailored resume");
    api("GET", "/api/candidate/versions/" + encodeURIComponent(id)).then(function (r) {
      if (mine !== navId) return;
      if (!r.ok) { failure("Tailored resume", r.status === 404 ? "That version does not exist." : r.error); return; }
      drawVersion(r.data);
    });
  }

  function drawVersion(V) {
    var c = V.content || {};
    var rewrites = (c.rewrites || []).length
      ? '<ul class="rewrite-list">' + c.rewrites.map(function (w) {
        return '<li class="rewrite"><span class="was">' + esc(w.original) + '</span><span class="now">' + esc(w.rewritten) + "</span>" + (w.why ? "<small>" + esc(w.why) + "</small>" : "") + "</li>";
      }).join("") + "</ul>"
      : '<p class="empty-inline">No line could be reworded safely for this job, so the text is your resume as it was.</p>';
    var dropped = (c.dropped || []).length
      ? '<p class="privacy-note">' + c.dropped.length + " suggestion" + (c.dropped.length === 1 ? " was" : "s were") + " thrown away because they did not stick to your resume: " +
        c.dropped.map(function (d) { return esc(d.reason); }).filter(function (x, i, a) { return a.indexOf(x) === i; }).join("; ") + ".</p>" : "";
    var scores = V.score_before == null ? "" : '<div class="score-pair"><span class="mono">' + Math.round(V.score_before) + " → " + Math.round(V.score_after) +
      '</span><small class="faint">fit with this job, before and after. Most of your fit comes from your listed skills, so wording changes it only a little.</small></div>';
    view.innerHTML = '<div class="view">' + header(V.label, LIVE) + '<p style="margin:0"><a class="btn-link" href="#resume">Back to tailored resumes</a></p><div id="msg" aria-live="polite"></div>' +
      '<div class="card card-stack">' + scores +
      (c.summary ? '<div class="stack-2"><span class="card-sub">Suggested summary</span><p style="margin:0">' + esc(c.summary) + "</p></div>" : "") +
      ((c.skills_first || []).length ? '<div class="stack-2"><span class="card-sub">Put these skills first</span><div class="chips-row">' + chips(c.skills_first, 12, "chip-cyan") + "</div></div>" : "") + "</div>" +
      '<div class="card card-stack"><h2 class="card-title">Lines reworded</h2>' + rewrites + dropped + "</div>" +
      ((c.gaps || []).length ? '<div class="card card-stack"><h2 class="card-title">This job wants these, your resume does not show them</h2><div class="chips-row">' + chips(c.gaps, 20, "chip-neutral") +
        '</div><p class="privacy-note">Add one only if it is true: learn it, or point to where you have used it. It is never written in for you.</p></div>' : "") +
      '<div class="card card-stack"><div class="row-between"><h2 class="card-title">Tailored resume text</h2><span class="actions-bar"><button type="button" class="btn btn-outline" id="v-copy">Copy</button>' +
      '<button type="button" class="btn btn-outline" id="v-dl">Download .txt</button></span></div>' +
      '<textarea class="field resume-edit" id="v-text" maxlength="30000" aria-label="Tailored resume text">' + esc(V.text) + "</textarea>" +
      '<div class="actions-bar"><button type="button" class="btn btn-grad" id="v-save">Save edits</button></div></div>' +
      '<div class="card card-stack"><div class="field-group"><label class="label" for="v-label">Name</label><input class="field field-sm" id="v-label" maxlength="120" value="' + esc(V.label) + '"></div>' +
      '<div class="actions-bar"><button type="button" class="btn btn-outline" id="v-rename">Rename</button><button type="button" class="btn-link" id="v-del">Delete this version</button></div></div></div>';
    function patch(body, ok) {
      api("PATCH", "/api/candidate/versions/" + encodeURIComponent(V.id), body).then(function (r) {
        if (!r.ok) { $("#msg").innerHTML = notice("error", (r.data && r.data.detail && r.data.detail.message) || explain(r)); return; }
        V = r.data; $("#msg").innerHTML = notice("good", ok);
      });
    }
    $("#v-save").addEventListener("click", function () { patch({ text: $("#v-text").value }, "Saved."); });
    $("#v-rename").addEventListener("click", function () { patch({ label: $("#v-label").value }, "Renamed."); });
    $("#v-copy").addEventListener("click", function () {
      var t = $("#v-text").value;
      (navigator.clipboard ? navigator.clipboard.writeText(t) : Promise.reject()).then(function () { $("#msg").innerHTML = notice("good", "Copied."); },
        function () { $("#v-text").select(); $("#msg").innerHTML = notice("info", "Select all and copy with Ctrl+C."); });
    });
    $("#v-dl").addEventListener("click", function () {
      var a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([$("#v-text").value], { type: "text/plain" }));
      a.download = (V.label || "resume").replace(/[^\w\- ]+/g, "").trim().replace(/\s+/g, "-") + ".txt";
      document.body.appendChild(a); a.click(); a.remove();
    });
    $("#v-del").addEventListener("click", function () {
      if (!window.confirm("Delete this tailored resume? Your original resume stays.")) return;
      api("DELETE", "/api/candidate/versions/" + encodeURIComponent(V.id)).then(function (r) { r.ok ? (window.location.hash = "#resume") : ($("#msg").innerHTML = notice("error", explain(r))); });
    });
  }


  // =====================================================
  // RECOMMENDED (open Hiriq jobs, best fit first)
  // =====================================================
  var recMin = "30", recMode = "";

  function renderRecommended() {
    var mine = ++navId;
    loading("Recommended");
    var qs = "?min_score=" + encodeURIComponent(recMin) + (recMode ? "&work_mode=" + encodeURIComponent(recMode) : "");
    api("GET", "/api/candidate/recommendations" + qs).then(function (r) {
      if (mine !== navId) return;
      if (r.status === 409) {
        view.innerHTML = '<div class="view">' + header("Recommended", LIVE) + notice("info", "Add your resume or some skills on My profile first, then we can suggest jobs.") + '<p><a class="btn btn-grad" href="#profile">Go to My profile</a></p></div>';
        return;
      }
      if (!r.ok) { failure("Recommended", r.error); return; }
      drawRecommended(r.data);
    });
  }

  function recCard(j) {
    var f = j.fit;
    return '<article class="card job-card"><div class="stack-2" style="flex:1;min-width:240px"><h3><a href="#jobs/' + esc(j.id) + '">' + esc(j.title) + '</a></h3><div class="job-meta">' + jobMeta(j) + "</div>" +
      '<p class="rec-why">' + esc(j.reason) + "</p>" +
      (j.matched.length ? '<div class="chips-row"><small class="faint">You have</small> ' + chips(j.matched, 6, "chip-cyan") + "</div>" : "") +
      (j.gaps.length ? '<div class="chips-row"><small class="faint">To build</small> ' + chips(j.gaps, 4, "chip-neutral") + "</div>" : "") + "</div>" +
      '<div class="fit-side"><span class="score-chip' + (f.score >= 70 ? " strong" : "") + '">' + f.score + '</span><small class="faint">of 100</small>' +
      '<a class="btn btn-outline" href="#jobs/' + esc(j.id) + '" style="min-height:38px">See why</a></div></article>';
  }

  function drawRecommended(D) {
    var list = D.recommended.length ? '<div class="job-list">' + D.recommended.map(recCard).join("") + "</div>"
      : '<div class="card"><p class="empty-inline">' + (D.considered ? "No open jobs reach that fit yet. Lower the minimum fit, or add skills on My profile." : "No open jobs with listed skills yet. Check back soon, or search outside jobs.") + "</p></div>";
    view.innerHTML = '<div class="view">' + header("Recommended", LIVE) +
      '<div class="toolbar"><label class="faint" style="font-size:13px" for="r-min">Show fit of at least</label><select class="field field-sm" id="r-min" style="max-width:110px">' +
      ["0", "30", "50", "70"].map(function (v) { return '<option value="' + v + '"' + (String(D.min_score) === v ? " selected" : "") + ">" + v + "</option>"; }).join("") + "</select>" +
      '<select class="field field-sm" id="r-mode" style="max-width:150px" aria-label="Work mode"><option value="">Any work mode</option>' +
      ["onsite", "hybrid", "remote"].map(function (v) { return '<option value="' + v + '"' + (recMode === v ? " selected" : "") + ">" + v + "</option>"; }).join("") + "</select>" +
      '<span class="faint" style="font-size:13px">' + D.considered + " open jobs checked · " + D.strong + " strong" + (D.hidden_below ? " · " + D.hidden_below + " below your minimum" : "") + "</span></div>" + list +
      '<p class="privacy-note">Ranked by skills, qualification and experience from your resume. Where you live and your name are not scored.</p></div>';
    $("#r-min").addEventListener("change", function () { recMin = this.value; renderRecommended(); });
    $("#r-mode").addEventListener("change", function () { recMode = this.value; renderRecommended(); });
  }

  // =====================================================
  // SEARCH OUTSIDE JOBS
  // =====================================================
  var extState = { q: "", loc: "", radius: 20, page: 1, result: null };

  function renderSearch() {
    var mine = ++navId;
    loading("Search outside jobs");
    Promise.all([api("GET", "/api/candidate/external/status"), api("GET", "/api/candidate/me")]).then(function (rs) {
      if (mine !== navId) return;
      if (!rs[0].ok) { failure("Search outside jobs", rs[0].error); return; }
      if (!extState.loc && rs[1].ok && rs[1].data.location) extState.loc = rs[1].data.location;   // fills the box only; it is not scored
      drawSearch(rs[0].data.configured, rs[1].ok ? rs[1].data : {});
    });
  }

  function matchBadge(j, res) {
    var m = j.match;
    if (m) {
      var tone = m.score >= 70 ? "match-high" : m.score >= 40 ? "match-mid" : "match-low";
      return '<span class="match-pill ' + tone + '" title="Estimated from the words of the post by rules, not read by AI. Press Detailed analysis to see how.">' + m.score + '% match<small>estimated</small></span>';
    }
    return '<span class="match-pill match-none" title="">' + (res.can_score ? "No estimate" : "Add your resume to see your match") + "</span>";
  }

  function extCard(j, i, me, res) {
    var tooShort = (j.description || "").length < 200, m = j.match;
    var lines = "";
    if (m) {
      lines = '<div class="chips-row"><small class="faint">You show</small> ' + (m.matched.length ? chips(m.matched, 8, "chip-cyan") : '<span class="faint">none of its skills</span>') + "</div>" +
        (m.missing.length ? '<div class="chips-row"><small class="faint">Missing</small> ' + chips(m.missing, 5, "") + "</div>" : "");
    } else if (res.can_score) {
      lines = '<small class="faint">This post names no skill Hiriq recognises, so there is no honest number. Open it to read it yourself.</small>';
    }
    return '<article class="card ext-card" data-i="' + i + '"><div class="row-between"><div class="stack-2"><h3 style="margin:0">' + esc(j.title) + '</h3><div class="job-meta">' +
      [j.company, j.location, j.remote ? "remote" : "", j.source ? "via " + j.source : "", j.posted_at ? "posted " + ago(j.posted_at) : ""].filter(Boolean).map(function (x) { return "<span>" + esc(x) + "</span>"; }).join("") + "</div></div>" +
      matchBadge(j, res) + "</div>" + lines +
      (j.description ? '<details><summary class="card-sub" style="cursor:pointer">Read the description</summary><div class="ext-desc">' + esc(j.description) + "</div></details>" : "") +
      '<div class="ext-actions">' + (j.apply_url ? '<a class="btn btn-outline" href="' + esc(j.apply_url) + '" target="_blank" rel="noopener noreferrer">Open the posting</a>' : "") +
      '<button type="button" class="btn btn-grad" data-act="detail"' + (m && j.job_ref ? "" : " disabled") + ">Detailed analysis</button>" +
      '<button type="button" class="btn btn-outline" data-act="fit"' + (tooShort || !me.has_profile ? " disabled" : "") + ">Check with AI</button>" +
      '<button type="button" class="btn btn-outline" data-act="tailor"' + (tooShort || !me.has_resume ? " disabled" : "") + ">Tailor my resume</button></div>" +
      (tooShort ? '<small class="faint">This post is too short for the AI check. Open it and paste the full text in Jobs &amp; match.</small>' : "") + '<div class="card-stack" data-out aria-live="polite"></div></article>';
  }

  function runSearch(me, page) {
    $("#s-go").disabled = true;
    $("#msg").innerHTML = notice("info", "Searching…");
    api("GET", "/api/candidate/external?q=" + encodeURIComponent(extState.q) + (extState.loc ? "&location=" + encodeURIComponent(extState.loc) : "") +
      "&radius=" + extState.radius + "&page=" + page).then(function (r) {
      if (!r.ok) { $("#s-go").disabled = false; $("#msg").innerHTML = notice("error", (r.data && r.data.detail && r.data.detail.message) || explain(r)); return; }
      extState.result = r.data; extState.page = page; drawSearch(true, me);
    });
  }

  function drawSearch(configured, me) {
    if (!configured) {
      view.innerHTML = '<div class="view">' + header("Search outside jobs", LIVE) + notice("info", "The outside job feed is not switched on for this server yet. The person running Hiriq adds a Jobs API key (RAPIDAPI_KEY) to turn it on. Until then, use Recommended and Jobs & match.") + "</div>";
      return;
    }
    var res = extState.result;
    var pager = res && res.jobs.length ? '<div class="actions-bar"><button type="button" class="btn btn-outline" id="s-prev"' + (extState.page <= 1 ? " disabled" : "") + '>Previous page</button><span class="faint" style="font-size:13px">Page ' + extState.page +
      ' · best estimated match first on each page</span><button type="button" class="btn btn-outline" id="s-next"' + (extState.page >= 5 || !res.has_more ? " disabled" : "") + ">Next page</button></div>" : "";
    var list = !res ? "" : res.jobs.length ? '<div class="job-list">' + res.jobs.map(function (j, i) { return extCard(j, i, me, res); }).join("") + "</div>" + pager
      : '<div class="card"><p class="empty-inline">Nothing found for that search. Try a broader title.</p></div>';
    var radii = [10, 20, 50, 100].map(function (n) { return '<option value="' + n + '"' + (n === extState.radius ? " selected" : "") + ">Within " + n + " km</option>"; }).join("");
    view.innerHTML = '<div class="view">' + header("Search outside jobs", LIVE) + '<div id="msg" aria-live="polite"></div>' +
      '<form class="toolbar" id="s-form"><input class="field field-sm" id="s-q" placeholder="Job title or skill, e.g. data analyst" maxlength="100" value="' + esc(extState.q) + '" aria-label="Job title or skill" required minlength="2">' +
      '<input class="field field-sm" id="s-loc" placeholder="City (optional)" maxlength="100" value="' + esc(extState.loc) + '" aria-label="City">' +
      '<select class="field field-sm" id="s-rad" aria-label="Distance">' + radii + "</select>" +
      '<button type="submit" class="btn btn-grad" id="s-go">Search</button></form>' + list +
      '<p class="privacy-note">These come from other job sites, so the text is theirs. The percentage is an estimate: Hiriq reads the skills, years and degree the post mentions and scores them against your profile with the same rules as Hiriq jobs, so it can miss what a post leaves unsaid. Detailed analysis shows exactly how it was worked out. Your location only fills the search box; it is never scored.</p></div>';
    $("#s-form").addEventListener("submit", function (e) {
      e.preventDefault();
      extState.q = $("#s-q").value.trim(); extState.loc = $("#s-loc").value.trim(); extState.radius = Number($("#s-rad").value) || 20;
      if (extState.q.length < 2) return;
      runSearch(me, 1);
    });
    if (res && res.jobs.length) {
      $("#s-prev").addEventListener("click", function () { runSearch(me, extState.page - 1); });
      $("#s-next").addEventListener("click", function () { runSearch(me, extState.page + 1); });
    }
    view.querySelectorAll(".ext-card").forEach(function (card) {
      var job = res.jobs[Number(card.getAttribute("data-i"))], out = card.querySelector("[data-out]");
      card.addEventListener("click", function (e) {
        var act = e.target.getAttribute && e.target.getAttribute("data-act");
        if (!act) return;
        var btn = e.target; btn.disabled = true;
        if (act === "detail") {
          var dl = work(out, "detail", function () { btn.disabled = false; });
          api("GET", "/api/candidate/external/jobs/" + encodeURIComponent(job.job_ref) + "/fit").then(function (r) {
            if (dl.cancelled) return;
            btn.disabled = false;
            if (!r.ok) { out.innerHTML = notice("error", (r.data && r.data.detail && r.data.detail.message) || explain(r)); return; }
            var d = r.data;
            out.innerHTML = matchHtml({ score: d.score, parts: d.parts, explanation: d.explanation, summary: d.summary, assessed_weight: d.assessed_weight }) +
              '<p class="privacy-note">' + esc(d.basis) + "</p>";
          });
        } else if (act === "fit") {
          var fl = work(out, "fit", function () { btn.disabled = false; });
          api("POST", "/api/candidate/match/paste", { text: job.description }).then(function (r) {
            if (fl.cancelled) return;
            btn.disabled = false;
            if (!r.ok) { out.innerHTML = notice("error", (r.data && r.data.detail && r.data.detail.message) || explain(r)); return; }
            var d = r.data;
            out.innerHTML = matchHtml({ score: d.score, parts: d.parts, explanation: d.explanation, summary: d.summary, assessed_weight: d.assessed_weight });
          });
        } else {
          var tl2 = work(out, "tailor", function () { btn.disabled = false; });
          api("POST", "/api/candidate/rewrite", { text: job.description }).then(function (r) {
            if (tl2.cancelled) return;
            if (!r.ok) { btn.disabled = false; out.innerHTML = notice("error", (r.data && r.data.detail && r.data.detail.message) || explain(r)); return; }
            window.location.hash = "#resume/" + r.data.id;
          });
        }
      });
    });
  }


  // =====================================================
  // INTERVIEW PREP and COVER LETTERS (one job in, one saved document out)
  // =====================================================
  var DOC_PRESELECT = "";

  function docIndex(cfg2) {
    var mine = ++navId;
    loading(cfg2.title);
    Promise.all([api("GET", "/api/candidate/" + cfg2.list), api("GET", "/api/candidate/jobs")]).then(function (rs) {
      if (mine !== navId) return;
      if (!rs[0].ok) { failure(cfg2.title, rs[0].error); return; }
      var D = rs[0].data, items = D[cfg2.key], jobs = rs[1].ok ? rs[1].data.jobs : [];
      var opts = jobs.map(function (j) { return '<option value="' + esc(j.id) + '">' + esc(j.title + (j.company ? " · " + j.company : "")) + "</option>"; }).join("");
      var list = items.length ? '<ul class="skill-rows">' + items.map(function (v) {
        return '<li class="skill-row"><span class="skill-main"><strong><a href="#' + cfg2.route + "/" + esc(v.id) + '">' + esc(v.label || ("For " + (v.job_title || "a job"))) + "</a></strong><small class=\"faint\">" +
          ago(v.created_at) + (v.questions != null ? " · " + v.questions + " questions" : "") + "</small></span></li>";
      }).join("") + "</ul>" : '<p class="empty-inline">Nothing saved yet.</p>';
      view.innerHTML = '<div class="view">' + header(cfg2.title, LIVE) + '<div id="msg" aria-live="polite">' + (D.has_resume ? "" : notice("info", "Upload your resume on My profile first. " + cfg2.title + " is built from what you have already written.")) + "</div>" +
        '<div class="card card-stack"><h2 class="card-title">' + cfg2.make + "</h2><p class=\"privacy-note\">" + cfg2.note + "</p>" +
        '<div class="field-group"><label class="label" for="d-job">An open job on Hiriq</label><select class="field field-sm" id="d-job"><option value="">Choose a job</option>' + opts + "</select></div>" +
        '<div class="field-group"><label class="label" for="d-text">…or paste a job description</label><textarea class="field paste-box" id="d-text" maxlength="12000" placeholder="Paste the whole post"></textarea></div>' +
        (cfg2.tones ? '<div class="field-group"><label class="label" for="d-tone">Tone</label><select class="field field-sm" id="d-tone" style="max-width:200px"><option value="professional">Professional</option><option value="friendly">Friendly</option></select></div>' : "") +
        '<div class="actions-bar"><button type="button" class="btn btn-grad" id="d-go"' + (D.has_resume ? "" : " disabled") + ">" + cfg2.button + "</button></div></div>" +
        '<div class="card card-stack"><div class="row-between"><h2 class="card-title">Saved</h2><span class="faint" style="font-size:13px">' + items.length + " of " + D.max + "</span></div>" + list + "</div></div>";
      if (DOC_PRESELECT) { $("#d-job").value = DOC_PRESELECT; DOC_PRESELECT = ""; }
      $("#d-go").addEventListener("click", function () {
        var jobId = $("#d-job").value, text = $("#d-text").value.trim();
        var body = jobId && !text ? { job_id: jobId } : !jobId && text ? { text: text } : null;
        if (!body) { $("#msg").innerHTML = notice("error", "Choose an open job, or paste a job description, not both."); return; }
        if (cfg2.tones) body.tone = $("#d-tone").value;
        var btn = this; btn.disabled = true;
        var loader = work($("#msg"), cfg2.kind, function () { btn.disabled = false; });
        api("POST", "/api/candidate/" + cfg2.make_path, body).then(function (r) {
          if (loader.cancelled) return;
          if (!r.ok) { btn.disabled = false; $("#msg").innerHTML = notice("error", (r.data && r.data.detail && r.data.detail.message) || explain(r)); return; }
          window.location.hash = "#" + cfg2.route + "/" + r.data.id;
        });
      });
    });
  }

  function docDelete(path, back, msgSel) {
    if (!window.confirm("Delete this? Your resume stays.")) return;
    api("DELETE", path).then(function (r) { r.ok ? (window.location.hash = back) : ($(msgSel).innerHTML = notice("error", explain(r))); });
  }

  var KIND_LABEL = { technical: "Technical", behavioural: "Behavioural", role: "About the role", gap: "Skills the job wants that your resume does not show" };

  function drawPrep(P) {
    var c = P.content || {}, groups = ["technical", "behavioural", "role", "gap"];
    var qHtml = groups.map(function (k) {
      var qs = (c.questions || []).filter(function (q) { return q.kind === k; });
      if (!qs.length) return "";
      return '<div class="card card-stack"><h2 class="card-title">' + esc(KIND_LABEL[k]) + '</h2><ul class="q-list">' + qs.map(function (q) {
        return '<li class="q-item"><strong>' + esc(q.question) + "</strong>" + (q.why ? "<small>" + esc(q.why) + "</small>" : "") +
          (q.resume_line ? "<small>From your resume:</small><blockquote>" + esc(q.resume_line) + "</blockquote>" : "") + (q.tip ? "<span>" + esc(q.tip) + "</span>" : "") + "</li>";
      }).join("") + "</ul></div>";
    }).join("");
    var gaps = (c.gaps || []).length ? '<div class="card card-stack"><h2 class="card-title">Be ready to be honest about these</h2><ul class="skill-rows">' + c.gaps.map(function (g) {
      return '<li class="skill-row"><span class="skill-main"><strong>' + esc(g.skill) + '</strong><small class="faint">' + (g.importance === "required" ? "Required" : "Nice to have") + "</small>" +
        "<span style=\"font-size:13.5px\">" + (g.related_to ? "Your resume shows a related skill, " + esc(g.related_to) + ". Say so, and explain what you would learn first." : "Your resume does not show this. Say so plainly, and describe the closest thing you have done.") + "</span></span></li>";
    }).join("") + "</ul></div>" : "";
    var stories = (c.stories || []).length ? '<div class="card card-stack"><h2 class="card-title">Stories to prepare</h2><ul class="q-list">' + c.stories.map(function (s) {
      return '<li class="q-item"><strong>' + esc(s.point) + "</strong><blockquote>" + esc(s.resume_line) + "</blockquote></li>";
    }).join("") + "</ul></div>" : "";
    var ask = (c.ask_them || []).length ? '<div class="card card-stack"><h2 class="card-title">Questions to ask them</h2><ul style="margin:0;padding-left:18px;display:grid;gap:6px">' +
      c.ask_them.map(function (a) { return "<li>" + esc(a) + "</li>"; }).join("") + "</ul></div>" : "";
    view.innerHTML = '<div class="view">' + header("Prep for " + (P.job_title || "a job"), LIVE) + '<p style="margin:0"><a class="btn-link" href="#prep">Back to interview prep</a></p><div id="msg" aria-live="polite"></div>' +
      '<p class="privacy-note">These are likely questions, not a promise of what you will be asked. Every resume line shown here is really in your resume' + (c.dropped ? "; " + c.dropped + " suggestion" + (c.dropped === 1 ? " was" : "s were") + " removed because they did not stick to it" : "") + ".</p>" +
      qHtml + gaps + stories + ask + '<p><button type="button" class="btn-link" id="p-del">Delete this prep</button></p></div>';
    $("#p-del").addEventListener("click", function () { docDelete("/api/candidate/preps/" + encodeURIComponent(P.id), "#prep", "#msg"); });
  }

  function drawLetter(L) {
    var dropped = ((L.content || {}).dropped || []);
    view.innerHTML = '<div class="view">' + header(L.label, LIVE) + '<p style="margin:0"><a class="btn-link" href="#letters">Back to cover letters</a></p><div id="msg" aria-live="polite"></div>' +
      '<p class="privacy-note">Written only from your resume' + (dropped.length ? "; " + dropped.length + " paragraph" + (dropped.length === 1 ? " was" : "s were") + " removed because they did not stick to it" : "") +
      ". Read it through and make it yours before you send it. Check the date and the greeting.</p>" +
      '<div class="card card-stack"><textarea class="field letter-edit" id="l-text" maxlength="12000" aria-label="Cover letter text">' + esc(L.text) + "</textarea>" +
      '<div class="actions-bar"><button type="button" class="btn btn-grad" id="l-save">Save edits</button><button type="button" class="btn btn-outline" id="l-pdf">Download PDF</button>' +
      '<button type="button" class="btn btn-outline" id="l-copy">Copy</button></div></div>' +
      '<div class="card card-stack"><div class="field-group"><label class="label" for="l-label">Name</label><input class="field field-sm" id="l-label" maxlength="120" value="' + esc(L.label) + '"></div>' +
      '<div class="actions-bar"><button type="button" class="btn btn-outline" id="l-rename">Rename</button><button type="button" class="btn-link" id="l-del">Delete this letter</button></div></div></div>';
    function patch(body, ok) {
      api("PATCH", "/api/candidate/letters/" + encodeURIComponent(L.id), body).then(function (r) {
        if (!r.ok) { $("#msg").innerHTML = notice("error", (r.data && r.data.detail && r.data.detail.message) || explain(r)); return; }
        L = r.data; $("#msg").innerHTML = notice("good", ok);
      });
    }
    $("#l-save").addEventListener("click", function () { patch({ text: $("#l-text").value }, "Saved."); });
    $("#l-rename").addEventListener("click", function () { patch({ label: $("#l-label").value }, "Renamed."); });
    $("#l-copy").addEventListener("click", function () {
      (navigator.clipboard ? navigator.clipboard.writeText($("#l-text").value) : Promise.reject()).then(function () { $("#msg").innerHTML = notice("good", "Copied."); },
        function () { $("#l-text").select(); $("#msg").innerHTML = notice("info", "Select all and copy with Ctrl+C."); });
    });
    $("#l-pdf").addEventListener("click", function () {
      var btn = this, s2 = window.HiriqAuth.current();
      if (!s2) { window.HiriqAuth.logout(); return; }
      btn.disabled = true;
      // Save what is on screen first, so the PDF has your latest edits.
      api("PATCH", "/api/candidate/letters/" + encodeURIComponent(L.id), { text: $("#l-text").value }).then(function (pr) {
        if (!pr.ok) { btn.disabled = false; $("#msg").innerHTML = notice("error", explain(pr)); return; }
        L = pr.data;
        return fetch(cfg.apiBase + "/api/candidate/letters/" + encodeURIComponent(L.id) + "/pdf", { headers: { Authorization: "Bearer " + s2.token } }).then(function (res) {
          if (!res.ok) throw new Error("pdf");
          return res.blob();
        }).then(function (blob) {
          var a = document.createElement("a");
          a.href = URL.createObjectURL(blob);
          a.download = (L.label || "cover-letter").replace(/[^\w\- ]+/g, "").trim().replace(/\s+/g, "-") + ".pdf";
          document.body.appendChild(a); a.click(); a.remove();
          btn.disabled = false;
        });
      }).catch(function () { btn.disabled = false; $("#msg").innerHTML = notice("error", "Could not make the PDF. Try again."); });
    });
    $("#l-del").addEventListener("click", function () { docDelete("/api/candidate/letters/" + encodeURIComponent(L.id), "#letters", "#msg"); });
  }

  function docDetail(title, path, draw) {
    var mine = ++navId;
    loading(title);
    api("GET", path).then(function (r) {
      if (mine !== navId) return;
      if (!r.ok) { failure(title, r.status === 404 ? "That does not exist." : r.error); return; }
      draw(r.data);
    });
  }

  // =====================================================
  // Router
  // =====================================================
  var helpers = {
    view: view, esc: esc, api: api, ago: ago, chips: chips, header: header, loading: loading, failure: failure, notice: notice, explain: explain,
    LIVE: LIVE, jobMeta: jobMeta, nav: function () { return ++navId; }, current: function (id) { return id === navId; }
  };
  var apply = window.HiriqCandidateApply ? window.HiriqCandidateApply(helpers) : null;

  var VIEWS = {
    profile: [function () { renderProfile(); }, "My profile"],
    insights: [function () { renderInsights(); }, "Insights"],
    recommended: [function () { renderRecommended(); }, "Recommended"],
    search: [function () { renderSearch(); }, "Search outside jobs"],
    prep: [function (rest) {
      rest[0] ? docDetail("Interview prep", "/api/candidate/preps/" + encodeURIComponent(decodeURIComponent(rest[0])), drawPrep)
        : docIndex({ kind: "prep", title: "Interview prep", list: "preps", key: "preps", route: "prep", make: "Prepare for a job", make_path: "prep", button: "Prepare me",
                     note: "Likely questions for the job, tied to lines you already wrote, plus honest notes on the skills your resume does not show." });
    }, "Interview prep"],
    letters: [function (rest) {
      rest[0] ? docDetail("Cover letter", "/api/candidate/letters/" + encodeURIComponent(decodeURIComponent(rest[0])), drawLetter)
        : docIndex({ kind: "letter", title: "Cover letters", list: "letters", key: "letters", route: "letters", make: "Write a cover letter", make_path: "letters", button: "Write my letter", tones: true,
                     note: "Written only from your resume. Anything that adds a number or a skill your resume does not have is thrown away, and your name and contact details are filled in for you." });
    }, "Cover letters"],
    resume: [function (rest) { rest[0] ? renderVersion(decodeURIComponent(rest[0])) : renderResume(); }, "Tailor resume"],
    jobs: [function (rest) { rest[0] ? renderJob(decodeURIComponent(rest[0])) : renderJobs(); }, "Jobs & match"],
    applications: [function () { apply ? apply.applications() : failure("Applications", "This part did not load. Refresh the page."); }, "Applications"]
  };
  function route() {
    var parts = (location.hash || "#profile").slice(1).split("/");
    var key = parts[0];
    if (!VIEWS[key]) key = "profile";
    document.querySelectorAll(".side-nav a").forEach(function (a) {
      if (a.getAttribute("href") === "#" + key) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    });
    document.title = VIEWS[key][1] + " · Hiriq candidate";
    VIEWS[key][0](parts.slice(1));
    window.scrollTo(0, 0);
  }

  document.getElementById("logout").addEventListener("click", function () { window.HiriqAuth.logout(); });
  if (session) {
    document.getElementById("me-name").textContent = session.user;
    document.getElementById("me-avatar").textContent = String(session.user || "C").charAt(0).toUpperCase();
  }
  window.addEventListener("hashchange", route);
  if (cfg.mode !== "api") {
    failure("My profile", 'The candidate workspace shows live data, so it needs the backend. Start it and set mode to "api" in assets/js/config.js, then log in again.');
  } else {
    route();
  }
})();
