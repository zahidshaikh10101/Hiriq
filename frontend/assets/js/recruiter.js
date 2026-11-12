/* Hiriq — recruiter workspace. Live data from the backend (/api/recruiter/*).
   Views are chosen by the URL hash: #overview #jobs #jobs/new #jobs/<id> #candidates #matching #pipeline #pipeline/<job id> #applicants #applicants/<job id> #applicants/<job id>/<application id> #ask.
   Overview (phase 1), Jobs & JDs (2), Candidates (3), Matching (4), Pipeline (5) and Ask the pool (6) are live. */
(function () {
  var view = document.getElementById("view");
  var cfg = window.HIRIQ_CONFIG;
  var session = window.HiriqAuth.current();

  // ---------- helpers ----------
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function fmt(n) { return Math.round(n).toLocaleString("en-IN"); }
  function icon(name, size, cls) {
    return '<svg class="i ' + (cls || "") + '" width="' + size + '" height="' + size + '" aria-hidden="true"><use href="#i-' + name + '"></use></svg>';
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
  function header(title, badge) {
    return '<header class="page-head"><div class="stack-2"><span class="faint" style="font-size:13px">Recruiter workspace</span><h1>' + esc(title) + "</h1></div>" +
      '<div class="head-tools">' + (badge || "") + "</div></header>";
  }
  var LIVE = '<span class="live-badge"><span class="dot pulse" style="background:rgb(var(--a4))"></span>Live data</span>';

  function loading(title) {
    view.innerHTML = '<div class="view">' + header(title) + '<div class="card loading" role="status">Loading…</div></div>';
  }
  function failure(title, message) {
    view.innerHTML = '<div class="view">' + header(title) +
      '<div class="notice notice-error" role="alert" style="animation:none">' + icon("info", 18) + "<span>" + esc(message) + "</span></div></div>";
  }
  function api(method, path, body) {
    return window.HiriqAuth.api(method, path, body).then(function (r) {
      if (!r.ok && (r.status === 401 || r.code === "not_signed_in")) { window.HiriqAuth.logout(); }
      return r;
    });
  }

  // A newer navigation cancels slower responses from an older one.
  var navId = 0;
  var helpers = {
    view: view, esc: esc, fmt: fmt, ago: ago, icon: icon, api: api, header: header, loading: loading, failure: failure,
    nav: function () { return ++navId; }, current: function (id) { return id === navId; }
  };
  var jobs = window.HiriqJobs ? window.HiriqJobs(helpers) : null;
  var candidates = window.HiriqCandidates ? window.HiriqCandidates(helpers) : null;
  var matching = window.HiriqMatching ? window.HiriqMatching(helpers) : null;
  var pipeline = window.HiriqPipeline ? window.HiriqPipeline(helpers) : null;
  var ask = window.HiriqAsk ? window.HiriqAsk(helpers) : null;
  var applicants = window.HiriqApplicants ? window.HiriqApplicants(helpers) : null;

  // =====================================================
  // OVERVIEW
  // =====================================================
  var qualityJob = null; // which open job the match-quality card shows

  function renderOverview() {
    var mine = ++navId;
    loading("Overview");
    api("GET", "/api/recruiter/overview").then(function (r) {
      if (mine !== navId) return;
      if (!r.ok) {
        failure("Overview", r.status === 403 ? "This area is for recruiter accounts. Ask an admin to change your role, or sign up as a recruiter." : r.error);
        return;
      }
      drawOverview(r.data);
    });
  }

  function kpiCard(k, i) {
    var colors = ["a1", "a2", "a3", "a4", "a1", "a2"];
    var c = colors[i % colors.length];
    var delta = k.delta
      ? '<div class="kpi-delta"><span class="' + (k.delta.charAt(0) === "+" ? "up" : "down") + '">' + (k.delta.charAt(0) === "+" ? "▲ " : "▼ ") + esc(k.delta.replace(/^[+−]/, "")) + '</span> <span class="faint">vs last week</span></div>'
      : '<div class="kpi-delta"><span class="faint">' + esc(k.sub || "") + "&nbsp;</span></div>";
    return '<div class="card kpi" style="animation-delay:' + i * 0.06 + 's">' +
      '<div class="kpi-top"><span>' + esc(k.label) + '</span><span class="kpi-icon"><span class="bg-' + c + '" style="color:rgb(var(--' + c + '))"></span></span></div>' +
      '<div class="kpi-value">' + fmt(k.value) + "</div>" + delta + "</div>";
  }

  function funnelCard(funnel) {
    var max = Math.max(1, funnel[0].count);
    var any = funnel.some(function (f) { return f.count > 0; });
    if (!any) {
      return '<p class="empty-inline">No candidates in a pipeline yet. Once you add people to a job, you will see how many reach each stage and where they drop off.</p>';
    }
    return funnel.map(function (f, i) {
      var drop = "";
      if (i > 0 && f.drop !== null) {
        drop = '<span class="drop' + (f.drop === 0 ? " flat" : "") + '">' + (f.drop === 0 ? "no drop-off" : "−" + f.drop + "% from " + esc(funnel[i - 1].label)) + "</span>";
      }
      return drop +
        '<div class="rbar-row"><div class="rbar-top"><span>' + esc(f.label) + '</span><span class="mono">' + fmt(f.count) + "</span></div>" +
        '<div class="rbar-track"><div class="rbar-fill' + (f.stage === "hired" ? " good" : "") + '" style="width:' + Math.max(f.count ? 3 : 0, (f.count / max) * 100) + "%;animation-delay:" + i * 0.1 + 's"></div></div></div>';
    }).join("");
  }

  function healthCard(list) {
    if (!list.length) return '<p class="empty-inline">No open jobs yet. Open a job and this list will flag the ones that need attention.</p>';
    return list.map(function (h) {
      return '<div class="hrow"><span class="state-dot state-' + h.state + '"></span>' +
        '<span class="cell-stack"><strong>' + esc(h.title) + "</strong><span>" + esc(h.note) + "</span></span>" +
        '<span class="num">' + fmt(h.matched) + " matched</span></div>";
    }).join("");
  }

  function qualityCard(list) {
    if (!list.length) return '<p class="empty-inline">Match scores appear here once you rank candidates against an open job.</p>';
    var cur = list.filter(function (q) { return q.job_id === qualityJob; })[0] || list[0];
    qualityJob = cur.job_id;
    var pills = list.length > 1
      ? '<div class="job-pills" role="group" aria-label="Choose a job">' + list.map(function (q) {
        return '<button type="button" class="filter-pill" data-qjob="' + esc(q.job_id) + '" aria-pressed="' + (q.job_id === cur.job_id) + '">' + esc(q.title) + "</button>";
      }).join("") + "</div>"
      : "";
    var max = Math.max(1, Math.max.apply(null, cur.bands));
    var bands = cur.bands.map(function (n, i) {
      return '<div class="band' + (i >= 3 ? " strong" : "") + '"><span class="count">' + fmt(n) + '</span><div class="col" style="height:' + Math.max(4, Math.round((n / max) * 96)) + "px;animation-delay:" + i * 0.06 + 's"></div></div>';
    }).join("");
    var labels = cur.band_labels.map(function (l) { return "<span>" + esc(l) + "</span>"; }).join("");
    var top = cur.top.length
      ? '<ul class="top-list">' + cur.top.map(function (t, i) {
        return '<li><span class="rank">' + (i + 1) + '</span><span class="cell-stack"><strong>' + esc(t.name) + "</strong>" + (t.headline ? "<small>" + esc(t.headline) + "</small>" : "") +
          '</span><span class="score-chip' + (t.score >= 70 ? " strong" : "") + '">' + t.score + "</span></li>";
      }).join("") + "</ul>"
      : '<p class="empty-inline">Nobody has been matched to this job yet.</p>';
    return pills +
      '<div class="stack-2"><span class="card-sub">Score distribution · ' + fmt(cur.total) + " candidate" + (cur.total === 1 ? "" : "s") + " scored</span></div>" +
      '<div class="bands" role="img" aria-label="Number of candidates in each score band">' + bands + '</div><div class="band-labels">' + labels + "</div>" +
      '<div class="stack-2" style="margin-top:6px"><span class="card-sub">Top candidates right now</span></div>' + top;
  }

  function skillsCard(skills, pool) {
    if (!skills.length) return '<p class="empty-inline">Skills appear here once your open jobs list the skills they need.</p>';
    return skills.map(function (s, i) {
      var pct = pool ? (s.candidates / pool) * 100 : 0;
      var gap = s.candidates === 0;
      return '<div class="rbar-row"><div class="rbar-top"><span>' + esc(s.skill) + ' <small>asked by ' + s.jobs + " open job" + (s.jobs === 1 ? "" : "s") + "</small></span>" +
        "<span class=\"mono\" style=\"" + (gap ? "color:#ffb3bf" : "") + '">' + (gap ? "no candidates" : fmt(s.candidates) + " in pool") + "</span></div>" +
        '<div class="rbar-track"><div class="rbar-fill' + (gap ? " gap" : " good") + '" style="width:' + (gap ? 100 : Math.max(3, pct)) + "%;animation-delay:" + i * 0.08 + 's' + (gap ? ";opacity:.35" : "") + '"></div></div></div>';
    }).join("");
  }

  function needsCard(n) {
    var parts = [];
    parts.push('<div class="todo"><div class="todo-head"><span>Candidates waiting for review</span><span class="mono">' + fmt(n.waiting_total) + "</span></div>" +
      (n.waiting.length
        ? "<ul>" + n.waiting.map(function (w) { return '<li><a href="#pipeline/' + esc(w.job_id) + '">' + esc(w.name) + "</a> <small>for " + esc(w.job) + "</small></li>"; }).join("") + "</ul>"
        : '<p class="empty-inline">Nothing waiting. You are all caught up.</p>') + "</div>");
    parts.push('<div class="todo"><div class="todo-head"><span>Jobs open over ' + n.stale_days + ' days</span><span class="mono">' + fmt(n.stale_jobs.length) + "</span></div>" +
      (n.stale_jobs.length
        ? "<ul>" + n.stale_jobs.map(function (s) { return "<li>" + esc(s.title) + " <small>open " + s.days + " days</small></li>"; }).join("") + "</ul>"
        : '<p class="empty-inline">No stale jobs.</p>') + "</div>");
    return parts.join("");
  }

  function activityCard(list) {
    if (!list.length) return '<p class="empty-inline">Uploads, job changes and shortlists will show up here.</p>';
    return list.map(function (a, i) {
      return '<div class="activity" style="animation-delay:' + i * 0.06 + 's"><span class="dot bg-' + a.tone + '" style="color:rgb(var(--' + a.tone + '))"></span>' +
        "<span>" + esc(a.text) + "<small>" + esc(ago(a.at)) + "</small></span></div>";
    }).join("");
  }

  function drawOverview(D) {
    var pool = D.skills_pool || 0; // candidates with skills on file: what "skills in demand" is measured against
    var first = String(D.me.name || "").split(" ")[0] || "there";
    var where = [D.me.designation, D.me.company].filter(Boolean).join(" at ");

    var start = D.empty
      ? '<div class="card card-stack"><h2 class="card-title">Welcome to Hiriq. Here is how a hire flows.</h2>' +
        '<ol class="start-steps">' +
        "<li><b>1 · CREATE</b>Create a job<span>Fill in a short form and get a job description written for you.</span></li>" +
        "<li><b>2 · ADD</b>Add resumes<span>Upload resumes and Hiriq reads them into clean candidate profiles.</span></li>" +
        "<li><b>3 · MATCH</b>See the best fit<span>Every score comes with the reasons: matched skills, gaps, evidence.</span></li>" +
        "<li><b>4 · DECIDE</b>You decide<span>Hiriq ranks and explains. Nothing is ever auto-rejected.</span></li></ol></div>"
      : "";

    var quick =
      '<div class="quick">' +
      '<a class="btn btn-grad" href="#jobs/new">' + icon("plus", 16) + 'Create JD</a>' +
      '<a class="btn btn-ghost glass" href="#candidates">' + icon("upload", 16) + 'Upload resume</a>' +
      '<a class="btn btn-ghost glass" href="#matching">' + icon("search", 16) + 'Match candidates</a></div>';

    view.innerHTML =
      '<div class="view">' + header("Overview", LIVE) +
      '<div class="welcome"><p>Welcome back, <strong>' + esc(first) + "</strong>" + (where ? " · " + esc(where) : "") + "</p>" + quick + "</div>" +
      start +
      '<div class="grid-auto" style="--min:170px">' + D.kpis.map(kpiCard).join("") + "</div>" +
      '<div class="row">' +
        '<div class="card card-stack grow-2"><div class="row-between"><div class="stack-2"><h2 class="card-title">Hiring funnel</h2><span class="card-sub">Sourced to hired, across all your jobs</span></div>' +
          '<a class="btn-link" href="#pipeline">Open pipeline</a></div>' + funnelCard(D.funnel) + "</div>" +
        '<div class="card card-stack grow-1"><div class="stack-2"><h2 class="card-title">Needs action</h2><span class="card-sub">What is waiting on you</span></div>' + needsCard(D.needs_action) + "</div>" +
      "</div>" +
      '<div class="row">' +
        '<div class="card card-stack grow-1"><div class="stack-2"><h2 class="card-title">Job health</h2><span class="card-sub">Open jobs, the ones needing attention first</span></div>' + healthCard(D.job_health) + "</div>" +
        '<div class="card card-stack grow-2" id="quality"><div class="stack-2"><h2 class="card-title">Match quality</h2></div><div class="card-stack" id="quality-body">' + qualityCard(D.match_quality) + "</div></div>" +
      "</div>" +
      '<div class="row">' +
        '<div class="card card-stack grow-1"><div class="stack-2"><h2 class="card-title">Skills in demand</h2><span class="card-sub">What your open jobs ask for, against ' + fmt(pool) + " candidate" + (pool === 1 ? "" : "s") + " with skills on file</span></div>" + skillsCard(D.skills_in_demand, pool) + "</div>" +
        '<div class="card card-stack grow-1"><div class="row-between"><h2 class="card-title">Recent activity</h2></div>' + activityCard(D.activity) + "</div>" +
      "</div></div>";

    $("#quality").addEventListener("click", function (e) {
      var b = e.target.closest("[data-qjob]");
      if (!b) return;
      qualityJob = b.getAttribute("data-qjob");
      $("#quality-body").innerHTML = qualityCard(D.match_quality);
    });
  }

  // =====================================================
  // A module that failed to load says so instead of showing a blank page
  // =====================================================
  function renderSoon(title, phase, lead, points) {
    ++navId;
    view.innerHTML = '<div class="view">' + header(title, '<span class="phase-badge">' + esc(phase) + "</span>") +
      '<div class="card card-stack soon-card"><h2 class="card-title">Coming next</h2><p class="muted" style="margin:0">' + esc(lead) + "</p><ul>" +
      points.map(function (p) { return "<li>" + esc(p) + "</li>"; }).join("") + "</ul></div></div>";
  }

  // =====================================================
  // Router
  // =====================================================
  var VIEWS = {
    overview: [renderOverview, "Overview"],
    jobs: [function (rest) { return !jobs ? renderSoon("Jobs & JDs", "Unavailable", "The jobs module did not load. Refresh the page.", []) : rest[0] ? jobs.edit(rest[0]) : jobs.list(); }, "Jobs & JDs"],
    candidates: [function (rest) { return !candidates ? renderSoon("Candidates", "Unavailable", "The candidates module did not load. Refresh the page.", []) : rest[0] ? candidates.detail(rest[0]) : candidates.list(); }, "Candidates"],
    matching: [function (rest) { return !matching ? renderSoon("Matching", "Unavailable", "The matching module did not load. Refresh the page.", []) : matching.show(rest[0] ? decodeURIComponent(rest[0]) : ""); }, "Matching"],
    pipeline: [function (rest) { return !pipeline ? renderSoon("Pipeline", "Unavailable", "The pipeline module did not load. Refresh the page.", []) : pipeline.show(rest[0] ? decodeURIComponent(rest[0]) : ""); }, "Pipeline"],
    applicants: [function (rest) { return !applicants ? renderSoon("Applicants", "Unavailable", "The applicants module did not load. Refresh the page.", []) : applicants.show(rest[0] ? decodeURIComponent(rest[0]) : "", rest[1] ? decodeURIComponent(rest[1]) : ""); }, "Applicants"],
    ask: [function () { return !ask ? renderSoon("Ask the pool", "Unavailable", "The ask module did not load. Refresh the page.", []) : ask.show(); }, "Ask the pool"]
  };
  function route() {
    var parts = (location.hash || "#overview").slice(1).split("/");
    var key = parts[0];
    if (!VIEWS[key]) key = "overview";
    document.querySelectorAll(".side-nav a").forEach(function (a) {
      if (a.getAttribute("href") === "#" + key) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    });
    document.title = VIEWS[key][1] + " · Hiriq recruiter";
    VIEWS[key][0](parts.slice(1));
    window.scrollTo(0, 0);
  }

  document.getElementById("logout").addEventListener("click", function () { window.HiriqAuth.logout(); });
  if (session) {
    document.getElementById("me-name").textContent = session.user;
    document.getElementById("me-avatar").textContent = String(session.user || "R").charAt(0).toUpperCase();
  }

  window.addEventListener("hashchange", route);
  if (cfg.mode !== "api") {
    failure("Overview", 'The recruiter workspace shows live data, so it needs the backend. Start it and set mode to "api" in assets/js/config.js, then log in again.');
  } else {
    route();
  }
})();
