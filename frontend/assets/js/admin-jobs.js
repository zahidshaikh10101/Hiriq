/* Hiriq — admin console: Jobs & sources (reads and writes /api/admin/jobs).
   A factory: admin.js calls window.HiriqAdminJobs(helpers) and gets { show() } back.
   Two kinds of job are listed together:
     - "On Hiriq": posted by a recruiter on the platform. Admin can add one for any recruiter, edit it, open or close it, delete it.
     - "Outside": public posts collected from the outside job feed (Indeed), or added by hand. Admin can add, edit and delete them. */
window.HiriqAdminJobs = function (H) {
  var view = H.view, esc = H.esc, fmt = H.fmt, icon = H.icon, api = H.api;

  var D = null;                 // last response: { jobs, summary, owners, me }
  var source = "all";           // all | portal | outside
  var statusFilter = "all";     // all | open | draft | closed
  var query = "";
  var armed = null;             // "source:id" of the row waiting for a second click
  var armedTimer = null;
  var toast = null;             // { kind, text }
  var editor = null;            // { source, id|null, data|null, error|null, busy }

  var WORK = ["onsite", "hybrid", "remote"];
  var TYPES = ["full-time", "part-time", "contract", "internship"];
  var CURRENCY = ["INR", "USD", "EUR", "GBP"];
  var STATUS_LABEL = { open: "Open", draft: "Draft", closed: "Closed" };
  var STATUS_DOT = { open: "rgb(var(--a4))", draft: "rgb(var(--warn))", closed: "rgb(255 255 255 / .35)" };

  function cap(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : ""; }
  function key(j) { return j.source + ":" + j.id; }
  function safeUrl(u) { return /^https?:\/\//i.test(u || "") ? u : null; }

  // ---------------- loading ----------------
  function show() {
    var mine = H.next();
    H.loading("Jobs & sources");
    api("GET", "/api/admin/jobs?limit=1000").then(function (r) {
      if (!H.current(mine)) return;
      if (!r.ok) { H.failure("Jobs & sources", r.error); return; }
      D = r.data;
      draw();
    });
  }
  function reload(message) {
    api("GET", "/api/admin/jobs?limit=1000").then(function (r) {
      if (r.ok) { D = r.data; }
      if (message) toast = { kind: "good", text: message };
      draw();
    });
  }
  function say(kind, text) { toast = { kind: kind, text: text }; drawToast(); }

  // ---------------- list ----------------
  function filtered() {
    var q = query.toLowerCase();
    return D.jobs.filter(function (j) {
      if (source !== "all" && j.source !== source) return false;
      if (statusFilter !== "all" && j.status !== statusFilter) return false;
      var hay = (j.title + " " + (j.company || "") + " " + (j.location || "") + " " + (j.owner || "")).toLowerCase();
      return !q || hay.indexOf(q) >= 0;
    });
  }

  function summaryCard(label, value, note, i) {
    var colors = ["a1", "a2", "a3", "a4"];
    return '<div class="card kpi" style="animation-delay:' + i * 0.08 + 's"><div class="kpi-top"><span>' + esc(label) + '</span><span class="kpi-icon"><span class="bg-' + colors[i] +
      '" style="color:rgb(var(--' + colors[i] + '))"></span></span></div><div class="kpi-value">' + value + '</div><div class="kpi-delta">' + (note || '<span class="faint">&nbsp;</span>') + "</div></div>";
  }

  function pdfSpec() {
    var rows = filtered(), s = D.summary;
    var scope = (source === "all" ? "All jobs" : source === "portal" ? "Jobs on Hiriq" : "Outside jobs") + (statusFilter !== "all" ? ", " + statusFilter + " only" : "") + (query ? ", matching \"" + query + "\"" : "");
    return {
      title: "Jobs & sources", subtitle: scope + " (" + rows.length + " shown)",
      blocks: [
        { type: "kpis", items: [
          ["Jobs on Hiriq", fmt(s.portal.total), fmt(s.portal.open) + " open, " + fmt(s.portal.draft) + " draft, " + fmt(s.portal.closed) + " closed"],
          ["Outside jobs", fmt(s.outside.total), s.outside.last_fetched ? "Last fetched " + H.dateShort(s.outside.last_fetched) : "None fetched yet"],
          ["Shown in this report", fmt(rows.length)]
        ] },
        { type: "heading", text: "Sources" },
        { type: "table", head: ["Source", "Jobs"], widths: [3, 1], align: ["l", "r"],
          rows: [["Hiriq (recruiters)", fmt(s.portal.total)]].concat(s.outside.sources.map(function (x) { return [x.name, fmt(x.count)]; })) },
        { type: "heading", text: "Jobs" },
        { type: "table", head: ["Job", "Company", "Source", "Location", "Status", "Owner", "Updated"], widths: [3.2, 2.2, 1.6, 2, 1.1, 1.8, 1.6],
          rows: rows.map(function (j) {
            return [j.title, j.company || "-", j.source === "portal" ? "Hiriq" : "Outside / " + j.provider, j.location || "-", STATUS_LABEL[j.status] || "-", j.owner || "-", H.dateShort(j.updated_at)];
          }) }
      ]
    };
  }

  function draw() {
    var s = D.summary;
    var srcNote = s.outside.sources.length ? s.outside.sources.map(function (x) { return esc(x.name) + " " + fmt(x.count); }).join(" · ") : '<span class="faint">No outside jobs yet</span>';
    var pills = [["all", "All"], ["portal", "On Hiriq"], ["outside", "Outside"]].map(function (f) {
      return '<button type="button" class="filter-pill" data-src="' + f[0] + '" aria-pressed="' + (source === f[0]) + '">' + f[1] + "</button>";
    }).join("");
    var statusOpts = [["all", "Any status"], ["open", "Open"], ["draft", "Draft"], ["closed", "Closed"]].map(function (o) {
      return '<option value="' + o[0] + '"' + (statusFilter === o[0] ? " selected" : "") + ">" + o[1] + "</option>";
    }).join("");

    view.innerHTML =
      '<div class="view">' +
      H.header("Jobs & sources",
        '<button type="button" class="btn btn-grad btn-pdf" data-add="portal">' + icon("plus", 16) + "Add job</button>" +
        '<button type="button" class="btn btn-outline btn-pdf" data-add="outside">' + icon("plus", 16) + "Add outside job</button>" + H.pdfBtn()) +
      '<div class="grid-auto">' +
        summaryCard("Jobs on Hiriq", fmt(s.portal.total), '<span class="faint">' + fmt(s.portal.open) + " open · " + fmt(s.portal.draft) + " draft · " + fmt(s.portal.closed) + " closed</span>", 0) +
        summaryCard("Outside jobs", fmt(s.outside.total), '<span class="faint">' + (s.outside.last_fetched ? "Last fetched " + esc(H.ago(s.outside.last_fetched)) : "Nothing fetched yet") + "</span>", 1) +
        summaryCard("Sources", fmt(1 + s.outside.sources.length), '<span class="faint" style="font-size:12px">Hiriq ' + fmt(s.portal.total) + " · " + srcNote + "</span>", 2) +
        summaryCard("Showing", '<span id="shown-count">0</span>', '<span class="faint">after search and filters</span>', 3) +
      "</div>" +
      '<div class="toolbar">' +
        '<div class="search">' + icon("search", 18) + '<label class="sr-only" for="jsearch">Search jobs</label>' +
        '<input class="field field-sm" id="jsearch" type="search" placeholder="Search title, company, location or owner" value="' + esc(query) + '"></div>' +
        '<div class="filters" role="group" aria-label="Filter by source">' + pills + "</div>" +
        '<label class="sr-only" for="jstatus">Status</label><select class="field field-sm" id="jstatus" style="width:150px">' + statusOpts + "</select>" +
      "</div>" +
      '<div id="jtoast"></div>' +
      '<div class="card table-card"><div class="table-scroll"><table style="min-width:980px">' +
        "<thead><tr><th>Job</th><th>Source</th><th>Location</th><th>Status</th><th>Owner</th><th>Updated</th><th class=\"right\">Actions</th></tr></thead>" +
        '<tbody id="job-rows"></tbody></table></div><p class="empty" id="no-jobs" hidden>No jobs match this search.</p></div>' +
      "</div>" + (editor ? editorHtml() : "");

    drawToast();
    drawRows();
    wire();
    H.wirePdf("hiriq-jobs-and-sources.pdf", pdfSpec);
    if (editor) wireEditor();
  }

  function drawToast() {
    var el = view.querySelector("#jtoast");
    if (!el) return;
    el.innerHTML = toast
      ? '<div class="toast' + (toast.kind === "error" ? " toast-error" : "") + '" role="' + (toast.kind === "error" ? "alert" : "status") + '">' +
        icon(toast.kind === "error" ? "info" : "check", 18) + "<span>" + esc(toast.text) + "</span></div>"
      : "";
  }

  function drawRows() {
    var rows = filtered();
    view.querySelector("#shown-count").textContent = fmt(rows.length);
    view.querySelector("#job-rows").innerHTML = rows.map(function (j) {
      var k = key(j);
      var url = safeUrl(j.apply_url);
      var src = j.source === "portal"
        ? '<span class="chip chip-neutral"><span class="dot" style="background:rgb(var(--a1))"></span>On Hiriq</span>'
        : '<span class="chip chip-neutral"><span class="dot" style="background:rgb(var(--a3))"></span>Outside · ' + esc(j.provider) + "</span>";
      var status = j.status
        ? '<span class="chip chip-neutral"><span class="dot" style="background:' + STATUS_DOT[j.status] + '"></span>' + STATUS_LABEL[j.status] + "</span>"
        : '<span class="faint">—</span>';
      var del = armed === k
        ? '<button type="button" class="btn-danger" data-act="confirm-delete" data-k="' + esc(k) + '">Delete for good?</button>'
        : '<button type="button" class="icon-btn" data-act="delete" data-k="' + esc(k) + '" aria-label="Delete ' + esc(j.title) + '" title="Delete">' + icon("trash", 16, "trash") + "</button>";
      return (
        "<tr>" +
        '<td><span class="cell-stack"><strong>' + esc(j.title) + (j.is_demo ? ' <span class="faint">(demo)</span>' : "") + "</strong><small>" + esc(j.company || "—") + "</small>" +
          (url ? '<small><a href="' + esc(url) + '" target="_blank" rel="noopener noreferrer">Apply link</a></small>' : "") + "</span></td>" +
        "<td>" + src + "</td>" +
        "<td>" + esc(j.location || "—") + (j.work_mode ? '<br><small class="faint">' + esc(cap(j.work_mode)) + "</small>" : "") + "</td>" +
        "<td>" + status + "</td>" +
        "<td>" + (j.owner ? esc(j.owner) : '<span class="faint">Outside feed</span>') + "</td>" +
        '<td class="nowrap"><span class="cell-stack"><span>' + esc(H.ago(j.updated_at)) + "</span><small>Added " + esc(H.dateShort(j.created_at)) + "</small></span></td>" +
        '<td><div class="actions"><button type="button" class="icon-btn" data-act="edit" data-k="' + esc(k) + '" aria-label="Edit ' + esc(j.title) + '" title="Edit">' + icon("edit", 16) + "</button>" + del + "</div></td></tr>"
      );
    }).join("");
    view.querySelector("#no-jobs").hidden = rows.length > 0;
  }

  function find(k) { return D.jobs.filter(function (j) { return key(j) === k; })[0]; }

  function wire() {
    view.querySelector("#jsearch").addEventListener("input", function (e) { query = e.target.value; drawRows(); });
    view.querySelector("#jstatus").addEventListener("change", function (e) { statusFilter = e.target.value; drawRows(); });
    view.querySelectorAll("[data-src]").forEach(function (b) {
      b.addEventListener("click", function () {
        source = b.getAttribute("data-src");
        view.querySelectorAll("[data-src]").forEach(function (x) { x.setAttribute("aria-pressed", String(x === b)); });
        drawRows();
      });
    });
    view.querySelectorAll("[data-add]").forEach(function (b) {
      b.addEventListener("click", function () { openEditor(b.getAttribute("data-add"), null); });
    });
    view.querySelector("#job-rows").addEventListener("click", function (e) {
      var btn = e.target.closest("button[data-act]");
      if (!btn) return;
      var k = btn.getAttribute("data-k"), j = find(k), act = btn.getAttribute("data-act");
      if (!j) return;
      if (act === "edit") {
        api("GET", "/api/admin/jobs/" + j.source + "/" + j.id).then(function (r) {
          if (!r.ok) { say("error", r.error); return; }
          openEditor(j.source, r.data);
        });
      } else if (act === "delete") {
        armed = k;
        clearTimeout(armedTimer);
        armedTimer = setTimeout(function () { armed = null; drawRows(); }, 4000);
        drawRows();
      } else if (act === "confirm-delete") {
        clearTimeout(armedTimer);
        armed = null;
        api("DELETE", "/api/admin/jobs/" + j.source + "/" + j.id).then(function (r) {
          if (!r.ok) { say("error", r.error); return; }
          reload(j.title + " was deleted." + (j.source === "portal" ? " Its matches and pipeline entries were removed too." : ""));
        });
      }
    });
  }

  // ---------------- add / edit form ----------------
  function openEditor(src, data) {
    editor = { source: src, id: data ? data.id : null, data: data, error: null, busy: false };
    draw();
  }
  function closeEditor() { editor = null; document.removeEventListener("keydown", onKey); draw(); }
  function onKey(e) { if (e.key === "Escape" && editor && !editor.busy) closeEditor(); }

  function opts(list, value, blank) {
    return (blank ? '<option value="">' + esc(blank) + "</option>" : "") + list.map(function (o) {
      return '<option value="' + esc(o) + '"' + (value === o ? " selected" : "") + ">" + esc(cap(o)) + "</option>";
    }).join("");
  }
  function val(v) { return v == null ? "" : esc(v); }
  function input(id, label, value, extra) {
    return '<label class="field-group"><span class="lbl">' + esc(label) + '</span><input class="field field-sm" id="' + id + '" value="' + val(value) + '" ' + (extra || "") + "></label>";
  }

  function editorHtml() {
    var d = editor.data || {}, adding = !editor.id, portal = editor.source === "portal";
    var title = (adding ? "Add " : "Edit ") + (portal ? "a job on Hiriq" : "an outside job");
    var fields;
    if (portal) {
      var ownerOpts = D.owners.map(function (o) {
        var sel = (d.owner_id ? d.owner_id === o.id : o.id === D.me) ? " selected" : "";
        return '<option value="' + esc(o.id) + '"' + sel + ">" + esc(o.name) + " (" + esc(o.role) + ")</option>";
      }).join("");
      fields =
        '<div class="form-grid">' +
          input("f-title", "Job title *", d.title, 'maxlength="160" required') +
          '<label class="field-group"><span class="lbl">Belongs to</span><select class="field field-sm" id="f-owner">' + ownerOpts + "</select></label>" +
          '<label class="field-group"><span class="lbl">Status</span><select class="field field-sm" id="f-status">' + opts(["draft", "open", "closed"], d.status || "draft") + "</select></label>" +
          input("f-department", "Department", d.department, 'maxlength="120"') +
          input("f-location", "Location", d.location, 'maxlength="120"') +
          '<label class="field-group"><span class="lbl">Work mode</span><select class="field field-sm" id="f-work_mode">' + opts(WORK, d.work_mode, "Not set") + "</select></label>" +
          '<label class="field-group"><span class="lbl">Employment type</span><select class="field field-sm" id="f-employment_type">' + opts(TYPES, d.employment_type, "Not set") + "</select></label>" +
          input("f-experience_min", "Experience min (years)", d.experience_min, 'type="number" min="0" max="50"') +
          input("f-experience_max", "Experience max (years)", d.experience_max, 'type="number" min="0" max="50"') +
          input("f-qualification", "Qualification", d.qualification, 'maxlength="200"') +
          input("f-salary_min", "Salary min (per year)", d.salary_min, 'type="number" min="0"') +
          input("f-salary_max", "Salary max (per year)", d.salary_max, 'type="number" min="0"') +
          '<label class="field-group"><span class="lbl">Currency</span><select class="field field-sm" id="f-salary_currency">' + CURRENCY.map(function (c) {
            return '<option' + ((d.salary_currency || "INR") === c ? " selected" : "") + ">" + c + "</option>";
          }).join("") + "</select></label>" +
        "</div>" +
        '<div class="form-grid" style="grid-template-columns:1fr">' +
          input("f-skills_required", "Required skills (comma separated)", (d.skills_required || []).join(", ")) +
          input("f-skills_nice", "Nice-to-have skills (comma separated)", (d.skills_nice || []).join(", ")) +
          '<label class="field-group"><span class="lbl">Responsibilities</span><textarea class="field" id="f-responsibilities" maxlength="3000" rows="3">' + val(d.responsibilities) + "</textarea></label>" +
          '<label class="field-group"><span class="lbl">Job description</span><textarea class="field" id="f-description" maxlength="20000" rows="7">' + val(d.description) + "</textarea></label>" +
        "</div>" +
        '<p class="hint" style="margin:0">To set a job to Open it needs a description and at least one required skill, the same rule recruiters follow.</p>';
    } else {
      fields =
        '<div class="form-grid">' +
          input("f-title", "Job title *", d.title, 'maxlength="160" required') +
          input("f-company", "Company", d.company, 'maxlength="160"') +
          input("f-location", "Location", d.location, 'maxlength="160"') +
          input("f-apply_url", "Apply link (https://…)", d.apply_url, 'maxlength="600" type="url"') +
        "</div>" +
        '<label class="check-row" style="display:flex;gap:10px;align-items:center"><input type="checkbox" id="f-remote"' + (d.remote ? " checked" : "") + "> <span>Remote job</span></label>" +
        '<label class="field-group"><span class="lbl">Job description</span><textarea class="field" id="f-description" maxlength="6000" rows="8">' + val(d.description) + "</textarea></label>" +
        (editor.id && d.provider !== "Added by hand" ? '<p class="hint" style="margin:0">This post came from the outside feed. If the feed fetches it again it will refresh your edits.</p>' : "");
    }
    return (
      '<div class="modal-back" id="modal-back"><div class="modal card" role="dialog" aria-modal="true" aria-labelledby="modal-title">' +
      '<div class="row-between"><h2 class="card-title" id="modal-title">' + esc(title) + '</h2><button type="button" class="icon-btn" id="modal-x" aria-label="Close">' + icon("close", 16) + "</button></div>" +
      '<div id="modal-error">' + (editor.error ? '<div class="notice notice-error" role="alert" style="animation:none">' + icon("info", 18) + "<span>" + esc(editor.error) + "</span></div>" : "") + "</div>" +
      '<form id="job-form" novalidate class="card-stack" style="gap:14px">' + fields +
      '<div class="modal-actions"><button type="button" class="btn btn-outline btn-pdf" id="modal-cancel">Cancel</button>' +
      '<button type="submit" class="btn btn-grad btn-pdf" id="modal-save">' + (adding ? "Add job" : "Save changes") + "</button></div></form></div></div>"
    );
  }

  function wireEditor() {
    document.addEventListener("keydown", onKey);
    var back = view.querySelector("#modal-back");
    back.addEventListener("mousedown", function (e) { if (e.target === back && !editor.busy) closeEditor(); });
    view.querySelector("#modal-x").addEventListener("click", closeEditor);
    view.querySelector("#modal-cancel").addEventListener("click", closeEditor);
    view.querySelector("#job-form").addEventListener("submit", function (e) { e.preventDefault(); save(); });
    var first = view.querySelector("#f-title");
    if (first) first.focus();
  }

  function g(id) { var el = view.querySelector("#f-" + id); return el ? el.value.trim() : ""; }
  function num(id) { var v = g(id); return v === "" ? null : Number(v); }
  function list(id) { return g(id).split(",").map(function (s) { return s.trim(); }).filter(Boolean); }

  function save() {
    var portal = editor.source === "portal", body;
    if (g("title").length < 3) { editorError("Give the job a title (at least 3 characters)."); return; }
    if (portal) {
      body = {
        title: g("title"), owner_id: g("owner") || null, status: g("status"), department: g("department") || null, location: g("location") || null,
        work_mode: g("work_mode") || null, employment_type: g("employment_type") || null, experience_min: num("experience_min"), experience_max: num("experience_max"),
        qualification: g("qualification") || null, salary_min: num("salary_min"), salary_max: num("salary_max"), salary_currency: g("salary_currency") || "INR",
        skills_required: list("skills_required"), skills_nice: list("skills_nice"), responsibilities: g("responsibilities") || null, description: g("description") || null
      };
    } else {
      body = { title: g("title"), company: g("company") || null, location: g("location") || null, apply_url: g("apply_url") || null, remote: view.querySelector("#f-remote").checked, description: g("description") };
    }
    editor.busy = true;
    var btn = view.querySelector("#modal-save");
    btn.disabled = true;
    var adding = !editor.id;
    var path = "/api/admin/jobs/" + editor.source + (adding ? "" : "/" + editor.id);
    api(adding ? "POST" : "PUT", path, body).then(function (r) {
      editor.busy = false;
      if (!r.ok) { btn.disabled = false; editorError(r.error); return; }
      var name = r.data.title;
      editor = null;
      document.removeEventListener("keydown", onKey);
      reload(name + (adding ? " was added." : " was updated."));
    });
  }
  function editorError(text) {
    editor.error = text;
    view.querySelector("#modal-error").innerHTML = '<div class="notice notice-error" role="alert" style="animation:none">' + icon("info", 18) + "<span>" + esc(text) + "</span></div>";
    view.querySelector(".modal").scrollTop = 0;
  }

  return { show: show };
};
