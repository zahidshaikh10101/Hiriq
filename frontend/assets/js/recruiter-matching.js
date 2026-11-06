/* Hiriq — recruiter: Matching (rank the candidate pool against one job).
   A factory: recruiter.js calls window.HiriqMatching(helpers) and gets { show(jobId) } back.
   Step 1 is instant and rule based (skills, qualification, experience, location and keywords). Step 2, started by itself afterwards, is an optional AI look
   at the gaps of the top candidates; if it is unavailable the ranking above it is still complete. Every skill shows the resume
   line it came from. Parts the resume cannot answer are shown as "not assessed", never as zero.
   Phase 5 adds, under each candidate: thumbs up/down (labels for the ranker later, they never change a score) and
   "Add to pipeline" (or the stage they are already in). */
window.HiriqMatching = function (R) {
  var view = R.view, esc = R.esc, icon = R.icon, api = R.api;

  var PARTS = [["skills", "Skills"], ["qualification", "Qualification"], ["experience", "Experience"], ["location", "Location"], ["keywords", "Keywords"]];
  var STATUS = {
    listed: "In the skills list", implied: "Implied", text: "Used in a job", related: "Related, half credit",
    ai_related: "Related (AI), half credit", missing: "Not found"
  };
  var STAGE = { sourced: "Sourced", shortlisted: "Shortlisted", interview: "Interview", offer: "Offer", hired: "Hired", rejected: "Rejected" };
  var THUMB = '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path fill="currentColor" d="M2 21h4V9H2v12zM23 10c0-1.1-.9-2-2-2h-6.3l.95-4.57.03-.32c0-.41-.17-.79-.44-1.06L14.17 1 7.59 7.59C7.22 7.95 7 8.45 7 9v10c0 1.1.9 2 2 2h9c.83 0 1.54-.5 1.84-1.22l3.02-7.05c.09-.23.14-.47.14-.73v-2z"/></svg>';

  // ---------- small helpers ----------
  function scoreClass(n) { return n >= 70 ? " strong" : n >= 40 ? " mid" : " low"; }
  function chips(list, cls) {
    return (list || []).map(function (s) { return '<span class="chip ' + (cls || "chip-neutral") + '">' + esc(s) + "</span>"; }).join(" ");
  }
  function say(r, fallback) { var d = r.data && r.data.detail; return (d && d.message) || r.error || fallback || "Something went wrong. Try again."; }
  function share(w, all) { var t = PARTS.reduce(function (n, p) { return n + (all[p[0]] || 0); }, 0); return t ? Math.round((w / t) * 100) : 0; }

  // =====================================================
  // state of the one open page
  // =====================================================
  var S = null;   // { token, jobId, jobs, data, weights, detail:{}, open, busy, ai:{state,text} }

  function alive() { return S && R.current(S.token); }

  // =====================================================
  // entry
  // =====================================================
  function show(jobId) {
    var mine = R.nav();
    R.loading("Matching");
    api("GET", "/api/recruiter/jobs").then(function (r) {
      if (!R.current(mine)) return;
      if (!r.ok) { R.failure("Matching", r.status === 403 ? "This area is for recruiter accounts." : say(r)); return; }
      S = { token: mine, jobId: jobId || "", jobs: r.data.jobs || [], data: null, weights: null, detail: {}, open: null, busy: false, ai: null };
      if (!S.jobId) { draw(); return; }
      api("GET", "/api/recruiter/jobs/" + encodeURIComponent(S.jobId) + "/matches").then(function (m) {
        if (!R.current(mine)) return;
        if (!m.ok) { S.problem = m.status === 404 ? "That job could not be found." : say(m); S.jobId = ""; draw(); return; }
        S.data = m.data; S.weights = Object.assign({}, m.data.weights);
        draw();
      });
    });
  }

  // =====================================================
  // drawing
  // =====================================================
  function picker() {
    var opts = S.jobs.map(function (j) {
      return '<option value="' + esc(j.id) + '"' + (j.id === S.jobId ? " selected" : "") + ">" + esc(j.title || "Untitled") + (j.status && j.status !== "open" ? " (" + esc(j.status) + ")" : "") + "</option>";
    }).join("");
    return '<div class="field-group"><label class="label" for="m-job">Job to match against</label>' +
      '<select class="field field-sm" id="m-job"><option value="">Choose a job…</option>' + opts + "</select></div>";
  }

  function weightsBox() {
    var d = S.data, w = S.weights, def = d.default_weights;
    var sliders = PARTS.map(function (p) {
      return '<div class="w-row"><label for="w-' + p[0] + '">' + p[1] + "</label>" +
        '<input type="range" min="0" max="100" step="5" id="w-' + p[0] + '" data-w="' + p[0] + '" value="' + w[p[0]] + '">' +
        '<span class="mono w-val" id="wv-' + p[0] + '">' + share(w[p[0]], w) + "%</span></div>";
    }).join("");
    var changed = PARTS.some(function (p) { return w[p[0]] !== def[p[0]]; });
    return '<div class="w-box"><div class="row-between"><span class="label">How much each part counts</span>' +
      '<button type="button" class="btn-link" id="w-reset"' + (changed ? "" : " hidden") + ">Reset to default</button></div>" + sliders +
      '<p class="hint" style="margin:0">Only these five things are scored. Qualification looks at the degree level, never the college. Name, gender, photo, college and age are never used.</p></div>';
  }

  function banners() {
    var s = S.data.stale, out = "";
    if (S.data.ranked && s.job_changed) out += '<div class="notice notice-warn" role="status">' + icon("warn", 18) + "<span>This job was edited after the last ranking. Rank again to use its latest requirements.</span></div>";
    if (S.data.ranked && s.new_candidates) out += '<div class="notice notice-info" role="status">' + icon("info", 18) + "<span>" + s.new_candidates + " candidate" + (s.new_candidates === 1 ? " was" : "s were") + " added since the last ranking and " + (s.new_candidates === 1 ? "is" : "are") + " not ranked yet.</span></div>";
    if (S.data.ranked && s.edited_candidates) out += '<div class="notice notice-info" role="status">' + icon("info", 18) + "<span>" + s.edited_candidates + " candidate" + (s.edited_candidates === 1 ? " was" : "s were") + " edited since the last ranking, so " + (s.edited_candidates === 1 ? "their score" : "those scores") + " may be out of date. Rank again to refresh.</span></div>";
    if (S.data.ranked && S.data.old_version) out += '<div class="notice notice-info" role="status">' + icon("info", 18) + "<span>" + S.data.old_version + " score" + (S.data.old_version === 1 ? " was" : "s were") + " made before qualification and keywords were added. Rank again to include them.</span></div>";
    return out;
  }

  function partBars(parts, assessed) {
    return PARTS.map(function (p) {
      var x = (parts || {})[p[0]] || {};
      if (!x.assessed) {
        return '<div class="pbar na" title="Not enough information in the resume to assess this part"><span class="pbar-l">' + p[1] + '</span><span class="pbar-t"><i></i></span><span class="pbar-v">not assessed</span></div>';
      }
      var n = Math.round(x.score);
      return '<div class="pbar"><span class="pbar-l">' + p[1] + '</span><span class="pbar-t"><i class="' + scoreClass(n).trim() + '" style="width:' + Math.max(2, n) + '%"></i></span><span class="pbar-v mono">' + n + "</span></div>";
    }).join("");
  }

  // Thumbs and the pipeline link/button. Lives in the always-visible part of the row, outside the row's expand button.
  function pipeStrip(c) {
    var up = '<button type="button" class="thumb-btn up" data-fb="1" data-c="' + esc(c.candidate_id) + '" aria-pressed="' + (c.feedback === 1) + '" aria-label="Good match for ' + esc(c.name || "this candidate") + '" title="Good match">' + THUMB + "</button>";
    var down = '<button type="button" class="thumb-btn down" data-fb="-1" data-c="' + esc(c.candidate_id) + '" aria-pressed="' + (c.feedback === -1) + '" aria-label="Not a good match for ' + esc(c.name || "this candidate") + '" title="Not a good match">' + THUMB + "</button>";
    var where = c.stage
      ? '<a class="chip chip-cyan" href="#pipeline/' + esc(S.jobId) + '">In pipeline: ' + esc(STAGE[c.stage] || c.stage) + "</a>"
      : '<button type="button" class="btn-link" data-pipe="' + esc(c.candidate_id) + '"' + (S.data.job.status === "closed" ? " disabled" : "") + ">Add to pipeline</button>";
    return '<div class="m-pipe"><span class="thumbs" role="group" aria-label="Was this a good match?">' + up + down + "</span>" + where + "</div>";
  }

  function rowHtml(c, i) {
    var open = S.open === c.candidate_id;
    var missing = c.missing_required.length
      ? '<div class="chips-row"><span class="faint m-lbl">Missing</span>' + chips(c.missing_required.slice(0, 5), "chip-miss") + (c.missing_required.length > 5 ? ' <span class="faint">+' + (c.missing_required.length - 5) + "</span>" : "") + "</div>"
      : '<div class="chips-row"><span class="faint m-lbl">All required skills found</span></div>';
    var partial = c.assessed_weight != null && c.assessed_weight < 100
      ? '<div class="m-partial">' + (c.assessed_weight === 0
        ? "Not assessed: the resume gave nothing to score for this job."
        : "Scored on " + c.assessed_weight + "% of the criteria. The rest could not be read from the resume.") + "</div>" : "";
    var meta = [c.headline, c.location, c.years != null ? (c.years === 1 ? "1 yr" : +Number(c.years).toFixed(1) + " yrs") : ""].filter(Boolean).map(esc).join(" · ");
    return '<li class="m-row' + (open ? " open" : "") + '" data-cid="' + esc(c.candidate_id) + '">' +
      '<button type="button" class="m-head" aria-expanded="' + open + '" data-toggle="' + esc(c.candidate_id) + '">' +
      '<span class="rank">' + (i + 1) + "</span>" +
      '<span class="cell-stack m-who"><strong>' + esc(c.name || "Unnamed") + "</strong>" + (meta ? "<small>" + meta + "</small>" : "") + "</span>" +
      '<span class="m-badges">' + (c.source === "platform" ? '<span class="chip chip-violet">Hiriq member</span>' : "") + (c.ai_checked ? '<span class="chip chip-cyan" title="An AI model double-checked the gaps">AI-checked</span>' : "") + "</span>" +
      (c.assessed_weight === 0
        ? '<span class="score-chip low" title="Nothing in the resume could be scored for this job" aria-label="Not assessed">n/a</span></button>'
        : '<span class="score-chip' + scoreClass(c.score) + '" aria-label="Match score ' + c.score + ' out of 100">' + c.score + "</span></button>") +
      '<div class="m-body"><div class="m-bars">' + partBars(c.parts) + "</div>" + missing + partial + pipeStrip(c) + "</div>" +
      '<div class="m-detail" id="d-' + esc(c.candidate_id) + '"' + (open ? "" : " hidden") + ">" + (open ? detailHtml(c.candidate_id) : "") + "</div></li>";
  }

  function skillRow(s) {
    var cls = s.credit >= 1 ? "full" : s.credit > 0 ? "half" : "none";
    var via = s.via && (s.status === "implied" || s.status === "related") ? " (via " + esc(s.via) + ")" : "";
    return '<li class="sk sk-' + cls + '"><span class="sk-top"><strong>' + esc(s.skill) + '</strong><span class="sk-st">' + esc(STATUS[s.status] || s.status) + via + "</span></span>" +
      (s.evidence ? '<span class="sk-ev">“' + esc(s.evidence) + "”</span>" : "") + "</li>";
  }

  function detailHtml(cid) {
    var d = S.detail[cid];
    if (!d) return '<p class="empty-inline" role="status">Loading the reasons…</p>';
    if (d.error) return '<div class="notice notice-error" role="alert">' + icon("info", 18) + "<span>" + esc(d.error) + "</span></div>";
    var e = d.explanation || {}, sk = e.skills || {};
    var LBL = { qualification: "Qualification", experience: "Experience", location: "Location", keywords: "Keywords" };
    var parts = ["qualification", "experience", "location", "keywords"].map(function (k) {
      var x = e[k]; if (!x) return "";
      var label = LBL[k];
      var terms = k === "keywords" && x.assessed
        ? '<span class="chips-row">' + chips((x.matched || []).slice(0, 10), "chip-cyan") + " " + chips((x.missing || []).slice(0, 10), "chip-miss") + "</span>" : "";
      return '<li class="sk ' + (x.assessed ? "sk-full" : "sk-na") + '"><span class="sk-top"><strong>' + label + '</strong><span class="sk-st">' + (x.assessed ? Math.round(x.score) + " / 100" : "Not assessed") + "</span></span>" +
        (x.reason ? '<span class="sk-ev plain">' + esc(x.reason) + "</span>" : "") + terms + "</li>";
    }).join("");
    var judge = e.judge ? '<p class="hint">AI second look by ' + esc((e.judge.model || "a free model").replace(/:free$/, "")) + ". It can only add half credit, and only when it quotes a line that really is in the resume.</p>" : "";
    return '<p class="m-sum">' + esc(e.summary || "") + "</p>" +
      '<div class="sub-title">Required skills</div><ul class="sk-list">' + (sk.required || []).map(skillRow).join("") + "</ul>" +
      ((sk.nice || []).length ? '<div class="sub-title">Nice to have</div><ul class="sk-list">' + sk.nice.map(skillRow).join("") + "</ul>" : "") +
      '<div class="sub-title">Qualification, experience, location and keywords</div><ul class="sk-list">' + parts + "</ul>" + judge +
      '<div class="actions-bar"><a class="btn btn-outline" href="#candidates/' + encodeURIComponent(cid) + '">Open full profile</a></div>';
  }

  function aiLine() {
    var a = S.ai;
    if (!a) return "";
    var icn = a.state === "running" ? '<span class="spin" aria-hidden="true"></span>' : a.state === "failed" ? icon("info", 16) : icon("check", 16);
    return '<div class="ai-line ai-' + a.state + '" role="status">' + icn + "<span>" + esc(a.text) + "</span></div>";
  }

  function listHtml() {
    var d = S.data;
    if (!d.ranked) {
      return '<div class="card"><p class="empty-inline" style="padding:14px 0">' + (d.stale.new_candidates
        ? "Nobody is ranked for this job yet. Press <strong>Rank candidates</strong> to score the " + d.stale.new_candidates + " in your pool."
        : "Your pool has nobody to score yet. Upload resumes in Candidates, then come back.") + "</p></div>";
    }
    var c = d.counts;
    var line = '<p class="card-sub" style="margin:0">' + c.total + " ranked · " + c.strong + " scoring " + d.strong_score + "+ · " + c.ai_checked + " AI-checked" +
      (S.data.skipped ? " · " + S.data.skipped + " without a profile skipped" : "") + "</p>";
    var more = d.total > d.results.length ? '<p class="hint">Showing the top ' + d.results.length + " of " + d.total + ".</p>" : "";
    return line + '<ol class="m-list">' + d.results.map(rowHtml).join("") + "</ol>" + more;
  }

  function draw() {
    if (!alive()) return;
    var d = S.data, job = d && d.job;
    var head = R.header("Matching", "");
    if (!S.jobs.length) {
      view.innerHTML = '<div class="view">' + head + '<div class="card card-stack"><h2 class="card-title">Create a job first</h2><p class="muted" style="margin:0">Matching ranks your candidates against a job, so it needs one.</p>' +
        '<div class="actions-bar"><a class="btn btn-grad" href="#jobs/new">Create a job</a></div></div></div>';
      return;
    }
    var problem = S.problem ? '<div class="notice notice-error" role="alert">' + icon("info", 18) + "<span>" + esc(S.problem) + "</span></div>" : "";
    var body = "";
    if (d) {
      var needSkills = !(job.skills_required || []).length && !(job.skills_nice || []).length;
      body = '<div class="card card-stack">' +
        '<div class="stack-2"><h2 class="card-title">' + esc(job.title) + '</h2><span class="card-sub">' + [job.location, job.work_mode, job.experience_min != null ? job.experience_min + (job.experience_max != null ? "–" + job.experience_max : "+") + " yrs" : ""].filter(Boolean).map(esc).join(" · ") + "</span></div>" +
        '<div class="chips-row">' + (chips(job.skills_required, "chip-cyan") || '<span class="faint">No required skills</span>') + " " + chips(job.skills_nice) + "</div>" +
        (needSkills ? '<div class="notice notice-warn">' + icon("warn", 18) + '<span>This job lists no skills, so there is nothing to score. <a href="#jobs/' + esc(job.id) + '">Add skills to the job</a>.</span></div>' : "") +
        weightsBox() +
        '<div class="actions-bar"><button type="button" class="btn btn-grad" id="m-run"' + (needSkills || S.busy ? " disabled" : "") + ">" + (S.busy === "rank" ? "Ranking…" : d.ranked ? "Rank again" : "Rank candidates") + "</button>" +
        (d.ranked && !S.busy ? '<button type="button" class="btn btn-outline" id="m-ai">Run the AI check again</button>' : "") +
        '<a class="btn btn-outline" href="#pipeline/' + esc(job.id) + '">Open pipeline</a>' +
        '<span class="hint" style="max-width:420px">Scores come from clear rules first. The AI check only looks at the gaps of your top candidates and never lowers a score.</span></div></div>' +
        banners() + aiLine() + listHtml();
    }
    view.innerHTML = '<div class="view">' + head + problem + '<div class="card">' + picker() + "</div>" +
      (d ? body : '<div class="card"><p class="empty-inline" style="padding:14px 0">Pick a job to see how your candidates rank for it.</p></div>') + "</div>";
    wire();
  }

  // =====================================================
  // actions
  // =====================================================
  function wire() {
    var sel = view.querySelector("#m-job");
    if (sel) sel.addEventListener("change", function () { window.location.hash = sel.value ? "#matching/" + encodeURIComponent(sel.value) : "#matching"; });
    if (!S.data) return;
    view.querySelectorAll("[data-w]").forEach(function (el) {
      el.addEventListener("input", function () {
        S.weights[el.getAttribute("data-w")] = +el.value;
        PARTS.forEach(function (p) { var v = view.querySelector("#wv-" + p[0]); if (v) v.textContent = share(S.weights[p[0]], S.weights) + "%"; });
        var def = S.data.default_weights, reset = view.querySelector("#w-reset");
        if (reset) reset.hidden = !PARTS.some(function (p) { return S.weights[p[0]] !== def[p[0]]; });
      });
    });
    var reset = view.querySelector("#w-reset");
    if (reset) reset.addEventListener("click", function () { S.weights = Object.assign({}, S.data.default_weights); draw(); });
    var run = view.querySelector("#m-run"); if (run) run.addEventListener("click", rank);
    var ai = view.querySelector("#m-ai"); if (ai) ai.addEventListener("click", function () { review(true); });
    var list = view.querySelector(".m-list");
    if (list) list.addEventListener("click", function (e) {
      var fb = e.target.closest("[data-fb]");
      if (fb) { thumb(fb.getAttribute("data-c"), +fb.getAttribute("data-fb")); return; }
      var pipe = e.target.closest("[data-pipe]");
      if (pipe) { addToPipeline(pipe.getAttribute("data-pipe")); return; }
      var b = e.target.closest("[data-toggle]");
      if (b) toggle(b.getAttribute("data-toggle"));
    });
  }

  function rowFor(cid) {
    return (S.data.results || []).filter(function (r) { return r.candidate_id === cid; })[0];
  }

  function thumb(cid, label) {
    var c = rowFor(cid);
    if (!c) return;
    var next = c.feedback === label ? 0 : label;      // tapping the same thumb again clears it
    var tok = S.token;
    api("PUT", "/api/recruiter/jobs/" + encodeURIComponent(S.jobId) + "/matches/" + encodeURIComponent(cid) + "/feedback", { label: next }).then(function (r) {
      if (!alive() || S.token !== tok) return;
      if (!r.ok) { S.problem = say(r); draw(); return; }
      S.problem = ""; c.feedback = r.data.label; draw();
    });
  }

  function addToPipeline(cid) {
    var c = rowFor(cid);
    if (!c || c.stage) return;
    var tok = S.token;
    api("POST", "/api/recruiter/jobs/" + encodeURIComponent(S.jobId) + "/pipeline", { candidate_ids: [cid] }).then(function (r) {
      if (!alive() || S.token !== tok) return;
      if (!r.ok) { S.problem = say(r); draw(); return; }
      S.problem = ""; c.stage = "sourced"; draw();
    });
  }

  function rank() {
    if (S.busy) return;
    var tok = S.token, total = PARTS.reduce(function (n, p) { return n + (S.weights[p[0]] || 0); }, 0);
    if (total <= 0) { S.problem = "Give at least one part some weight."; draw(); return; }
    S.problem = ""; S.busy = "rank"; S.ai = null; draw();
    api("POST", "/api/recruiter/jobs/" + encodeURIComponent(S.jobId) + "/match", { weights: S.weights }).then(function (r) {
      if (!alive() || S.token !== tok) return;
      S.busy = false;
      if (!r.ok) { S.problem = say(r); draw(); return; }
      S.data = r.data; S.weights = Object.assign({}, r.data.weights); S.detail = {}; S.open = null;
      draw();
      if (r.data.results.length) review(false);
    });
  }

  function review(manual) {
    if (S.busy || !S.data || !S.data.ranked) return;
    var tok = S.token;
    S.busy = "ai"; S.ai = { state: "running", text: "AI is double-checking the gaps of your top candidates. You can read the ranking while it works." }; draw();
    api("POST", "/api/recruiter/jobs/" + encodeURIComponent(S.jobId) + "/match/review").then(function (r) {
      if (!alive() || S.token !== tok) return;
      S.busy = false;
      if (!r.ok) {
        S.ai = { state: "failed", text: "AI check unavailable: " + say(r) + " The ranking above is complete without it." };
        draw(); return;
      }
      var v = r.data.review || {};
      r.data.skipped = S.data.skipped; S.data = r.data; S.detail = {};
      if (v.nothing_to_check) S.ai = { state: "done", text: manual ? "Nothing new to check: every gap in the top candidates was already looked at." : "No gaps needed an AI look." };
      else {
        var t = v.judged + " candidate" + (v.judged === 1 ? "" : "s") + " checked";
        if (v.failed) t += ", " + v.failed + " could not be checked";
        if (v.unverified) t += ". " + v.unverified + " claim" + (v.unverified === 1 ? " was" : "s were") + " ignored because the quoted line is not in the resume";
        S.ai = { state: v.failed ? "failed" : "done", text: t + "." };
      }
      if (S.open) { var o = S.open; S.open = null; draw(); toggle(o); } else draw();
    });
  }

  function toggle(cid) {
    if (S.open === cid) { S.open = null; draw(); return; }
    S.open = cid;
    var tok = S.token;
    if (!S.detail[cid]) {
      api("GET", "/api/recruiter/jobs/" + encodeURIComponent(S.jobId) + "/matches/" + encodeURIComponent(cid)).then(function (r) {
        if (!alive() || S.token !== tok) return;
        S.detail[cid] = r.ok ? r.data : { error: say(r, "Could not load the reasons.") };
        var box = view.querySelector("#d-" + cid);
        if (box && S.open === cid) box.innerHTML = detailHtml(cid);
      });
    }
    draw();
  }

  return { show: show };
};
