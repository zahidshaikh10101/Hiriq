/* Hiriq — candidate: applying to a job.
   A factory: candidate.js calls window.HiriqCandidateApply(helpers) and gets { applications, jobActions } back.
     #applications   what you have applied to, and withdraw         (/api/candidate/applications)
   jobActions(job, element) draws the Apply box (or "You applied" with Withdraw) on a job page.
   Applying is the only place your details go to a recruiter: only that job's owner, only the resume and letter you pick,
   only when you click Apply, and you can withdraw. */
window.HiriqCandidateApply = function (H) {
  var view = H.view, esc = H.esc, api = H.api, notice = H.notice, explain = H.explain;
  function $(sel) { return view.querySelector(sel); }

  // =====================================================
  // my applications
  // =====================================================
  function applications() {
    var mine = H.nav();
    H.loading("Applications");
    api("GET", "/api/candidate/applications").then(function (r) {
      if (!H.current(mine)) return;
      if (!r.ok) { H.failure("Applications", r.status === 403 ? "This area is for candidate accounts." : explain(r)); return; }
      var items = r.data.applications;
      var body = items.length ? '<div class="job-list">' + items.map(function (a) {
        var open = a.job_status === "open";
        return '<article class="card doc-row"><div class="stack-2" style="flex:1;min-width:220px"><h3>' + (open ? '<a href="#jobs/' + esc(a.job_id) + '">' + esc(a.job_title) + "</a>" : esc(a.job_title || "A job")) + "</h3>" +
          '<div class="job-meta">' + [a.company, "Applied " + H.ago(a.applied_at), "Sent: " + a.resume_label + (a.letter_label ? " and " + a.letter_label : ""), a.has_message ? "with a message" : ""]
            .filter(Boolean).map(function (x) { return "<span>" + esc(x) + "</span>"; }).join("") + "</div></div>" +
          '<div class="fit-side"><span class="status-chip ' + (open ? "good" : "") + '">' + (open ? "Job open" : "Job closed") + '</span><button type="button" class="btn-link" data-withdraw="' + esc(a.id) + '">Withdraw</button></div></article>';
      }).join("") + "</div>" : '<div class="card"><p class="empty-inline">You have not applied to anything yet. Open a job and use Apply; nothing is sent until you do.</p></div>';
      view.innerHTML = '<div class="view">' + H.header("Applications", H.LIVE) + '<div id="msg" aria-live="polite"></div>' +
        '<div class="card"><span class="card-sub">Each application is a copy of what you sent, held by the recruiter who posted the job. Withdraw deletes that copy. Recruiters decide who moves forward; Hiriq never does it for them.</span></div>' +
        '<div class="row-between"><h2 class="card-title">Your applications</h2><span class="faint" style="font-size:13px">' + items.length + " of " + r.data.max + "</span></div>" + body + "</div>";
      view.querySelectorAll("[data-withdraw]").forEach(function (b) {
        b.addEventListener("click", function () {
          if (!window.confirm("Withdraw this application? The recruiter loses the copy you sent.")) return;
          b.disabled = true;
          api("DELETE", "/api/candidate/applications/" + encodeURIComponent(b.getAttribute("data-withdraw"))).then(function (d) {
            if (!d.ok) { $("#msg").innerHTML = notice("error", explain(d)); b.disabled = false; return; }
            applications();
          });
        });
      });
    });
  }

  // =====================================================
  // on a job page: apply, or withdraw
  // =====================================================
  function jobActions(J, el) {
    if (!el) return;
    el.innerHTML = '<div class="card loading" role="status">Loading…</div>';
    Promise.all([api("GET", "/api/candidate/applications"), api("GET", "/api/candidate/versions"), api("GET", "/api/candidate/letters")]).then(function (rs) {
      if (!document.body.contains(el)) return;
      if (!rs[0].ok) { el.innerHTML = notice("error", explain(rs[0])); return; }
      var apps = rs[0].data.applications, versions = rs[1].ok ? rs[1].data.versions : [], letters = rs[2].ok ? rs[2].data.letters : [];
      var done = apps.filter(function (a) { return a.job_id === J.id; })[0];
      if (done) {
        el.innerHTML = '<div class="card card-stack"><div class="row-between"><div class="stack-2"><h2 class="card-title">You applied</h2><span class="card-sub">' + esc("Applied " + H.ago(done.applied_at) + ". Sent: " + done.resume_label + (done.letter_label ? " and " + done.letter_label : "") + ".") +
          '</span></div><button type="button" class="btn btn-outline" id="withdraw">Withdraw</button></div><div id="apply-msg" aria-live="polite"></div></div>';
        $("#withdraw").addEventListener("click", function () {
          if (!window.confirm("Withdraw this application? The recruiter loses the copy you sent.")) return;
          this.disabled = true;
          api("DELETE", "/api/candidate/applications/" + encodeURIComponent(done.id)).then(function (d) {
            if (!d.ok) { $("#apply-msg").innerHTML = notice("error", explain(d)); $("#withdraw").disabled = false; return; }
            jobActions(J, el);
          });
        });
        return;
      }
      // tailored versions made for this job come first
      var ordered = versions.slice().sort(function (a, b) { return (b.job_id === J.id) - (a.job_id === J.id); });
      var vopts = '<option value="">Your uploaded resume</option>' + ordered.map(function (v) { return '<option value="' + esc(v.id) + '">' + esc(v.label + (v.job_id === J.id ? " (made for this job)" : "")) + "</option>"; }).join("");
      var lopts = '<option value="">No cover letter</option>' + letters.slice().sort(function (a, b) { return (b.job_id === J.id) - (a.job_id === J.id); })
        .map(function (l) { return '<option value="' + esc(l.id) + '">' + esc(l.label + (l.job_id === J.id ? " (made for this job)" : "")) + "</option>"; }).join("");
      el.innerHTML = '<div class="card card-stack"><div class="stack-2"><h2 class="card-title">Apply</h2><span class="card-sub">Choose what to send. Nothing leaves Hiriq until you click Apply.</span></div>' +
        '<div class="field-group"><label class="label" for="ap-version">Resume to send</label><select class="field field-sm" id="ap-version">' + vopts + "</select></div>" +
        '<div class="field-group"><label class="label" for="ap-letter">Cover letter</label><select class="field field-sm" id="ap-letter">' + lopts + "</select></div>" +
        '<div class="field-group"><label class="label" for="ap-message">Short message (optional)</label><textarea class="field" id="ap-message" rows="3" maxlength="1000" placeholder="Anything the recruiter should know, such as when you could start"></textarea></div>' +
        '<p class="privacy-note">Applying sends a copy of the resume and letter you chose, your message, your contact details (email, phone and links) and your fit score to the recruiter who posted this job, and to nobody else. ' +
        "Later edits do not change that copy. You can withdraw any time.</p>" +
        '<div id="apply-msg" aria-live="polite"></div><div class="actions-bar"><button type="button" class="btn btn-grad" id="apply-go"' + (J.has_profile ? "" : " disabled") + ">Apply to this job</button></div>" +
        "</div>";
      $("#apply-go").addEventListener("click", function () {
        var btn = this; btn.disabled = true;
        var body = { message: $("#ap-message").value.trim() || null };
        if ($("#ap-version").value) body.version_id = $("#ap-version").value;
        if ($("#ap-letter").value) body.letter_id = $("#ap-letter").value;
        api("POST", "/api/candidate/jobs/" + encodeURIComponent(J.id) + "/apply", body).then(function (r) {
          if (!r.ok) { $("#apply-msg").innerHTML = notice("error", explain(r)); btn.disabled = false; return; }
          jobActions(J, el);
        });
      });
    });
  }

  return { applications: applications, jobActions: jobActions };
};