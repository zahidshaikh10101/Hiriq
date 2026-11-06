/* Hiriq — candidate workspace. Live data from the backend (/api/candidate/*).
   Views are chosen by the URL hash: #profile #insights #jobs #jobs/<id>.
   Profile (resume upload, edit, who can see you), Insights (what your resume shows and what open jobs ask for) and
   Jobs & match (open jobs, your fit with the reasons, and a match for any job description you paste) are live.
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
      '<span class="card-sub">Off by default. When on, recruiters can find you by title, skills and experience. They never see your email, phone or links.</span></div>' +
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
      if (!window.confirm("Remove your resume and profile details? You will also be hidden from recruiters.")) return;
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
    var started = Date.now();
    msg.innerHTML = notice("info", "Reading your resume… 0 s");
    var tick = setInterval(function () {
      var el = $("#msg span"); if (el) el.textContent = "Reading your resume… " + Math.round((Date.now() - started) / 1000) + " s"; else clearInterval(tick);
    }, 1000);
    var s = window.HiriqAuth.current();
    if (!s) { clearInterval(tick); window.HiriqAuth.logout(); return; }
    fetch(cfg.apiBase + "/api/candidate/resume", {
      method: "POST",
      headers: { Authorization: "Bearer " + s.token, "X-Filename": encodeURIComponent(file.name), "Content-Type": "application/octet-stream" },
      body: file
    }).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (data) { return { ok: res.ok, status: res.status, data: data }; });
    }).catch(function () {
      return { ok: false, status: 0, data: {}, error: "Could not reach the backend. Is it running?" };
    }).then(function (r) {
      clearInterval(tick);
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
      out.innerHTML = notice("info", "Reading the job description…");
      api("POST", "/api/candidate/match/paste", { text: $("#paste").value }).then(function (r) {
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
      (J.description ? '<details><summary class="card-sub" style="cursor:pointer">Read the job description</summary><p style="white-space:pre-wrap;font-size:14px;line-height:1.6">' + esc(J.description) + "</p></details>" : "") + "</div>" +
      '<div class="card card-stack" id="fit-card"><div class="row-between"><div class="stack-2"><h2 class="card-title">Your fit</h2>' + (fit ? '<span class="card-sub">Scored ' + ago(fit.computed_at) + ". Where you live is not scored. Weights: skills 42, qualification 21, experience 32, keywords 5.</span>" : "") +
      '</div><button type="button" class="btn btn-grad" id="match"' + (J.has_profile ? "" : " disabled") + ">" + (fit ? "Match again" : "Match me to this job") + "</button></div>" + matchBlock + "</div></div>";
    $("#match").addEventListener("click", function () {
      this.disabled = true;
      api("POST", "/api/candidate/jobs/" + encodeURIComponent(J.id) + "/match").then(function (r) {
        if (!r.ok) { $("#msg").innerHTML = notice("error", explain(r)); $("#match").disabled = false; return; }
        drawJob(r.data);
      });
    });
  }

  // =====================================================
  // Router
  // =====================================================
  var VIEWS = {
    profile: [function () { renderProfile(); }, "My profile"],
    insights: [function () { renderInsights(); }, "Insights"],
    jobs: [function (rest) { rest[0] ? renderJob(decodeURIComponent(rest[0])) : renderJobs(); }, "Jobs & match"]
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
