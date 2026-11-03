/* Hiriq — recruiter: Jobs & JDs.
   A factory: recruiter.js calls window.HiriqJobs(helpers) and gets the two views back.
   List (#jobs), editor (#jobs/new and #jobs/<id>): fill the form, let AI write the JD, edit it, publish, close, clone. */
window.HiriqJobs = function (R) {
  var view = R.view, esc = R.esc, icon = R.icon, api = R.api;

  var STATUS = { open: "Open", draft: "Draft", closed: "Closed" };
  var LABELS = {
    title: "Job title", department: "Department", location: "Location", work_mode: "Work mode", employment_type: "Employment type",
    experience_min: "Minimum experience", experience_max: "Maximum experience", qualification: "Qualification",
    salary_min: "Minimum salary", salary_max: "Maximum salary", salary_currency: "Currency", skills_required: "Required skills",
    skills_nice: "Nice-to-have skills", responsibilities: "Day-to-day work", description: "Job description"
  };
  var SYMBOL = { INR: "₹", USD: "$", EUR: "€", GBP: "£" };

  function chip(status) { return '<span class="job-status job-' + esc(status) + '">' + esc(STATUS[status] || status) + "</span>"; }
  function expText(min, max) {
    if (min == null && max == null) return "";
    if (min != null && max != null) return min === max ? min + " yrs" : min + "–" + max + " yrs";
    return min != null ? min + "+ yrs" : "up to " + max + " yrs";
  }
  function money(n, cur) {
    if (cur === "INR") {
      if (n >= 10000000) return "₹" + +(n / 10000000).toFixed(2) + " crore";
      if (n >= 100000) return "₹" + +(n / 100000).toFixed(2) + " lakh";
      return "₹" + n.toLocaleString("en-IN");
    }
    return (SYMBOL[cur] || cur + " ") + n.toLocaleString("en-US");
  }

  /** A readable message from a failed call, naming the field when the server says which one. */
  function explain(r) {
    var d = r.data && r.data.detail;
    if (Array.isArray(d) && d.length) {
      return d.slice(0, 3).map(function (e) {
        var key = e.loc && e.loc[e.loc.length - 1];
        var msg = String(e.msg || "").replace(/^Value error, /, "");
        return LABELS[key] && !/^(Minimum|Maximum|Work|Employment|Currency)/.test(msg) ? LABELS[key] + ": " + msg : msg;
      }).join(" ");
    }
    return r.error || "Something went wrong. Try again.";
  }

  // =====================================================
  // LIST
  // =====================================================
  var listFilter = "all";

  function renderList() {
    var mine = R.nav();
    R.loading("Jobs & JDs");
    api("GET", "/api/recruiter/jobs").then(function (r) {
      if (!R.current(mine)) return;
      if (!r.ok) { R.failure("Jobs & JDs", r.status === 403 ? "This area is for recruiter accounts." : r.error); return; }
      drawList(r.data);
    });
  }

  function drawList(D) {
    var pills = [["all", "All"], ["open", "Open"], ["draft", "Drafts"], ["closed", "Closed"]].map(function (p) {
      return '<button type="button" class="filter-pill" data-filter="' + p[0] + '" aria-pressed="' + (listFilter === p[0]) + '">' + p[1] + " · " + D.counts[p[0]] + "</button>";
    }).join("");

    function body() {
      var rows = D.jobs.filter(function (j) { return listFilter === "all" || j.status === listFilter; });
      if (!D.counts.all) {
        return '<div class="card card-stack"><h2 class="card-title">No jobs yet</h2><p class="muted" style="margin:0">Create a job from a short form and Hiriq will write the job description for you. You edit it before anyone sees it.</p>' +
          '<div><a class="btn btn-grad" href="#jobs/new">' + icon("plus", 16) + "Create your first job</a></div></div>";
      }
      if (!rows.length) return '<div class="card"><p class="empty-inline">No ' + esc(listFilter) + " jobs.</p></div>";
      return '<div class="card table-card"><div class="table-scroll"><table><thead><tr><th>Job</th><th>Status</th><th>Must-have skills</th><th class="right">Matched</th><th>Updated</th></tr></thead><tbody>' +
        rows.map(function (j) {
          var meta = [j.location, expText(j.experience_min, j.experience_max)].filter(Boolean).join(" · ");
          var sk = (j.skills_required || []).slice(0, 3).map(function (s) { return '<span class="chip chip-neutral">' + esc(s) + "</span>"; }).join(" ");
          var more = (j.skills_required || []).length > 3 ? ' <span class="faint">+' + ((j.skills_required || []).length - 3) + "</span>" : "";
          return '<tr><td><a class="job-link" href="#jobs/' + esc(j.id) + '"><span class="cell-stack"><strong>' + esc(j.title) + "</strong>" + (meta ? "<small>" + esc(meta) + "</small>" : "") + "</span></a></td>" +
            "<td>" + chip(j.status) + (j.is_demo ? ' <span class="faint" style="font-size:12px">sample</span>' : "") + "</td>" +
            '<td><div class="chips-row">' + (sk || '<span class="faint">none yet</span>') + more + "</div></td>" +
            '<td class="right mono">' + (j.matched ? R.fmt(j.matched) : "—") + '</td><td class="nowrap faint">' + esc(R.ago(j.updated_at)) + "</td></tr>";
        }).join("") + "</tbody></table></div></div>";
    }

    view.innerHTML = '<div class="view">' + R.header("Jobs & JDs", '<a class="btn btn-grad" href="#jobs/new">' + icon("plus", 16) + "New job</a>") +
      (D.counts.all ? '<div class="filters" role="group" aria-label="Filter jobs">' + pills + "</div>" : "") + '<div id="jobs-body">' + body() + "</div></div>";

    var holder = view.querySelector(".filters");
    if (holder) {
      holder.addEventListener("click", function (e) {
        var b = e.target.closest("[data-filter]");
        if (!b) return;
        listFilter = b.getAttribute("data-filter");
        holder.querySelectorAll("[data-filter]").forEach(function (x) { x.setAttribute("aria-pressed", String(x === b)); });
        view.querySelector("#jobs-body").innerHTML = body();
      });
    }
  }

  // =====================================================
  // EDITOR
  // =====================================================
  function renderEditor(id) {
    var mine = R.nav();
    if (!id || id === "new") { drawEditor({ status: "draft", skills_required: [], skills_nice: [], salary_currency: "INR" }, null); return; }
    R.loading("Job");
    api("GET", "/api/recruiter/jobs/" + encodeURIComponent(id)).then(function (r) {
      if (!R.current(mine)) return;
      if (!r.ok) { R.failure("Job", r.status === 404 ? "That job does not exist, or it belongs to another account." : r.error); return; }
      drawEditor(r.data, null);
    });
  }

  function sel(id, value, options) {
    return '<select class="field field-sm" id="' + id + '">' + options.map(function (o) {
      return '<option value="' + esc(o[0]) + '"' + (String(value || "") === o[0] ? " selected" : "") + ">" + esc(o[1]) + "</option>";
    }).join("") + "</select>";
  }
  function group(id, label, control, hint) {
    return '<div class="field-group"><label class="label" for="' + id + '">' + label + "</label>" + control + (hint ? '<span class="hint" id="' + id + '-hint">' + hint + "</span>" : "") + "</div>";
  }
  function text(id, value, attrs) { return '<input class="field field-sm" id="' + id + '" value="' + esc(value == null ? "" : value) + '" ' + (attrs || "") + ">"; }
  function num(id, value, attrs) { return text(id, value, 'type="number" min="0" step="1" inputmode="numeric" ' + (attrs || "")); }
  function tagBox(key, label, hint) {
    return '<div class="field-group"><label class="label" for="tag-' + key + '">' + label + '</label><div class="tag-box" data-tags="' + key + '">' +
      '<span class="tag-list"></span><input class="tag-input" id="tag-' + key + '" placeholder="Type a skill, press Enter" autocomplete="off"></div><span class="hint">' + hint + "</span></div>";
  }

  /** `job` is the saved job (or a blank). `notice` is an optional [kind, message] shown after drawing. */
  function drawEditor(job, notice) {
    var S = {
      id: job.id || null, status: job.status || "draft", req: (job.skills_required || []).slice(), nice: (job.skills_nice || []).slice(),
      suggested: [], undo: null, busy: false, locked: job.status === "closed"
    };
    var saved = !!S.id;
    var $ = function (sel2) { return view.querySelector(sel2); };

    var modes = [["", "Not set"], ["onsite", "On-site"], ["hybrid", "Hybrid"], ["remote", "Remote"]];
    var types = [["", "Not set"], ["full-time", "Full-time"], ["part-time", "Part-time"], ["contract", "Contract"], ["internship", "Internship"]];
    var currencies = [["INR", "INR ₹"], ["USD", "USD $"], ["EUR", "EUR €"], ["GBP", "GBP £"]];

    var form =
      '<form class="card card-stack grow-1b" id="job-form" novalidate>' +
      '<div class="stack-2"><h2 class="card-title">Role details</h2><span class="card-sub">Hiriq uses these to write the job description and, later, to match candidates.</span></div>' +
      group("f-title", "Job title *", text("f-title", job.title, 'maxlength="160" placeholder="e.g. Senior Data Analyst" required')) +
      '<div class="form-grid">' + group("f-dept", "Department", text("f-dept", job.department, 'maxlength="120"')) + group("f-loc", "Location", text("f-loc", job.location, 'maxlength="120" placeholder="e.g. Mumbai"')) + "</div>" +
      '<div class="form-grid">' + group("f-mode", "Work mode", sel("f-mode", job.work_mode, modes)) + group("f-type", "Employment type", sel("f-type", job.employment_type, types)) + "</div>" +
      '<div class="form-grid">' + group("f-exp-min", "Experience, minimum (years)", num("f-exp-min", job.experience_min, 'max="50"')) + group("f-exp-max", "Experience, maximum (years)", num("f-exp-max", job.experience_max, 'max="50"')) + "</div>" +
      group("f-qual", "Qualification", text("f-qual", job.qualification, 'maxlength="200" placeholder="e.g. B.E./B.Tech in IT, CS or a related field"')) +
      '<div class="form-grid form-grid-3">' + group("f-cur", "Currency", sel("f-cur", job.salary_currency || "INR", currencies)) +
      group("f-sal-min", "Salary, minimum (per year)", num("f-sal-min", job.salary_min)) + group("f-sal-max", "Salary, maximum (per year)", num("f-sal-max", job.salary_max)) + "</div>" +
      '<span class="hint" id="salary-hint" aria-live="polite"></span>' +
      tagBox("req", "Required skills", "Must-haves. Candidates are matched on these first.") +
      tagBox("nice", "Nice-to-have skills", "Optional extras. A skill is either required or nice to have, never both.") +
      group("f-resp", "Day-to-day work", '<textarea class="field" id="f-resp" rows="5" maxlength="3000" placeholder="What will this person do in a typical week? A few lines is enough.">' + esc(job.responsibilities || "") + "</textarea>",
        "The AI turns these notes into the responsibilities. It never sees the salary.") +
      "</form>";

    var primary = S.status === "closed" ? "" : '<button type="button" class="btn btn-outline" id="btn-save">' + (saved ? "Save changes" : "Save draft") + "</button>";
    var publish = S.status === "draft" ? '<button type="button" class="btn btn-grad" id="btn-publish">Publish job</button>'
      : S.status === "closed" ? '<button type="button" class="btn btn-grad" id="btn-publish">Reopen job</button>' : "";
    var closeBtn = S.status === "open" ? '<button type="button" class="btn btn-outline" id="btn-close">Close job</button>' : "";
    var cloneBtn = saved ? '<button type="button" class="btn btn-outline" id="btn-clone">Clone</button>' : "";
    var delBtn = saved && S.status === "draft" ? '<button type="button" class="btn-danger" id="btn-delete">Delete draft</button>' : "";

    var jd =
      '<div class="card card-stack grow-2" id="jd-card">' +
      '<div class="row-between"><div class="stack-2"><h2 class="card-title">Job description</h2><span class="card-sub" id="jd-sub"></span></div>' +
      (S.locked ? "" : '<div class="jd-tools"><button type="button" class="btn-link" id="btn-undo" hidden>Undo AI rewrite</button><button type="button" class="btn btn-grad" id="btn-gen">' + icon("arrow", 16) + '<span id="gen-label">' + (job.has_description ? "Rewrite with AI" : "Write with AI") + "</span></button></div>") + "</div>" +
      '<div id="ai-note"></div><div id="suggest"></div>' +
      '<textarea class="field desc" id="f-desc" rows="22" maxlength="20000" aria-label="Job description" placeholder="Click “Write with AI” to draft the job description from the details on the left, or type your own.">' + esc(job.description || "") + "</textarea>" +
      '<div id="flags"></div><div id="job-msg" aria-live="polite"></div>' +
      '<div class="actions-bar">' + primary + publish + closeBtn + cloneBtn + delBtn + "</div></div>";

    var head = R.header(job.title || "New job", chip(S.status) + '<a class="btn btn-ghost glass" href="#jobs" style="min-height:40px">← All jobs</a>');
    view.innerHTML = '<div class="view">' + head + '<div class="row editor">' + form + jd + "</div></div>";

    // ---------- helpers bound to this render ----------
    function say(kind, message) {
      var box = $("#job-msg");
      box.innerHTML = message ? '<div class="notice notice-' + kind + '" role="' + (kind === "error" ? "alert" : "status") + '" style="animation:none">' + icon(kind === "good" ? "check" : "info", 18) + "<span>" + esc(message) + "</span></div>" : "";
      if (message && box.scrollIntoView) box.scrollIntoView({ block: "nearest" });
    }
    function paintSub() {
      $("#jd-sub").textContent = S.locked ? "This job is closed. Reopen it to make changes."
        : S.status === "open" ? "Live. Changes you save here are what candidates and matches use." : "Review and edit before you publish. You are in charge of the final text.";
    }
    function paintFlags(list) {
      $("#flags").innerHTML = list && list.length
        ? '<div class="notice notice-warn" role="note" style="animation:none">' + icon("warn", 18) + "<span><strong>Worth a second look.</strong> " + list.map(esc).join(" · ") + "</span></div>" : "";
    }
    function paintTags(key) {
      var list = key === "req" ? S.req : S.nice;
      $('[data-tags="' + key + '"] .tag-list').innerHTML = list.map(function (s, i) {
        return '<span class="chip ' + (key === "req" ? "chip-cyan" : "chip-violet") + '">' + esc(s) + (S.locked ? "" : '<button type="button" class="chip-x" data-rm="' + key + ":" + i + '" aria-label="Remove ' + esc(s) + '">' + icon("close", 12) + "</button>") + "</span>";
      }).join("");
    }
    function paintSuggest() {
      $("#suggest").innerHTML = S.suggested.length
        ? '<div class="suggest"><span class="faint" style="font-size:13px">AI suggests also (click to add as nice to have):</span>' +
        S.suggested.map(function (s, i) { return '<button type="button" class="chip chip-dashed" data-sg="' + i + '">+ ' + esc(s) + "</button>"; }).join("") + "</div>" : "";
    }
    function addSkills(key, raw) {
      String(raw || "").split(/[,;\n]/).forEach(function (piece) {
        var skill = piece.replace(/\s+/g, " ").trim().slice(0, 60);
        if (!skill) return;
        var k = skill.toLowerCase();
        var has = function (l) { return l.some(function (x) { return x.toLowerCase() === k; }); };
        if (key === "req") { S.nice = S.nice.filter(function (x) { return x.toLowerCase() !== k; }); if (!has(S.req) && S.req.length < 30) S.req.push(skill); }
        else if (!has(S.req) && !has(S.nice) && S.nice.length < 30) S.nice.push(skill);
      });
      paintTags("req"); paintTags("nice");
    }
    function salaryHint() {
      var cur = $("#f-cur").value, lo = $("#f-sal-min").value, hi = $("#f-sal-max").value;
      var a = lo === "" ? null : Number(lo), b = hi === "" ? null : Number(hi);
      var t = "";
      if (a != null && b != null) t = money(a, cur) + " to " + money(b, cur) + " per year";
      else if (a != null) t = "from " + money(a, cur) + " per year";
      else if (b != null) t = "up to " + money(b, cur) + " per year";
      $("#salary-hint").textContent = t ? "Reads as: " + t + ". Enter the full yearly amount." : "Optional. Enter the full yearly amount, for example 1200000 for 12 lakh.";
    }
    function collect() {
      var v = function (id) { return $("#" + id).value.trim(); };
      var n = function (id) { var x = v(id); return x === "" ? null : Number(x); };
      return {
        title: v("f-title"), department: v("f-dept"), location: v("f-loc"), work_mode: v("f-mode") || null, employment_type: v("f-type") || null,
        experience_min: n("f-exp-min"), experience_max: n("f-exp-max"), qualification: v("f-qual"), salary_currency: $("#f-cur").value,
        salary_min: n("f-sal-min"), salary_max: n("f-sal-max"), skills_required: S.req.slice(), skills_nice: S.nice.slice(),
        responsibilities: v("f-resp"), description: $("#f-desc").value
      };
    }
    function busy(on) {
      S.busy = on;
      view.querySelectorAll(".actions-bar button, #btn-gen").forEach(function (b) { b.disabled = on; });
    }

    // ---------- save / publish / close / clone / delete ----------
    function save() {
      var body = collect();
      if (body.title.length < 3) { say("error", "Give the job a title of at least 3 characters."); $("#f-title").focus(); return Promise.resolve(null); }
      var call = S.id ? api("PUT", "/api/recruiter/jobs/" + S.id, body) : api("POST", "/api/recruiter/jobs", body);
      return call.then(function (r) {
        if (!r.ok) { say("error", explain(r)); return null; }
        var created = !S.id;
        S.id = r.data.id; S.status = r.data.status; saved = true;
        $("#job-form").closest(".view").querySelector("h1").textContent = r.data.title;
        if (created) {
          if (window.history && history.replaceState) history.replaceState(null, "", "#jobs/" + S.id);
          mountSavedButtons();
        }
        paintFlags(r.data.wording_flags);
        return r.data;
      });
    }

    /** After a brand-new job is first saved, it gains the buttons only a saved job has. */
    function mountSavedButtons() {
      var bar = $(".actions-bar");
      $("#btn-save").textContent = "Save changes";
      if (!$("#btn-clone")) {
        bar.insertAdjacentHTML("beforeend", '<button type="button" class="btn btn-outline" id="btn-clone">Clone</button><button type="button" class="btn-danger" id="btn-delete">Delete draft</button>');
        on("#btn-clone", onClone); on("#btn-delete", onDelete);
      }
    }

    function onSave() {
      busy(true);
      save().then(function (j) {
        busy(false);
        if (j) say("good", saved && j.status === "draft" ? "Draft saved." : "Saved.");
      });
    }

    function onPublish() {
      var reopening = S.status === "closed";
      busy(true);
      (reopening ? Promise.resolve({ id: S.id }) : save()).then(function (j) {
        if (!j) { busy(false); return; }
        return api("POST", "/api/recruiter/jobs/" + S.id + "/publish").then(function (r) {
          busy(false);
          if (!r.ok) { say("error", (reopening ? "" : "Saved as a draft, but not opened. ") + explain(r)); return; }
          drawEditor(r.data, ["good", reopening ? "The job is open again." : "The job is open. Candidates can now be matched to it."]);
        });
      });
    }

    function onClose() {
      busy(true);
      api("POST", "/api/recruiter/jobs/" + S.id + "/close").then(function (r) {
        busy(false);
        if (!r.ok) { say("error", explain(r)); return; }
        drawEditor(r.data, ["good", "The job is closed. Its history stays in your funnel."]);
      });
    }

    function onClone() {
      busy(true);
      api("POST", "/api/recruiter/jobs/" + S.id + "/clone").then(function (r) {
        busy(false);
        if (!r.ok) { say("error", explain(r)); return; }
        history.replaceState(null, "", "#jobs/" + r.data.id);
        drawEditor(r.data, ["good", "Copied into a new draft. You are editing the copy."]);
      });
    }

    function onDelete(btn) {
      if (!btn.getAttribute("data-sure")) {
        btn.setAttribute("data-sure", "1");
        btn.textContent = "Really delete?";
        setTimeout(function () { if (btn.isConnected) { btn.removeAttribute("data-sure"); btn.textContent = "Delete draft"; } }, 4000);
        return;
      }
      busy(true);
      api("DELETE", "/api/recruiter/jobs/" + S.id).then(function (r) {
        if (!r.ok) { busy(false); say("error", explain(r)); return; }
        window.location.hash = "#jobs";
      });
    }

    // The loader reads these live, so edits made while waiting show up in "While you wait".
    var genRun = 0;
    var MODE_LABEL = { onsite: "On-site", hybrid: "Hybrid", remote: "Remote" };

    function longExp(min, max) {
      if (min == null && max == null) return "";
      if (min != null && max != null) return min === max ? min + " years" : min + " to " + max + " years";
      return min != null ? min + "+ years" : "up to " + max + " years";
    }
    function longSalary(b) {
      var lo = b.salary_min, hi = b.salary_max, cur = b.salary_currency;
      if (lo == null && hi == null) return "";
      if (lo != null && hi != null) return (lo === hi ? money(lo, cur) : money(lo, cur) + " to " + money(hi, cur)) + " per year";
      return (lo != null ? "from " + money(lo, cur) : "up to " + money(hi, cur)) + " per year";
    }
    /** The same facts block the server puts at the top of the JD, taken from the form. Only what was filled in. */
    function genFacts(b) {
      var type = String(b.employment_type || "").replace(/-/g, " ");
      return [
        ["Department", b.department],
        ["Location", [b.location, MODE_LABEL[b.work_mode]].filter(Boolean).join(" · ")],
        ["Employment", type ? type.charAt(0).toUpperCase() + type.slice(1) : ""],
        ["Experience", longExp(b.experience_min, b.experience_max)],
        ["Qualification", b.qualification],
        ["Salary", longSalary(b)]
      ].filter(function (f) { return f[1]; });
    }
    function genChecks() {
      var v = function (id) { var el = $("#" + id); return el ? el.value.trim() : ""; };
      var n = S.req.length;
      return [
        { ok: n >= 1 && n <= 8, focus: "tag-req",
          text: n > 8 ? n + " must-have skills is a lot. Move some to nice to have" : n ? "Must-have skills look focused" : "Add the must-have skills" },
        { ok: v("f-sal-min") !== "" || v("f-sal-max") !== "", focus: "f-sal-min",
          text: v("f-sal-min") !== "" || v("f-sal-max") !== "" ? "Salary range is in" : "Add a salary range. Candidates look for it" },
        { ok: v("f-exp-min") !== "" || v("f-exp-max") !== "", focus: "f-exp-min",
          text: v("f-exp-min") !== "" || v("f-exp-max") !== "" ? "Experience range is in" : "Add the years of experience you expect" },
        { ok: v("f-resp").length >= 60, focus: "f-resp",
          text: v("f-resp").length >= 60 ? "Day-to-day notes give the AI real detail" : "Write a few lines of day-to-day work for a richer JD" }
      ];
    }

    function onGenerate() {
      var body = collect();
      delete body.description;
      if (!body.skills_required.length && !body.responsibilities) {
        say("error", "Add at least one required skill or a few lines of day-to-day work first, so the job description has something real to say.");
        return;
      }
      if (body.title.length < 3) { say("error", "Give the job a title first."); $("#f-title").focus(); return; }
      var area = $("#f-desc"), run = ++genRun;
      busy(true);
      $("#gen-label").textContent = "Writing…";
      say("", "");
      var loader = null;
      if (window.HiriqJDLoader) {
        loader = window.HiriqJDLoader.start({
          area: area,
          facts: genFacts(body),
          sections: ["About the role", "What you will do", "What you bring"].concat(body.skills_nice.length ? ["Nice to have"] : []),
          checks: genChecks,
          onCancel: function () {
            genRun++; // the reply, when it arrives, is thrown away
            busy(false);
            $("#gen-label").textContent = area.value.trim() ? "Rewrite with AI" : "Write with AI";
            say("info", "Cancelled. Your text is unchanged. The request may still count toward your hourly limit.");
          }
        });
      } else {
        say("info", "Writing the job description. This can take up to a minute on the free models.");
      }
      api("POST", "/api/recruiter/jobs/generate", body).then(function (r) {
        if (run !== genRun || !area.isConnected) return; // cancelled, or the page was redrawn
        busy(false);
        $("#gen-label").textContent = "Rewrite with AI";
        if (!r.ok) { if (loader) loader.fail(); say("error", explain(r)); return; }
        if (area.value.trim() && area.value !== r.data.description) { S.undo = area.value; $("#btn-undo").hidden = false; }
        S.suggested = r.data.suggested_skills || [];
        paintSuggest(); paintFlags(r.data.wording_flags);
        $("#ai-note").innerHTML = '<div class="notice notice-info" role="note" style="animation:none">' + icon("info", 18) +
          "<span>Drafted by AI (" + esc(String(r.data.model).replace(/:free$/, "")) + "). The facts at the top come from your form. Read it through and edit anything you like before publishing.</span></div>";
        say("", "");
        if (loader) loader.finish(r.data.description); else area.value = r.data.description;
      });
    }

    // ---------- wire up ----------
    paintSub(); paintTags("req"); paintTags("nice"); salaryHint();
    view.querySelectorAll(".tag-box").forEach(function (box) {
      var key = box.getAttribute("data-tags"), input = box.querySelector(".tag-input");
      box.addEventListener("click", function (e) {
        var rm = e.target.closest("[data-rm]");
        if (rm) { var p = rm.getAttribute("data-rm").split(":"); (p[0] === "req" ? S.req : S.nice).splice(Number(p[1]), 1); paintTags(p[0]); return; }
        input.focus();
      });
      input.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === ",") { e.preventDefault(); addSkills(key, input.value); input.value = ""; }
        else if (e.key === "Backspace" && !input.value) { (key === "req" ? S.req : S.nice).pop(); paintTags(key); }
      });
      input.addEventListener("input", function () { if (/[,;\n]/.test(input.value)) { addSkills(key, input.value); input.value = ""; } });
      input.addEventListener("blur", function () { if (input.value.trim()) { addSkills(key, input.value); input.value = ""; } });
    });
    ["f-cur", "f-sal-min", "f-sal-max"].forEach(function (id) { $("#" + id).addEventListener("input", salaryHint); });
    $("#job-form").addEventListener("submit", function (e) { e.preventDefault(); });
    $("#suggest").addEventListener("click", function (e) {
      var b = e.target.closest("[data-sg]");
      if (!b) return;
      addSkills("nice", S.suggested[Number(b.getAttribute("data-sg"))]);
      S.suggested.splice(Number(b.getAttribute("data-sg")), 1);
      paintSuggest();
    });
    var on = function (id, fn) { var el = $(id); if (el) el.addEventListener("click", function () { if (!S.busy) fn(el); }); };
    on("#btn-save", onSave); on("#btn-publish", onPublish); on("#btn-close", onClose); on("#btn-clone", onClone);
    on("#btn-delete", onDelete); on("#btn-gen", onGenerate);
    on("#btn-undo", function (el) { if (S.undo != null) { $("#f-desc").value = S.undo; S.undo = null; el.hidden = true; paintFlags([]); } });

    if (S.locked) {
      view.querySelectorAll("#job-form input, #job-form select, #job-form textarea, #f-desc").forEach(function (el) { el.disabled = true; });
    }
    paintFlags(job.wording_flags);
    if (notice) say(notice[0], notice[1]);
    window.scrollTo(0, 0);
  }

  return { list: renderList, edit: renderEditor };
};
