/* Hiriq — recruiter: Pipeline (a stage board per job, notes, thumbs on a match).
   A factory: recruiter.js calls window.HiriqPipeline(helpers) and gets { show(jobId) } back.
   Columns run sourced → hired, with a rejected lane beside them. Cards move by drag and drop or by the "Move to…" menu
   (the menu is the keyboard and phone route). Nobody is moved automatically: every stage change is one of your clicks.
   Thumbs only appear once a candidate has been ranked for the job, and they never change a score. */
window.HiriqPipeline = function (R) {
  var view = R.view, esc = R.esc, icon = R.icon, api = R.api;

  var STAGES = [["sourced", "Sourced"], ["shortlisted", "Shortlisted"], ["interview", "Interview"], ["offer", "Offer"], ["hired", "Hired"]];
  var LABEL = { sourced: "Sourced", shortlisted: "Shortlisted", interview: "Interview", offer: "Offer", hired: "Hired", rejected: "Rejected" };
  var STRONG = 70;

  // ---------- small helpers ----------
  function say(r, fallback) {
    var d = r.data && r.data.detail;
    if (Array.isArray(d) && d.length) return d.slice(0, 2).map(function (e) { return String(e.msg || "").replace(/^Value error, /, ""); }).join(" ");
    return (d && d.message) || r.error || fallback || "Something went wrong. Try again.";
  }
  function scoreClass(n) { return n >= STRONG ? " strong" : n >= 40 ? " mid" : " low"; }
  function chip(c) { return c.source === "platform" ? '<span class="chip chip-violet">Hiriq member</span>' : ""; }
  function years(n) { return n == null ? "" : (n === 1 ? "1 yr" : +Number(n).toFixed(1) + " yrs"); }
  var THUMB = '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path fill="currentColor" d="M2 21h4V9H2v12zM23 10c0-1.1-.9-2-2-2h-6.3l.95-4.57.03-.32c0-.41-.17-.79-.44-1.06L14.17 1 7.59 7.59C7.22 7.95 7 8.45 7 9v10c0 1.1.9 2 2 2h9c.83 0 1.54-.5 1.84-1.22l3.02-7.05c.09-.23.14-.47.14-.73v-2z"/></svg>';

  // =====================================================
  // state of the one open page
  // =====================================================
  var S = null;   // { token, jobId, jobs, board, selected:{}, noteOpen, msg:{kind,text}, busy, dragging }

  function alive() { return S && R.current(S.token); }
  function setMsg(kind, text) { S.msg = text ? { kind: kind, text: text } : null; }

  // =====================================================
  // entry
  // =====================================================
  function show(jobId) {
    var mine = R.nav();
    R.loading("Pipeline");
    api("GET", "/api/recruiter/jobs").then(function (r) {
      if (!R.current(mine)) return;
      if (!r.ok) { R.failure("Pipeline", r.status === 403 ? "This area is for recruiter accounts." : say(r)); return; }
      S = { token: mine, jobId: jobId || "", jobs: r.data.jobs || [], board: null, selected: {}, noteOpen: null, msg: null, busy: false, dragging: null };
      if (!S.jobId) { draw(); return; }
      api("GET", "/api/recruiter/jobs/" + encodeURIComponent(S.jobId) + "/pipeline").then(function (b) {
        if (!R.current(mine)) return;
        if (!b.ok) { setMsg("error", b.status === 404 ? "That job could not be found." : say(b)); S.jobId = ""; draw(); return; }
        S.board = b.data;
        draw();
      });
    });
  }

  function base() { return "/api/recruiter/jobs/" + encodeURIComponent(S.jobId); }

  // =====================================================
  // drawing
  // =====================================================
  function picker() {
    var opts = S.jobs.map(function (j) {
      return '<option value="' + esc(j.id) + '"' + (j.id === S.jobId ? " selected" : "") + ">" + esc(j.title || "Untitled") + (j.status && j.status !== "open" ? " (" + esc(j.status) + ")" : "") +
        (j.in_pipeline ? " · " + j.in_pipeline + " in pipeline" : "") + "</option>";
    }).join("");
    return '<div class="field-group"><label class="label" for="pl-job">Job</label>' +
      '<select class="field field-sm" id="pl-job"><option value="">Choose a job…</option>' + opts + "</select></div>";
  }

  function summary() {
    var b = S.board, c = b.counts;
    var tiles = STAGES.map(function (s) {
      return '<div class="pl-tile"><span class="mono">' + c[s[0]] + "</span><small>" + s[1] + "</small></div>";
    }).join("") + '<div class="pl-tile pl-tile-rej"><span class="mono">' + c.rejected + "</span><small>Rejected</small></div>";
    return '<div class="card card-stack"><div class="row-between"><div class="stack-2"><h2 class="card-title">' + esc(b.job.title) + '</h2><span class="card-sub">' +
      [b.job.location, b.job.work_mode, b.job.status !== "open" ? b.job.status : ""].filter(Boolean).map(esc).join(" · ") + "</span></div>" +
      '<div class="head-tools"><a class="btn btn-outline" href="#matching/' + esc(b.job.id) + '" style="min-height:40px">See the ranking</a></div></div>' +
      '<div class="pl-tiles" role="group" aria-label="Candidates per stage">' + tiles + "</div></div>";
  }

  function thumbs(c) {
    if (c.score == null) return "";
    return '<span class="thumbs" role="group" aria-label="Was this a good match?">' +
      '<button type="button" class="thumb-btn up" data-fb="1" data-c="' + esc(c.candidate_id) + '" aria-pressed="' + (c.feedback === 1) + '" aria-label="Good match" title="Good match">' + THUMB + "</button>" +
      '<button type="button" class="thumb-btn down" data-fb="-1" data-c="' + esc(c.candidate_id) + '" aria-pressed="' + (c.feedback === -1) + '" aria-label="Not a good match" title="Not a good match">' + THUMB + "</button></span>";
  }

  function moveMenu(c) {
    var opts = STAGES.concat([["rejected", "Rejected"]]).filter(function (s) { return s[0] !== c.stage; }).map(function (s) {
      return '<option value="' + s[0] + '">' + (s[0] === "rejected" ? "Reject" : s[1]) + "</option>";
    }).join("");
    return '<select class="field field-sm pl-move" data-move="' + esc(c.candidate_id) + '" aria-label="Move ' + esc(c.name) + ' to…"><option value="">Move to…</option>' + opts + "</select>";
  }

  function editor(c) {
    return '<form class="pl-edit" data-edit="' + esc(c.candidate_id) + '">' +
      '<label class="label" for="n-' + esc(c.candidate_id) + '">Note</label>' +
      '<textarea class="field" id="n-' + esc(c.candidate_id) + '" rows="3" maxlength="2000" placeholder="What did you think? What to ask next?">' + esc(c.note || "") + "</textarea>" +
      (c.stage === "rejected" ? '<label class="label" for="r-' + esc(c.candidate_id) + '">Reason for rejecting</label><input class="field field-sm" id="r-' + esc(c.candidate_id) + '" maxlength="200" value="' + esc(c.rejection_reason || "") + '" placeholder="Kept for your own records">' : "") +
      '<div class="actions-bar"><button type="submit" class="btn btn-grad" style="min-height:38px">Save</button><button type="button" class="btn btn-outline" data-note-cancel style="min-height:38px">Cancel</button></div></form>';
  }

  function cardHtml(c) {
    var meta = [c.headline, c.location, years(c.years)].filter(Boolean).map(esc).join(" · ");
    var score = c.score != null ? '<span class="score-chip' + scoreClass(c.score) + '" aria-label="Match score ' + c.score + ' out of 100">' + c.score + "</span>" : '<span class="faint pl-unranked" title="Rank this job in Matching to get a score">not ranked</span>';
    var open = S.noteOpen === c.candidate_id;
    return '<li class="pl-card" draggable="true" data-cid="' + esc(c.candidate_id) + '">' +
      '<div class="pl-top"><a class="pl-name" href="#candidates/' + esc(c.candidate_id) + '">' + esc(c.name || "Unnamed") + "</a>" + score + "</div>" +
      (meta ? '<small class="pl-meta">' + meta + "</small>" : "") + (chip(c) ? '<div class="pl-chips">' + chip(c) + "</div>" : "") +
      (c.stage === "rejected" && c.rejection_reason ? '<p class="pl-reason">Reason: ' + esc(c.rejection_reason) + "</p>" : "") +
      (c.note && !open ? '<p class="pl-note">' + esc(c.note) + "</p>" : "") +
      (open ? editor(c) : "") +
      '<div class="pl-actions">' + thumbs(c) +
      '<button type="button" class="btn-link" data-note="' + esc(c.candidate_id) + '">' + (c.note ? "Edit note" : "Add note") + "</button>" +
      moveMenu(c) +
      '<button type="button" class="btn-link pl-remove" data-remove="' + esc(c.candidate_id) + '">Remove</button></div></li>';
  }

  function columnHtml(col, rejected) {
    return '<section class="pl-col' + (rejected ? " pl-col-rej" : "") + '" aria-label="' + esc(col.label) + ", " + col.count + (col.count === 1 ? " candidate" : " candidates") + '">' +
      '<header class="pl-col-head"><strong>' + esc(col.label) + '</strong><span class="mono">' + col.count + "</span></header>" +
      '<ul class="pl-cards" data-drop="' + col.stage + '">' + (col.cards.length ? col.cards.map(cardHtml).join("") : '<li class="pl-empty">Nobody here</li>') + "</ul></section>";
  }

  function addPanel() {
    var b = S.board;
    if (!b.can_add) {
      return '<div class="card"><div class="notice notice-warn" role="status" style="animation:none">' + icon("warn", 18) + "<span>This job is closed, so no one new can be added. Reopen it from Jobs &amp; JDs to add more candidates.</span></div></div>";
    }
    var strong = b.available.filter(function (a) { return a.score != null && a.score >= STRONG; });
    var picked = Object.keys(S.selected).length;
    var rows = b.available.map(function (a) {
      var right = a.score != null ? '<span class="score-chip' + scoreClass(a.score) + '">' + a.score + "</span>" : '<span class="faint">' + (a.has_profile ? "not ranked yet" : "no profile yet") + "</span>";
      var meta = [a.headline, a.location, years(a.years)].filter(Boolean).map(esc).join(" · ");
      return '<li class="pl-add-row"><label><input type="checkbox" data-pick="' + esc(a.candidate_id) + '"' + (S.selected[a.candidate_id] ? " checked" : "") + ">" +
        '<span class="cell-stack"><strong>' + esc(a.name || "Unnamed") + "</strong>" + (meta ? "<small>" + meta + "</small>" : "") + "</span></label>" + chip(a) + right + "</li>";
    }).join("");
    var more = b.available_total > b.available.length ? '<p class="hint">Showing the first ' + b.available.length + " of " + b.available_total + ". Rank the job in Matching to bring the best fits to the top.</p>" : "";
    return '<div class="card card-stack"><div class="stack-2"><h2 class="card-title">Add candidates</h2><span class="card-sub">Best matches first. People you add start in Sourced.</span></div>' +
      (b.available.length
        ? '<ul class="pl-add-list">' + rows + "</ul>" + more +
          '<div class="actions-bar"><button type="button" class="btn btn-grad" id="pl-add"' + (picked && !S.busy ? "" : " disabled") + ">" + (picked ? "Add " + picked + " selected" : "Add selected") + "</button>" +
          (strong.length ? '<button type="button" class="btn btn-outline" id="pl-add-strong"' + (S.busy ? " disabled" : "") + ">Add the " + strong.length + " scoring " + STRONG + "+</button>" : "") + "</div>"
        : '<p class="empty-inline">' + (b.counts.total ? "Everyone in your pool is already in this pipeline." : 'Your pool is empty. Add resumes in <a href="#candidates">Candidates</a> first.') + "</p>") + "</div>";
  }

  function msgHtml() {
    var m = S.msg;
    return m ? '<div class="notice notice-' + m.kind + '" role="' + (m.kind === "error" ? "alert" : "status") + '" style="animation:none">' + icon(m.kind === "good" ? "check" : "info", 18) + "<span>" + esc(m.text) + "</span></div>" : "";
  }

  function draw() {
    if (!alive()) return;
    var head = R.header("Pipeline", "");
    if (!S.jobs.length) {
      view.innerHTML = '<div class="view">' + head + '<div class="card card-stack"><h2 class="card-title">Create a job first</h2><p class="muted" style="margin:0">The pipeline tracks candidates for a job, so it needs one.</p>' +
        '<div class="actions-bar"><a class="btn btn-grad" href="#jobs/new">Create a job</a></div></div></div>';
      return;
    }
    var b = S.board, body;
    if (!b) {
      body = '<div class="card"><p class="empty-inline" style="padding:14px 0">Pick a job to see its pipeline.</p></div>';
    } else {
      var empty = !b.counts.total ? '<div class="card"><p class="empty-inline" style="padding:10px 0">Nobody is in this pipeline yet. Add candidates below, or from the ranking in <a href="#matching/' + esc(b.job.id) + '">Matching</a>.</p></div>' : "";
      body = summary() + msgHtml() + empty +
        '<div class="pl-board" id="pl-board">' + b.stages.map(function (c) { return columnHtml(c, false); }).join("") + "</div>" +
        columnHtml(b.rejected, true).replace('class="pl-col pl-col-rej"', 'class="pl-col pl-col-rej pl-rej-wide"') + addPanel();
    }
    view.innerHTML = '<div class="view">' + head + (b ? "" : msgHtml()) + '<div class="card">' + picker() + "</div>" + body + "</div>";
    wire();
  }

  // =====================================================
  // local updates (the server answers with the changed card and the new counts)
  // =====================================================
  function sortKey(c) { return [c.score == null ? 1 : 0, -(c.score || 0), String(c.name || "").toLowerCase(), c.candidate_id]; }
  function cmp(a, b) {
    var x = sortKey(a), y = sortKey(b);
    for (var i = 0; i < x.length; i++) { if (x[i] < y[i]) return -1; if (x[i] > y[i]) return 1; }
    return 0;
  }
  function columns() { return S.board.stages.concat([S.board.rejected]); }
  function findCard(cid) {
    var out = null;
    columns().forEach(function (col) { col.cards.forEach(function (c) { if (c.candidate_id === cid) out = c; }); });
    return out;
  }
  function placeCard(card, counts) {
    columns().forEach(function (col) { col.cards = col.cards.filter(function (c) { return c.candidate_id !== card.candidate_id; }); });
    var target = columns().filter(function (col) { return col.stage === card.stage; })[0];
    target.cards.push(card); target.cards.sort(cmp);
    columns().forEach(function (col) { col.count = col.cards.length; });
    S.board.counts = counts;
  }
  function dropCard(cid, counts) {
    columns().forEach(function (col) { col.cards = col.cards.filter(function (c) { return c.candidate_id !== cid; }); col.count = col.cards.length; });
    S.board.counts = counts;
  }

  // =====================================================
  // actions
  // =====================================================
  function addPeople(ids) {
    if (S.busy || !ids.length) return;
    var tok = S.token;
    S.busy = true; setMsg("", ""); draw();
    api("POST", base() + "/pipeline", { candidate_ids: ids }).then(function (r) {
      if (!alive() || S.token !== tok) return;
      S.busy = false;
      if (!r.ok) { setMsg("error", say(r)); draw(); return; }
      var n = r.data.added;
      S.board = r.data; S.selected = {};
      setMsg("good", n + (n === 1 ? " candidate was" : " candidates were") + " added to Sourced." + (r.data.already_there ? " " + r.data.already_there + " already there." : ""));
      draw();
    });
  }

  function patch(cid, body, okText) {
    var tok = S.token;
    return api("PATCH", base() + "/pipeline/" + encodeURIComponent(cid), body).then(function (r) {
      if (!alive() || S.token !== tok) return null;
      if (!r.ok) { setMsg("error", say(r)); draw(); return null; }
      placeCard(r.data.card, r.data.counts);
      setMsg(okText ? "good" : "", okText || "");
      draw();
      return r.data.card;
    });
  }

  function moveTo(cid, stage) {
    var c = findCard(cid);
    if (!c || c.stage === stage) { draw(); return; }
    patch(cid, { stage: stage }, c.name + (stage === "rejected" ? " was rejected. Open Edit note to record why." : " moved to " + LABEL[stage] + "."));
  }

  function thumb(cid, label) {
    var c = findCard(cid);
    if (!c) return;
    var next = c.feedback === label ? 0 : label;      // tapping the same thumb again clears it
    var tok = S.token;
    api("PUT", base() + "/matches/" + encodeURIComponent(cid) + "/feedback", { label: next }).then(function (r) {
      if (!alive() || S.token !== tok) return;
      if (!r.ok) { setMsg("error", say(r)); draw(); return; }
      c.feedback = r.data.label; setMsg("", ""); draw();
    });
  }

  function remove(cid, btn) {
    if (!btn.getAttribute("data-sure")) {
      btn.setAttribute("data-sure", "1"); btn.textContent = "Really remove?";
      setTimeout(function () { if (btn.isConnected) { btn.removeAttribute("data-sure"); btn.textContent = "Remove"; } }, 4000);
      return;
    }
    var tok = S.token, c = findCard(cid);
    api("DELETE", base() + "/pipeline/" + encodeURIComponent(cid)).then(function (r) {
      if (!alive() || S.token !== tok) return;
      if (!r.ok) { setMsg("error", say(r)); draw(); return; }
      dropCard(cid, r.data.counts); S.noteOpen = null;
      // they are addable again: reload the board so the "Add candidates" list is right
      api("GET", base() + "/pipeline").then(function (b) {
        if (!alive() || S.token !== tok) return;
        if (b.ok) S.board = b.data;
        setMsg("good", (c ? c.name : "The candidate") + " was taken off this pipeline."); draw();
      });
    });
  }

  // =====================================================
  // wiring
  // =====================================================
  function wire() {
    var sel = view.querySelector("#pl-job");
    if (sel) sel.addEventListener("change", function () { window.location.hash = sel.value ? "#pipeline/" + encodeURIComponent(sel.value) : "#pipeline"; });
    if (!S.board) return;

    view.addEventListener("click", onClick);   // the same function twice is ignored by the browser, so redraws never stack listeners
    view.querySelectorAll("[data-move]").forEach(function (m) {
      m.addEventListener("change", function () { if (m.value) moveTo(m.getAttribute("data-move"), m.value); });
    });
    view.querySelectorAll("[data-pick]").forEach(function (box) {
      box.addEventListener("change", function () {
        var id = box.getAttribute("data-pick");
        if (box.checked) S.selected[id] = true; else delete S.selected[id];
        var n = Object.keys(S.selected).length, add = view.querySelector("#pl-add");
        if (add) { add.disabled = !n || S.busy; add.textContent = n ? "Add " + n + " selected" : "Add selected"; }
      });
    });
    var add = view.querySelector("#pl-add"); if (add) add.addEventListener("click", function () { addPeople(Object.keys(S.selected)); });
    var strong = view.querySelector("#pl-add-strong");
    if (strong) strong.addEventListener("click", function () {
      addPeople(S.board.available.filter(function (a) { return a.score != null && a.score >= STRONG; }).map(function (a) { return a.candidate_id; }));
    });
    view.querySelectorAll("[data-edit]").forEach(function (f) {
      f.addEventListener("submit", function (e) {
        e.preventDefault();
        var cid = f.getAttribute("data-edit"), c = findCard(cid);
        var body = { note: f.querySelector("textarea").value };
        var reason = f.querySelector("input"); if (reason) body.rejection_reason = reason.value;
        S.noteOpen = null;
        patch(cid, body, c ? "Saved the note for " + c.name + "." : "Saved.");
      });
      var ta = f.querySelector("textarea"); if (ta) ta.focus();
    });

    // drag and drop between columns
    view.querySelectorAll(".pl-card").forEach(function (card) {
      card.addEventListener("dragstart", function (e) {
        S.dragging = card.getAttribute("data-cid"); card.classList.add("dragging");
        if (e.dataTransfer) { e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", S.dragging); }
      });
      card.addEventListener("dragend", function () { S.dragging = null; card.classList.remove("dragging"); view.querySelectorAll(".pl-cards.over").forEach(function (x) { x.classList.remove("over"); }); });
    });
    view.querySelectorAll("[data-drop]").forEach(function (zone) {
      zone.addEventListener("dragover", function (e) { if (!S.dragging) return; e.preventDefault(); zone.classList.add("over"); });
      zone.addEventListener("dragleave", function (e) { if (!zone.contains(e.relatedTarget)) zone.classList.remove("over"); });
      zone.addEventListener("drop", function (e) {
        e.preventDefault(); zone.classList.remove("over");
        var cid = S.dragging || (e.dataTransfer && e.dataTransfer.getData("text/plain"));
        S.dragging = null;
        if (cid) moveTo(cid, zone.getAttribute("data-drop"));
      });
    });
  }

  function onClick(e) {
    if (!alive()) return;
    var t = e.target.closest("[data-fb],[data-note],[data-note-cancel],[data-remove]");
    if (!t) return;
    if (t.hasAttribute("data-fb")) thumb(t.getAttribute("data-c"), +t.getAttribute("data-fb"));
    else if (t.hasAttribute("data-note")) { S.noteOpen = t.getAttribute("data-note"); draw(); }
    else if (t.hasAttribute("data-note-cancel")) { S.noteOpen = null; draw(); }
    else if (t.hasAttribute("data-remove")) remove(t.getAttribute("data-remove"), t);
  }

  return { show: show };
};
