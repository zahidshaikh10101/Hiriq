/* Hiriq — recruiter: Candidates (resume upload + candidate pool).
   A factory: recruiter.js calls window.HiriqCandidates(helpers) and gets the two views back.
   List (#candidates): upload zone, live upload queue, the searchable pool. Detail (#candidates/<id>): profile, edit, remove.
   Nothing on this page is estimated: a number the resume does not support is shown as "not found", never guessed. */
window.HiriqCandidates = function (R) {
  var view = R.view, esc = R.esc, icon = R.icon, api = R.api;

  var MAX_FILES = 10;                 // per drop; the pool itself holds far more
  var MAX_BYTES = 5 * 1024 * 1024;    // same limit as the server
  var OK_EXT = /\.(pdf|docx|txt)$/i;

  // ---------- small helpers ----------
  function safeUrl(u) { return /^https?:\/\//i.test(String(u || "")) ? String(u) : ""; }
  function years(n) { return n == null ? "—" : (n === 1 ? "1 yr" : +n.toFixed(1) + " yrs"); }
  function size(n) { return n < 1024 * 1024 ? Math.max(1, Math.round(n / 1024)) + " KB" : (n / 1048576).toFixed(1) + " MB"; }
  function sourceChip(s) { return '<span class="chip ' + (s === "platform" ? "chip-violet" : "chip-neutral") + '">' + (s === "platform" ? "Hiriq member" : "Uploaded") + "</span>"; }
  function chips(list, max) {
    list = list || [];
    var shown = list.slice(0, max).map(function (s) { return '<span class="chip chip-neutral">' + esc(s) + "</span>"; }).join(" ");
    var more = list.length > max ? ' <span class="faint">+' + (list.length - max) + "</span>" : "";
    return shown ? shown + more : '<span class="faint">none found</span>';
  }

  /** A readable message from a failed call (field names for validation problems). */
  function explain(r) {
    var d = r.data && r.data.detail;
    if (Array.isArray(d) && d.length) {
      return d.slice(0, 3).map(function (e) { return String(e.msg || "").replace(/^Value error, /, ""); }).join(" ");
    }
    return r.error || "Something went wrong. Try again.";
  }

  /** Sends one file as the raw request body. Resolves { ok, status, data, error, code } and never rejects. */
  function sendFile(file) {
    var cfg = window.HIRIQ_CONFIG, s = window.HiriqAuth.current();
    if (!s) return Promise.resolve({ ok: false, status: 401, data: {}, error: "Your session has ended. Sign in again." });
    return fetch(cfg.apiBase + "/api/recruiter/candidates", {
      method: "POST",
      headers: { Authorization: "Bearer " + s.token, "X-Filename": encodeURIComponent(file.name), "Content-Type": "application/octet-stream" },
      body: file
    }).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (data) {
        var out = { ok: res.ok, status: res.status, data: data };
        if (!res.ok) {
          var d = data && data.detail;
          if (d && typeof d === "object" && !Array.isArray(d)) { out.error = d.message; out.code = d.code; }
          else if (typeof d === "string") out.error = d;
          if (res.status === 413) out.error = out.error || "This file is larger than 5 MB.";
          out.error = out.error || "Something went wrong. Try again.";
        }
        return out;
      });
    }).catch(function () {
      return { ok: false, status: 0, data: {}, error: "Could not reach the backend. Is it running?" };
    });
  }

  // =====================================================
  // UPLOAD QUEUE (module-level: it keeps working if you click away and come back)
  // =====================================================
  var queue = [];          // { id, file, state: waiting|reading|added|already|failed, startedAt, took, result, error, retry }
  var nextId = 1, pumping = false, ticker = null;
  var onPoolChange = null; // set while the list view is on screen

  function checkFile(f) {
    if (/\.doc$/i.test(f.name)) return "Old .doc files are not supported. Save it as .docx or PDF first.";
    if (!OK_EXT.test(f.name)) return "Only PDF, Word (.docx) and text files are supported.";
    if (!f.size) return "This file is empty.";
    if (f.size > MAX_BYTES) return "This file is larger than 5 MB.";
    return "";
  }

  function addFiles(files) {
    var list = Array.prototype.slice.call(files || []);
    var skipped = 0;
    if (list.length > MAX_FILES) { skipped = list.length - MAX_FILES; list = list.slice(0, MAX_FILES); }
    list.forEach(function (f) {
      var problem = checkFile(f);
      queue.push({ id: nextId++, file: f, state: problem ? "failed" : "waiting", error: problem, retry: false });
    });
    paintQueue(); pump();
    return skipped;
  }

  function pump() {
    if (pumping) return;
    var item = queue.filter(function (q) { return q.state === "waiting"; })[0];
    if (!item) return;
    pumping = true;
    item.state = "reading"; item.startedAt = Date.now();
    paintQueue(); startTicker();
    sendFile(item.file).then(function (r) {
      item.took = Math.round((Date.now() - item.startedAt) / 1000);
      if (r.status === 401) { window.HiriqAuth.logout(); return; }
      if (r.ok) { item.state = r.data.already_added ? "already" : "added"; item.result = r.data; }
      else { item.state = "failed"; item.error = explain(r); item.retry = [0, 429, 502, 503].indexOf(r.status) !== -1; }
      pumping = false;
      paintQueue();
      if (r.ok && onPoolChange) onPoolChange();
      pump();
    });
  }

  function startTicker() {
    if (ticker) return;
    ticker = setInterval(function () {
      var live = queue.some(function (q) { return q.state === "reading"; });
      var box = view.querySelector("#cand-queue");
      if (!live || !box) { clearInterval(ticker); ticker = null; return; }
      queue.forEach(function (q) {
        if (q.state !== "reading") return;
        var el = box.querySelector('[data-q="' + q.id + '"] .q-time');
        if (el) el.textContent = Math.round((Date.now() - q.startedAt) / 1000) + " s";
      });
    }, 1000);
  }

  var STATE_TEXT = { waiting: "Waiting", reading: "Reading", added: "Added", already: "Already in your pool", failed: "Could not add" };

  function queueRow(q) {
    var detail = "";
    if (q.state === "reading") detail = '<span class="q-time mono">' + Math.round((Date.now() - q.startedAt) / 1000) + " s</span>";
    else if (q.state === "added" || q.state === "already") {
      var r = q.result, bits = [];
      if (r.skills && r.skills.length) bits.push(r.skills.length + (r.skills.length === 1 ? " skill" : " skills"));
      bits.push(r.total_experience_years == null ? "experience not found" : years(r.total_experience_years));
      detail = '<a class="q-who" href="#candidates/' + esc(r.id) + '">' + esc(r.full_name) + "</a> <span class=\"faint\">" + esc(bits.join(" · ")) + "</span>";
      if (r.same_email_as) detail += '<div class="q-note">Same email as <a href="#candidates/' + esc(r.same_email_as.id) + '">' + esc(r.same_email_as.name) + "</a>. Both are kept, so you can compare and remove one.</div>";
    } else if (q.state === "failed") detail = '<span class="q-err">' + esc(q.error) + "</span>";
    var actions = "";
    if (q.state === "failed" && q.retry) actions += '<button type="button" class="btn-link" data-qact="retry">Try again</button>';
    if (q.state !== "reading" && q.state !== "waiting") actions += '<button type="button" class="btn-link" data-qact="dismiss" aria-label="Dismiss ' + esc(q.file.name) + '">Dismiss</button>';
    else if (q.state === "waiting") actions += '<button type="button" class="btn-link" data-qact="dismiss" aria-label="Cancel ' + esc(q.file.name) + '">Cancel</button>';
    return '<li class="q-item q-' + q.state + '" data-q="' + q.id + '">' +
      '<span class="q-icon" aria-hidden="true">' + (q.state === "reading" ? '<span class="spin"></span>' : q.state === "added" || q.state === "already" ? icon("check", 16) : q.state === "failed" ? icon("warn", 16) : '<span class="q-dot"></span>') + "</span>" +
      '<span class="q-main"><span class="q-name"><strong>' + esc(q.file.name) + '</strong> <small class="faint">' + esc(size(q.file.size)) + "</small></span>" +
      '<span class="q-detail"><span class="q-state">' + STATE_TEXT[q.state] + "</span> " + detail + "</span></span>" +
      '<span class="q-actions">' + actions + "</span></li>";
  }

  function paintQueue() {
    var box = view.querySelector("#cand-queue");
    if (!box) return;
    if (!queue.length) { box.innerHTML = ""; return; }
    var done = queue.filter(function (q) { return q.state === "added" || q.state === "already" || q.state === "failed"; }).length;
    var reading = queue.some(function (q) { return q.state === "reading" || q.state === "waiting"; });
    box.innerHTML = '<div class="card card-stack"><div class="row-between"><div class="stack-2"><h2 class="card-title">' + (reading ? "Reading resumes" : "Upload finished") + "</h2>" +
      '<span class="card-sub" aria-live="polite">' + done + " of " + queue.length + " done" + (reading ? ". Each resume takes about 10 to 40 seconds on the free models." : ".") + "</span></div>" +
      (done ? '<button type="button" class="btn-link" data-qact="clear">Clear finished</button>' : "") + "</div>" +
      '<ul class="queue">' + queue.map(queueRow).join("") + "</ul></div>";
  }

  // =====================================================
  // LIST
  // =====================================================
  var source = "all", search = "", PAGE = 50;

  function renderList() {
    var mine = R.nav();
    R.loading("Candidates");
    fetchPool(0).then(function (r) {
      if (!R.current(mine)) return;
      if (!r.ok) { R.failure("Candidates", r.status === 403 ? "This area is for recruiter accounts." : r.error); return; }
      drawList(r.data, mine);
    });
  }

  function fetchPool(offset) {
    var q = "?source=" + encodeURIComponent(source) + "&limit=" + PAGE + "&offset=" + offset + (search ? "&q=" + encodeURIComponent(search) : "");
    return api("GET", "/api/recruiter/candidates" + q);
  }

  function drawList(D, mine) {
    var shownRows = D.candidates.slice();
    var counts = D.counts;

    var zone =
      '<div class="card card-stack"><div class="stack-2"><h2 class="card-title">Add resumes</h2>' +
      '<span class="card-sub">PDF, Word (.docx) or text, up to 5 MB each. Hiriq reads the file and keeps the text, not the file itself.</span></div>' +
      '<div class="dropzone" id="dropzone"><span class="dz-icon" aria-hidden="true">' + icon("upload", 26) + "</span>" +
      '<div class="dz-text"><strong>Drop resumes here</strong><span class="faint">up to ' + MAX_FILES + ' at a time</span></div>' +
      '<button type="button" class="btn btn-grad" id="btn-pick">' + icon("plus", 16) + 'Choose files</button>' +
      '<input type="file" id="file-input" multiple accept=".pdf,.docx,.txt,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain" hidden></div>' +
      '<div id="zone-msg" aria-live="polite"></div></div>';

    var pills = [["all", "All"], ["upload", "Uploaded"], ["platform", "Hiriq members"]].map(function (p) {
      return '<button type="button" class="filter-pill" data-src="' + p[0] + '" aria-pressed="' + (source === p[0]) + '">' + p[1] + ' · <span data-count="' + p[0] + '">' + counts[p[0]] + "</span></button>";
    }).join("");

    view.innerHTML = '<div class="view">' + R.header("Candidates", '<span class="phase-badge">' + counts.all + (counts.all === 1 ? " person" : " people") + " in your pool</span>") +
      zone + '<div id="cand-queue"></div>' +
      '<div class="card table-card"><div class="cand-toolbar"><div class="filters" role="group" aria-label="Filter candidates">' + pills + "</div>" +
      '<input class="field field-sm cand-search" id="cand-search" type="search" placeholder="Search name, skill, title, place" aria-label="Search candidates" value="' + esc(search) + '" maxlength="100"></div>' +
      '<div id="cand-body"></div></div></div>';

    var $ = function (s) { return view.querySelector(s); };

    function rowsHtml(rows) {
      return rows.map(function (c) {
        var meta = [c.current_title, c.current_company].filter(Boolean).join(" at ");
        return '<tr><td><a class="job-link" href="#candidates/' + esc(c.id) + '"><span class="cell-stack"><strong>' + esc(c.full_name) + "</strong>" + (meta || c.location ? "<small>" + esc([meta, c.location].filter(Boolean).join(" · ")) + "</small>" : "") + "</span></a></td>" +
          "<td>" + sourceChip(c.source) + (c.is_demo ? ' <span class="faint" style="font-size:12px">sample</span>' : "") + "</td>" +
          '<td class="mono nowrap">' + esc(years(c.total_experience_years)) + '</td><td><div class="chips-row">' + chips(c.skills, 4) + "</div></td>" +
          '<td class="nowrap faint">' + esc(R.ago(c.created_at)) + "</td></tr>";
      }).join("");
    }

    function body(total) {
      var host = $("#cand-body");
      if (!counts.all) {
        host.innerHTML = '<p class="empty-inline pad">Nobody in your pool yet. Drop a few resumes above and they will appear here with their skills and experience. People who join Hiriq as candidates appear here too.</p>';
        return;
      }
      if (!shownRows.length) {
        host.innerHTML = '<p class="empty-inline pad">' + (search ? "No one matches “" + esc(search) + "”." : "No candidates in this view.") + "</p>";
        return;
      }
      host.innerHTML = '<div class="table-scroll"><table><thead><tr><th>Candidate</th><th>Source</th><th>Experience</th><th>Skills</th><th>Added</th></tr></thead><tbody>' + rowsHtml(shownRows) + "</tbody></table></div>" +
        (shownRows.length < total ? '<div class="pad"><button type="button" class="btn btn-outline" id="btn-more">Show more (' + (total - shownRows.length) + " left)</button></div>" : "");
    }
    var total = D.total;
    body(total);

    // upload zone
    var zoneEl = $("#dropzone"), input = $("#file-input");
    function take(files) {
      var skipped = addFiles(files);
      $("#zone-msg").innerHTML = skipped ? '<div class="notice notice-warn" style="animation:none">' + icon("warn", 18) + "<span>Only the first " + MAX_FILES + " files were taken. Drop the other " + skipped + " again once these finish.</span></div>" : "";
      input.value = "";
    }
    $("#btn-pick").addEventListener("click", function () { input.click(); });
    input.addEventListener("change", function () { if (input.files.length) take(input.files); });
    ["dragenter", "dragover"].forEach(function (ev) { zoneEl.addEventListener(ev, function (e) { e.preventDefault(); zoneEl.classList.add("over"); }); });
    ["dragleave", "drop"].forEach(function (ev) { zoneEl.addEventListener(ev, function (e) { e.preventDefault(); zoneEl.classList.remove("over"); }); });
    zoneEl.addEventListener("drop", function (e) { if (e.dataTransfer && e.dataTransfer.files.length) take(e.dataTransfer.files); });

    // queue actions
    $("#cand-queue").addEventListener("click", function (e) {
      var b = e.target.closest("[data-qact]");
      if (!b) return;
      var act = b.getAttribute("data-qact"), li = b.closest("[data-q]");
      var item = li ? queue.filter(function (q) { return String(q.id) === li.getAttribute("data-q"); })[0] : null;
      if (act === "clear") queue = queue.filter(function (q) { return q.state === "reading" || q.state === "waiting"; });
      else if (act === "dismiss" && item) queue = queue.filter(function (q) { return q !== item; });
      else if (act === "retry" && item) { item.state = "waiting"; item.error = ""; }
      paintQueue(); pump();
    });
    paintQueue();
    if (queue.some(function (q) { return q.state === "reading"; })) startTicker();

    // pool: filter pills, search, paging
    var holder = $(".filters");
    holder.addEventListener("click", function (e) {
      var b = e.target.closest("[data-src]");
      if (!b || b.getAttribute("data-src") === source) return;
      source = b.getAttribute("data-src");
      holder.querySelectorAll("[data-src]").forEach(function (x) { x.setAttribute("aria-pressed", String(x === b)); });
      reload();
    });
    var timer = null;
    $("#cand-search").addEventListener("input", function (e) {
      clearTimeout(timer);
      var value = e.target.value.trim();
      timer = setTimeout(function () { if (value !== search) { search = value; reload(); } }, 250);
    });
    $("#cand-body").addEventListener("click", function (e) {
      var btn = e.target.closest("#btn-more");
      if (!btn) return;
      btn.disabled = true;
      fetchPool(shownRows.length).then(function (r) {
        if (!R.current(mine)) return;
        if (!r.ok) { btn.disabled = false; return; }
        shownRows = shownRows.concat(r.data.candidates); total = r.data.total; body(total);
      });
    });

    var seq = 0;
    function reload() {
      var mySeq = ++seq;
      fetchPool(0).then(function (r) {
        if (!R.current(mine) || mySeq !== seq || !r.ok) return;
        shownRows = r.data.candidates; total = r.data.total; counts = r.data.counts;
        ["all", "upload", "platform"].forEach(function (k) { var el = view.querySelector('[data-count="' + k + '"]'); if (el) el.textContent = counts[k]; });
        body(total);
      });
    }
    onPoolChange = function () { if (R.current(mine) && view.querySelector("#cand-body")) reload(); };
  }

  // =====================================================
  // DETAIL
  // =====================================================
  function renderDetail(id) {
    var mine = R.nav();
    onPoolChange = null;
    R.loading("Candidate");
    api("GET", "/api/recruiter/candidates/" + encodeURIComponent(id)).then(function (r) {
      if (!R.current(mine)) return;
      if (!r.ok) { R.failure("Candidate", r.status === 404 ? "That candidate does not exist, or it belongs to another account." : r.error); return; }
      drawDetail(r.data, null);
    });
  }

  function basisText(c) {
    if (c.total_experience_years == null) return "No usable job dates were found in the resume, so experience is left blank rather than guessed.";
    if (c.experience_basis === "edited") return "Entered by you.";
    return "Worked out from the job dates in the resume. Overlapping jobs are counted once.";
  }

  function kv(label, value) { return '<div class="kv"><span class="kv-k">' + esc(label) + '</span><span class="kv-v">' + (value || '<span class="faint">not found</span>') + "</span></div>"; }

  function drawDetail(c, notice) {
    var member = c.source === "platform";
    var $ = function (s) { return view.querySelector(s); };

    var li = safeUrl(c.linkedin_url), gh = safeUrl(c.github_url), site = safeUrl(c.portfolio_url);
    var contact = member
      ? '<p class="muted" style="margin:0">Contact details of Hiriq members stay private. Their profile is filled from their own account.</p>'
      : kv("Email", c.email ? '<a href="mailto:' + esc(c.email) + '">' + esc(c.email) + "</a>" : "") + kv("Phone", c.phone ? esc(c.phone) : "") +
        kv("LinkedIn", li ? '<a href="' + esc(li) + '" target="_blank" rel="noopener noreferrer">' + esc(li.replace(/^https?:\/\/(www\.)?/i, "")) + "</a>" : "") +
        kv("GitHub", gh ? '<a href="' + esc(gh) + '" target="_blank" rel="noopener noreferrer">' + esc(gh.replace(/^https?:\/\/(www\.)?/i, "")) + "</a>" : "") +
        kv("Website", site ? '<a href="' + esc(site) + '" target="_blank" rel="noopener noreferrer">' + esc(site.replace(/^https?:\/\/(www\.)?/i, "").replace(/\/$/, "")) + "</a>" : "");

    var profile = '<div class="card card-stack grow-1" id="profile-card"><div class="row-between"><h2 class="card-title">Profile</h2>' +
      (member ? "" : '<button type="button" class="btn-link" id="btn-edit">Edit</button>') + "</div>" +
      kv("Current role", [c.current_title, c.current_company].filter(Boolean).map(esc).join(" at ")) + kv("Location", esc(c.location || "")) +
      kv("Experience", c.total_experience_years == null ? "" : esc(years(c.total_experience_years))) +
      '<span class="hint">' + esc(basisText(c)) + "</span>" + kv("Qualification", esc(c.qualification || "")) +
      '<h3 class="sub-title">Contact</h3>' + contact +
      '<h3 class="sub-title">Skills</h3><div class="chips-row">' + (c.skills && c.skills.length ? c.skills.map(function (s) { return '<span class="chip chip-cyan">' + esc(s) + "</span>"; }).join(" ") : '<span class="faint">' + (member ? "This member has not added skills yet." : "No skills were found in this resume.") + "</span>") + "</div>" +
      '<span class="hint">Only skills the resume actually mentions are listed.</span></div>';

    var emp = (c.employers || []).map(function (e) {
      var span = [e.start, e.end].filter(Boolean).join(" to ");
      return '<li><strong>' + esc(e.title || "Role not stated") + "</strong> <span class=\"faint\">at</span> " + esc(e.company) + (span ? '<small class="mono">' + esc(span) + "</small>" : "") + (e.summary ? "<p>" + esc(e.summary) + "</p>" : "") + "</li>";
    }).join("");
    var edu = (c.education || []).map(function (e) {
      return "<li><strong>" + esc(e.degree || "Programme not stated") + "</strong>" + (e.institution ? " <span class=\"faint\">at</span> " + esc(e.institution) : "") + (e.year ? '<small class="mono">' + esc(e.year) + "</small>" : "") + "</li>";
    }).join("");
    var certs = (c.certifications || []).map(function (x) { return '<span class="chip chip-neutral">' + esc(x) + "</span>"; }).join(" ");

    var history = '<div class="card card-stack grow-2"><h2 class="card-title">Work and education</h2>' +
      '<h3 class="sub-title">Experience</h3>' + (emp ? '<ul class="timeline">' + emp + "</ul>" : '<p class="empty-inline">' + (member ? "Not shared yet." : "No jobs were found in this resume.") + "</p>") +
      '<h3 class="sub-title">Education</h3>' + (edu ? '<ul class="timeline">' + edu + "</ul>" : '<p class="empty-inline">' + (member ? "Not shared yet." : "No education was found in this resume.") + "</p>") +
      (certs ? '<h3 class="sub-title">Certifications</h3><div class="chips-row">' + certs + "</div>" : "") + "</div>";

    var foot = member ? "" :
      '<div class="card card-stack"><div class="row-between"><div class="stack-2"><h2 class="card-title">This resume</h2><span class="card-sub">' +
      (c.file_name ? "From the file " + esc(c.file_name) + ". " : "") + (c.parsed_by ? "Read by " + esc(String(c.parsed_by).replace(/:free$/, "")) + ". " : "") +
      "Check the details above against the original. The reader can make mistakes.</span></div>" +
      '<button type="button" class="btn-danger" id="btn-delete">Remove from pool</button></div></div>';

    view.innerHTML = '<div class="view">' + R.header(c.full_name, sourceChip(c.source) + '<a class="btn btn-ghost glass" href="#candidates" style="min-height:40px">← All candidates</a>') +
      '<div id="cand-msg" aria-live="polite"></div><div class="row editor">' + profile + history + "</div>" + foot + "</div>";

    function say(kind, message) {
      $("#cand-msg").innerHTML = message ? '<div class="notice notice-' + kind + '" role="' + (kind === "error" ? "alert" : "status") + '" style="animation:none">' + icon(kind === "good" ? "check" : "info", 18) + "<span>" + esc(message) + "</span></div>" : "";
    }
    if (notice) say(notice[0], notice[1]);

    var del = $("#btn-delete");
    if (del) del.addEventListener("click", function () {
      if (!del.getAttribute("data-sure")) {
        del.setAttribute("data-sure", "1"); del.textContent = "Really remove?";
        setTimeout(function () { if (del.isConnected) { del.removeAttribute("data-sure"); del.textContent = "Remove from pool"; } }, 4000);
        return;
      }
      del.disabled = true;
      api("DELETE", "/api/recruiter/candidates/" + c.id).then(function (r) {
        if (!r.ok) { del.disabled = false; say("error", explain(r)); return; }
        window.location.hash = "#candidates";
      });
    });

    var editBtn = $("#btn-edit");
    if (editBtn) editBtn.addEventListener("click", function () { drawEdit(c); });
  }

  function drawEdit(c) {
    var $ = function (s) { return view.querySelector(s); };
    function field(id, label, value, attrs) {
      return '<div class="field-group"><label class="label" for="e-' + id + '">' + label + '</label><input class="field field-sm" id="e-' + id + '" value="' + esc(value == null ? "" : value) + '" ' + (attrs || "") + "></div>";
    }
    $("#profile-card").innerHTML =
      '<div class="row-between"><h2 class="card-title">Edit profile</h2></div><form id="edit-form" class="card-stack" novalidate>' +
      field("name", "Full name *", c.full_name, 'maxlength="160" required') + field("title", "Current title", c.current_title, 'maxlength="160"') +
      field("company", "Current company", c.current_company, 'maxlength="160"') + field("loc", "Location", c.location, 'maxlength="160"') +
      field("years", "Experience (years)", c.total_experience_years, 'type="number" min="0" max="60" step="0.1" inputmode="decimal"') +
      field("qual", "Qualification", c.qualification, 'maxlength="200"') + field("email", "Email", c.email, 'type="email" maxlength="320"') +
      field("phone", "Phone", c.phone, 'maxlength="30"') + field("li", "LinkedIn link", c.linkedin_url, 'maxlength="300" placeholder="https://www.linkedin.com/in/…"') +
      field("gh", "GitHub link", c.github_url, 'maxlength="300" placeholder="https://github.com/…"') +
      field("site", "Website or portfolio", c.portfolio_url, 'maxlength="300" placeholder="https://yourname.dev"') +
      '<div class="field-group"><label class="label" for="e-skills">Skills (separate with commas)</label><textarea class="field" id="e-skills" rows="3">' + esc((c.skills || []).join(", ")) + "</textarea></div>" +
      '<div id="edit-msg" aria-live="polite"></div><div class="actions-bar"><button type="submit" class="btn btn-grad" id="btn-save">Save changes</button><button type="button" class="btn btn-outline" id="btn-cancel">Cancel</button></div></form>';
    $("#e-name").focus();

    $("#btn-cancel").addEventListener("click", function () { drawDetail(c, null); });
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
      api("PUT", "/api/recruiter/candidates/" + c.id, body).then(function (r) {
        btn.disabled = false;
        if (!r.ok) { $("#edit-msg").innerHTML = '<div class="notice notice-error" role="alert" style="animation:none">' + icon("info", 18) + "<span>" + esc(explain(r)) + "</span></div>"; return; }
        drawDetail(r.data, ["good", "Saved."]);
      });
    });
  }

  return { list: renderList, detail: renderDetail };
};
