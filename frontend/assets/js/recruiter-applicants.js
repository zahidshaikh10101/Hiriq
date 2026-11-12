/* Hiriq — recruiter: Applicants (people who applied to your jobs).
   A factory: recruiter.js calls window.HiriqApplicants(helpers) and gets { show(jobId, applicationId) } back.
     #applicants                     your jobs and how many people applied to each
     #applicants/<job id>            the people who applied to one job (newest first, or by fit)
     #applicants/<job id>/<app id>   one application: contact details, the resume and letter they sent, their message
   An applicant chose to send these details to you for this job, so contact details show here and nowhere else.
   Adding someone to the pipeline is your own click; nobody is added or moved automatically. The fit score is a guide, not a decision. */
window.HiriqApplicants = function (R) {
  var view = R.view, esc = R.esc, icon = R.icon, api = R.api;
  var STRONG = 70;
  var STAGE_LABEL = { sourced: "Sourced", shortlisted: "Shortlisted", interview: "Interview", offer: "Offer", hired: "Hired", rejected: "Rejected" };
  var sort = "new";

  function $(sel) { return view.querySelector(sel); }
  function say(r, fallback) {
    var d = r.data && r.data.detail;
    if (Array.isArray(d) && d.length) return d.slice(0, 2).map(function (e) { return String(e.msg || "").replace(/^Value error, /, ""); }).join(" ");
    return (d && d.message) || r.error || fallback || "Something went wrong. Try again.";
  }
  function notice(kind, text) {
    return '<div class="notice notice-' + kind + '" role="' + (kind === "error" ? "alert" : "status") + '" style="animation:none">' + icon("info", 18) + "<span>" + esc(text) + "</span></div>";
  }
  function years(n) { return n == null ? "—" : (n === 1 ? "1 yr" : +Number(n).toFixed(1) + " yrs"); }
  function scoreClass(n) { return n >= STRONG ? " strong" : n >= 40 ? " mid" : " low"; }
  function chips(list, max) {
    list = list || [];
    var shown = list.slice(0, max).map(function (s) { return '<span class="chip chip-neutral">' + esc(s) + "</span>"; }).join(" ");
    return shown ? shown + (list.length > max ? ' <span class="faint">+' + (list.length - max) + "</span>" : "") : '<span class="faint">none</span>';
  }
  function link(url, label) {
    return /^https?:\/\//i.test(url || "") ? '<a class="btn-link" href="' + esc(url) + '" target="_blank" rel="noopener noreferrer">' + esc(label) + "</a>" : "";
  }

  // =====================================================
  // entry
  // =====================================================
  function show(jobId, appId) {
    if (appId) { detail(jobId, appId); return; }
    if (jobId) { list(jobId); return; }
    jobs();
  }

  // ---------- my jobs ----------
  function jobs() {
    var mine = R.nav();
    R.loading("Applicants");
    api("GET", "/api/recruiter/applicants").then(function (r) {
      if (!R.current(mine)) return;
      if (!r.ok) { R.failure("Applicants", r.status === 403 ? "This area is for recruiter accounts." : say(r)); return; }
      var rows = r.data.jobs.map(function (j) {
        return '<tr><td><a class="job-link" href="#applicants/' + esc(j.id) + '"><span class="cell-stack"><strong>' + esc(j.title) + "</strong></span></a></td>" +
          '<td><span class="chip ' + (j.status === "open" ? "chip-cyan" : "chip-neutral") + '">' + (j.status === "open" ? "Open" : "Closed") + '</span></td><td class="mono">' + j.applicants + "</td>" +
          '<td><a class="btn btn-outline" style="min-height:36px" href="#applicants/' + esc(j.id) + '">' + (j.applicants ? "Review" : "Open") + "</a></td></tr>";
      }).join("");
      view.innerHTML = '<div class="view">' + R.header("Applicants", '<span class="phase-badge">' + r.data.total + (r.data.total === 1 ? " application" : " applications") + "</span>") +
        '<div class="card"><span class="card-sub">People on Hiriq who chose to apply to one of your jobs. They send you a copy of the resume and letter they picked, their message and their contact details. Nobody is moved or rejected for you.</span></div>' +
        (rows ? '<div class="card table-card"><div class="table-scroll"><table><thead><tr><th>Job</th><th>Status</th><th>Applicants</th><th></th></tr></thead><tbody>' + rows + "</tbody></table></div></div>"
          : '<div class="card"><p class="empty-inline">You have no published jobs yet. Publish a job under Jobs &amp; JDs and candidates on Hiriq can apply to it.</p></div>') + "</div>";
    });
  }

  // ---------- one job's applicants ----------
  function list(jobId) {
    var mine = R.nav();
    R.loading("Applicants");
    api("GET", "/api/recruiter/jobs/" + encodeURIComponent(jobId) + "/applicants?sort=" + sort).then(function (r) {
      if (!R.current(mine)) return;
      if (!r.ok) { R.failure("Applicants", r.status === 404 ? "That job could not be found." : say(r)); return; }
      var D = r.data;
      var rows = D.applicants.map(function (a) {
        var meta = [a.headline, a.location].filter(Boolean).join(" · ");
        var extras = [a.has_letter ? "Cover letter" : "", a.has_message ? "Message" : ""].filter(Boolean).map(function (x) { return '<span class="chip chip-violet">' + x + "</span>"; }).join(" ");
        return '<tr><td><a class="job-link" href="#applicants/' + esc(jobId) + "/" + esc(a.id) + '"><span class="cell-stack"><strong>' + esc(a.name) + "</strong>" + (meta ? "<small>" + esc(meta) + "</small>" : "") + "</span></a></td>" +
          '<td class="nowrap">' + (a.fit_score == null ? '<span class="faint">—</span>' : '<span class="score-chip' + scoreClass(a.fit_score) + '">' + a.fit_score + "</span>") + '</td><td class="mono nowrap">' + esc(years(a.years)) + "</td>" +
          '<td><div class="chips-row">' + chips(a.skills, 4) + '</div></td><td><div class="chips-row">' + (extras || '<span class="faint">—</span>') + '</div></td>' +
          '<td class="nowrap">' + (a.stage ? '<span class="chip chip-cyan">' + esc(STAGE_LABEL[a.stage] || a.stage) + "</span>" : '<span class="faint">Not in pipeline</span>') + '</td><td class="nowrap faint">' + esc(R.ago(a.applied_at)) + "</td></tr>";
      }).join("");
      var table = rows ? '<div class="table-scroll"><table><thead><tr><th>Applicant</th><th>Fit</th><th>Experience</th><th>Skills</th><th>Sent</th><th>Pipeline</th><th>Applied</th></tr></thead><tbody>' + rows + "</tbody></table></div>"
        : '<p class="empty-inline pad">Nobody has applied to this job yet.</p>';
      view.innerHTML = '<div class="view">' + R.header("Applicants · " + D.job.title, '<span class="phase-badge">' + D.total + (D.total === 1 ? " applicant" : " applicants") + "</span>") +
        '<p style="margin:0"><a class="btn-link" href="#applicants">Back to all jobs</a> · <a class="btn-link" href="#pipeline/' + esc(jobId) + '">Open this job\'s pipeline</a></p>' +
        '<div class="card table-card"><div class="cand-toolbar"><div class="filters" role="group" aria-label="Sort applicants">' +
        '<button type="button" class="filter-pill" data-sort="new" aria-pressed="' + (sort === "new") + '">Newest first</button>' +
        '<button type="button" class="filter-pill" data-sort="fit" aria-pressed="' + (sort === "fit") + '">Best fit first</button></div></div>' + table + "</div>" +
        '<p class="privacy-note">The fit score uses the standard weights on the resume the person sent. It is a guide: read the application before you decide anything.</p></div>';
      view.querySelectorAll("[data-sort]").forEach(function (b) { b.addEventListener("click", function () { sort = b.getAttribute("data-sort"); list(jobId); }); });
    });
  }

  // ---------- one application ----------
  function detail(jobId, appId) {
    var mine = R.nav();
    R.loading("Applicants");
    api("GET", "/api/recruiter/jobs/" + encodeURIComponent(jobId) + "/applicants/" + encodeURIComponent(appId)).then(function (r) {
      if (!R.current(mine)) return;
      if (!r.ok) { R.failure("Applicants", r.status === 404 ? "That application is no longer here. The applicant may have withdrawn it." : say(r)); return; }
      draw(jobId, r.data, "");
    });
  }

  function draw(jobId, A, msg) {
    var c = A.contact || {};
    var email = /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(c.email || "") ? '<a class="btn-link" href="mailto:' + esc(c.email) + '">' + esc(c.email) + "</a>" : "—";
    var contact = '<dl class="kv"><div><dt>Email</dt><dd>' + email + "</dd></div><div><dt>Phone</dt><dd>" + esc(c.phone || "—") + "</dd></div><div><dt>Location</dt><dd>" + esc(c.location || A.location || "—") + "</dd></div>" +
      "<div><dt>Experience</dt><dd>" + esc(years(A.years)) + "</dd></div><div><dt>Qualification</dt><dd>" + esc(A.qualification || "—") + "</dd></div></dl>" +
      '<p style="margin:0">' + [link(c.linkedin_url, "LinkedIn"), link(c.github_url, "GitHub"), link(c.portfolio_url, "Website")].filter(Boolean).join(" · ") + "</p>";
    var pipeline = A.stage
      ? '<span class="chip chip-cyan">In pipeline: ' + esc(STAGE_LABEL[A.stage] || A.stage) + '</span><a class="btn btn-outline" href="#pipeline/' + esc(jobId) + '">Open pipeline</a>'
      : '<button type="button" class="btn btn-grad" id="to-pipeline">Add to pipeline</button><span class="faint" style="font-size:13px">They start in Sourced. You decide every move after that.</span>';
    view.innerHTML = '<div class="view">' + R.header(A.name, A.fit_score == null ? "" : '<span class="score-chip' + scoreClass(A.fit_score) + '">Fit ' + A.fit_score + "</span>") +
      '<p style="margin:0"><a class="btn-link" href="#applicants/' + esc(jobId) + '">Back to ' + esc(A.job.title) + "</a></p>" +
      '<div id="msg" aria-live="polite">' + (msg ? notice(msg[0], msg[1]) : "") + "</div>" +
      '<div class="card card-stack"><div class="chips-row"><span class="chip chip-neutral">Applied ' + esc(R.ago(A.applied_at)) + '</span><span class="chip chip-neutral">Sent: ' + esc(A.resume_label) + "</span>" +
      (A.letter_label ? '<span class="chip chip-violet">' + esc(A.letter_label) + "</span>" : "") + "</div>" + (A.headline ? '<p style="margin:0">' + esc(A.headline) + "</p>" : "") +
      '<div class="actions-bar">' + pipeline + "</div></div>" +
      '<div class="card card-stack"><h2 class="card-title">Contact details</h2>' + contact + "</div>" +
      (A.message ? '<div class="card card-stack"><h2 class="card-title">Message</h2><p style="margin:0;white-space:pre-wrap;line-height:1.6">' + esc(A.message) + "</p></div>" : "") +
      (A.letter_text ? '<div class="card card-stack"><h2 class="card-title">Cover letter</h2><div class="doc-view">' + esc(A.letter_text) + "</div></div>" : "") +
      '<div class="card card-stack"><h2 class="card-title">Skills</h2><div class="chips-row">' + chips(A.skills, 60) + "</div></div>" +
      '<div class="card card-stack"><h2 class="card-title">Resume they sent</h2><div class="doc-view">' + esc(A.resume_text) + "</div></div>" +
      '<p class="privacy-note">This is a copy taken when they applied. It does not change if they edit their own resume, and it disappears if they withdraw.</p></div>';
    var add = $("#to-pipeline");
    if (add) add.addEventListener("click", function () {
      add.disabled = true;
      api("POST", "/api/recruiter/jobs/" + encodeURIComponent(jobId) + "/pipeline", { candidate_ids: [A.candidate_id] }).then(function (r) {
        if (!r.ok) { $("#msg").innerHTML = notice("error", say(r)); add.disabled = false; return; }
        A.stage = "sourced";
        draw(jobId, A, ["good", A.name + " is in the Sourced column."]);
      });
    });
  }

  return { show: show };
};
