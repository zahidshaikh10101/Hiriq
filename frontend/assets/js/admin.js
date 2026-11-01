/* Hiriq — admin console. Live data from the backend (/api/admin/*).
   Views are chosen by the URL hash: #overview #users #jobs #model #audit.
   Overview, Users and Audit read your real database. Jobs and Model quality have nothing to show yet. */
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
  var STATUS = { good: "✓", warn: "!", bad: "×" };
  function statusBadge(state) {
    return '<span class="status-badge status-' + state + '" aria-hidden="true">' + STATUS[state] + "</span>";
  }
  function header(title, extra, live) {
    var badge = live === null ? ""
      : live === false
        ? '<span class="demo-badge"><span class="dot" style="background:rgb(var(--warn))"></span>Not built yet</span>'
        : '<span class="live-badge"><span class="dot pulse" style="background:rgb(var(--a4))"></span>Live data</span>';
    return (
      '<header class="page-head"><div class="stack-2"><span class="faint" style="font-size:13px">Admin console</span><h1>' + esc(title) + "</h1></div>" +
      '<div class="head-tools">' + (extra || "") + badge + "</div></header>"
    );
  }
  function meter(label, valueText, pct, cls, delay, height) {
    return (
      '<div class="meter"><div class="meter-top"><span>' + esc(label) + "</span><span>" + valueText + "</span></div>" +
      '<div class="bar-track" style="height:' + (height || 10) + 'px"><div class="bar-fill ' + (cls || "") + '" style="width:' + Math.max(2, pct) + "%;animation-delay:" + delay + 's"></div></div></div>'
    );
  }
  function loading(title) {
    view.innerHTML = '<div class="view">' + header(title) + '<div class="card loading" role="status">Loading…</div></div>';
  }
  function failure(title, message) {
    view.innerHTML = '<div class="view">' + header(title, "", null) +
      '<div class="notice notice-error" role="alert" style="animation:none">' + icon("info", 18) + "<span>" + esc(message) + "</span></div></div>";
  }

  // ---------- dates (the server sends ISO times; we show them in the viewer's own time zone) ----------
  function dateShort(iso) {
    return iso ? new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : "—";
  }
  function dateTime(iso) {
    return iso ? new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false }) : "—";
  }
  function ago(iso) {
    if (!iso) return "never";
    var s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
    if (s < 60) return "just now";
    if (s < 3600) return Math.floor(s / 60) + " min ago";
    if (s < 86400) return Math.floor(s / 3600) + " h ago";
    if (s < 172800) return "yesterday";
    if (s < 30 * 86400) return Math.floor(s / 86400) + " days ago";
    return dateShort(iso);
  }

  // ---------- talking to the backend ----------
  /** Resolves { ok, data, error }. Sends the signed-in admin's token; a rejected token signs you out. */
  function api(method, path, body) {
    return window.HiriqAuth.api(method, path, body).then(function (r) {
      if (!r.ok && (r.status === 401 || r.code === "not_signed_in")) { window.HiriqAuth.logout(); }
      return r;
    });
  }

  /* Vertical bar chart. Hover a bar to read its value; one series, so no legend. */
  function barChart(id, values, labels, opts) {
    opts = opts || {};
    var max = Math.max(1, Math.max.apply(null, values));
    var total = values.reduce(function (a, b) { return a + b; }, 0);
    var h = opts.height || 200;
    var bars = values.map(function (v, i) {
      return '<div class="b" data-i="' + i + '" role="img" aria-label="' + esc(labels[i]) + ": " + fmt(v) +
        '" style="height:' + Math.max(4, Math.round((v / max) * (h - 20))) + "px;background:" + (opts.color || "rgb(var(--a2))") +
        ";animation-delay:" + (i * (0.5 / values.length)).toFixed(3) + 's"></div>';
    }).join("");
    return (
      '<div class="barchart" data-chart="' + id + '">' +
      '<div class="chart-read" aria-live="polite"><span class="mono" data-read-value>' + fmt(total) + '</span><span data-read-label>' + esc(opts.totalLabel || "Total") + "</span></div>" +
      '<div class="bars' + (values.length > 20 ? " dense" : "") + '" style="height:' + h + 'px">' + bars + "</div>" +
      '<div class="axis"><span>' + esc(labels[0]) + "</span><span>" + esc(labels[labels.length - 1]) + "</span></div></div>"
    );
  }
  function wireBarChart(id, values, labels, totalLabel) {
    var root = view.querySelector('[data-chart="' + id + '"]');
    if (!root) return;
    var barsEl = root.querySelector(".bars");
    var valEl = root.querySelector("[data-read-value]");
    var labEl = root.querySelector("[data-read-label]");
    var total = values.reduce(function (a, b) { return a + b; }, 0);
    barsEl.addEventListener("mouseover", function (e) {
      var b = e.target.closest(".b");
      if (!b) return;
      var i = +b.getAttribute("data-i");
      barsEl.classList.add("hovering");
      barsEl.querySelectorAll(".b").forEach(function (x) { x.classList.toggle("on", x === b); });
      valEl.textContent = fmt(values[i]);
      labEl.textContent = labels[i];
    });
    barsEl.addEventListener("mouseleave", function () {
      barsEl.classList.remove("hovering");
      valEl.textContent = fmt(total);
      labEl.textContent = totalLabel;
    });
  }

  // A newer navigation cancels slower responses from an older one.
  var navId = 0;

  // =====================================================
  // OVERVIEW
  // =====================================================
  var overviewRange = "7d";
  function renderOverview() {
    var mine = ++navId;
    loading("Overview");
    var tz = -new Date().getTimezoneOffset(); // minutes ahead of UTC, so sign-ups land on your local day
    api("GET", "/api/admin/overview?range=" + overviewRange + "&tz=" + tz).then(function (r) {
      if (mine !== navId) return;
      if (!r.ok) { failure("Overview", r.error); return; }
      drawOverview(r.data);
    });
  }

  function drawOverview(D) {
    setRole(D.you_are_superadmin);
    var up = D.signups;
    var kpiColors = ["a1", "a2", "a3", "a4"];
    var ranges = [["7d", "7 days"], ["30d", "30 days"], ["90d", "90 days"]].map(function (r) {
      return '<button type="button" data-range="' + r[0] + '" aria-pressed="' + (r[0] === overviewRange) + '">' + r[1] + "</button>";
    }).join("");

    var kpis = D.kpis.map(function (k, i) {
      var delta = k.delta
        ? '<div class="kpi-delta"><span class="' + (k.up ? "up" : "down") + '">' + (k.up ? "▲ " : "▼ ") + esc(k.delta) + "</span>" +
          (k.delta.indexOf("new") < 0 ? ' <span class="faint">vs previous period</span>' : "") + "</div>"
        : '<div class="kpi-delta"><span class="faint">&nbsp;</span></div>';
      return (
        '<div class="card kpi" style="animation-delay:' + i * 0.08 + 's">' +
        '<div class="kpi-top"><span>' + esc(k.label) + '</span><span class="kpi-icon"><span class="bg-' + kpiColors[i] + '" style="color:rgb(var(--' + kpiColors[i] + '))"></span></span></div>' +
        '<div class="kpi-value">' + fmt(k.value) + "</div>" + delta + "</div>"
      );
    }).join("");

    var maxRole = Math.max(1, Math.max.apply(null, D.roles.map(function (r) { return r[1]; })));
    var roles = D.roles.map(function (r, i) {
      return meter(r[0], '<span class="mono">' + fmt(r[1]) + "</span>", (r[1] / maxRole) * 100, "", 0.1 + i * 0.12);
    }).join("");
    var health = D.health.map(function (h) {
      return '<div class="health-row">' + statusBadge(h[1]) + "<span>" + esc(h[0]) + "</span><span>" + esc(h[2]) + "</span></div>";
    }).join("");
    var activity = D.activity.length
      ? D.activity.map(function (a, i) {
        return '<div class="activity" style="animation-delay:' + i * 0.08 + 's"><span class="dot bg-' + a.tone + '" style="color:rgb(var(--' + a.tone + '))"></span>' +
          "<span>" + esc(a.text) + "<small>" + esc(ago(a.at)) + "</small></span></div>";
      }).join("")
      : '<p class="empty">No activity yet.</p>';

    view.innerHTML =
      '<div class="view">' +
      header("Overview", '<div class="range" role="group" aria-label="Date range">' + ranges + "</div>") +
      '<div class="grid-auto">' + kpis + "</div>" +
      '<div class="row">' +
        '<div class="glow-border grow-2" style="--r:22px"><div class="glow-inner card-stack" style="padding:22px">' +
          '<div class="stack-2"><h2 class="card-title">New sign-ups</h2><span class="card-sub">' + esc(up.sub) + "</span></div>" +
          barChart("signups", up.values, up.labels, { totalLabel: "Total for the period" }) +
        "</div></div>" +
        '<div class="card card-stack grow-1">' +
          '<div class="stack-2"><h2 class="card-title">Users by role</h2><span class="card-sub">All accounts</span></div>' + roles +
          '<div class="health"><span class="muted" style="font-size:13px;font-weight:600">System health</span>' + health + "</div>" +
        "</div>" +
      "</div>" +
      '<div class="row">' +
        '<div class="card card-stack grow-1"><div class="row-between"><h2 class="card-title">Recent activity</h2><a class="faint" style="font-size:13px" href="#audit">See full audit log</a></div>' + activity + "</div>" +
      "</div></div>";

    view.querySelectorAll("[data-range]").forEach(function (b) {
      b.addEventListener("click", function () { overviewRange = b.getAttribute("data-range"); renderOverview(); });
    });
    wireBarChart("signups", up.values, up.labels, "Total for the period");
  }

  // =====================================================
  // USERS & ROLES (real accounts)
  // =====================================================
  var users = [];
  var plans = [];
  var iAmSuper = false;
  var usersToast = null; // { kind: "good" | "error", text }
  var userQuery = "";
  var userFilter = "all";
  var armedDelete = null; // id of the row waiting for a second click
  var armedTimer = null;
  var AVATAR = ["a1", "a2", "a3", "a4"];
  var STATUS_DOT = { Active: "rgb(var(--a4))", Suspended: "rgb(var(--bad))", Invited: "rgb(var(--warn))" };
  function avatarClass(u) { return "bg-" + AVATAR[(u.name.charCodeAt(0) || 0) % 4]; }
  function byId(id) { return users.find(function (x) { return x.id === id; }); }

  function renderUsers() {
    var mine = ++navId;
    loading("Users & roles");
    api("GET", "/api/admin/users").then(function (r) {
      if (mine !== navId) return;
      if (!r.ok) { failure("Users & roles", r.error); return; }
      users = r.data.users;
      plans = r.data.plans;
      iAmSuper = r.data.you_are_superadmin;
      setRole(iAmSuper);
      drawUsers();
    });
  }

  function drawUsers() {
    view.innerHTML =
      '<div class="view">' + header("Users & roles") +
      '<div class="grid-auto" style="--min:180px" id="plans"></div>' +
      '<div class="toolbar">' +
        '<div class="search">' + icon("search", 18) + '<label class="sr-only" for="usearch">Search users</label>' +
        '<input class="field field-sm" id="usearch" type="search" placeholder="Search name, email, username, phone or company" value="' + esc(userQuery) + '"></div>' +
        '<div class="filters" role="group" aria-label="Filter by role" id="role-filters"></div>' +
      "</div>" +
      '<div id="toast"></div>' +
      '<div class="card table-card"><div class="table-scroll"><table style="min-width:960px">' +
        "<thead><tr><th>User and mobile</th><th>Designation and company</th><th>Role</th><th>Plan</th><th>Status</th><th>Activity</th><th class=\"right\">Actions</th></tr></thead>" +
        '<tbody id="user-rows"></tbody></table></div><p class="empty" id="no-users" hidden>No users match this search.</p></div>' +
      '<p class="faint" style="font-size:13px">Everyone is on the Free plan for now. Basic, Pro and Premium unlock here once paid plans launch. ' +
      "Your own account is locked so you cannot remove or suspend yourself" +
      (iAmSuper ? "." : ", and only a superadmin can change another admin.") +
      " To add another admin, have them sign up first, then set their role to Admin.</p>" +
      "</div>";

    $("#usearch").addEventListener("input", function (e) { userQuery = e.target.value; renderUserRows(); });
    drawUsersDynamic();

    // One delegated listener for the table's controls
    var tbody = $("#user-rows");
    tbody.addEventListener("change", function (e) {
      var el = e.target;
      var id = el.getAttribute("data-id");
      var u = byId(id);
      if (!u) return;
      if (el.matches("[data-field=role]")) {
        change(u, { role: el.value }, u.name + " is now " + el.value + ".");
      } else if (el.matches("[data-field=plan]")) {
        change(u, { plan: el.value }, u.name + " is on the " + el.value + " plan.");
      }
    });
    tbody.addEventListener("click", function (e) {
      var btn = e.target.closest("button[data-act]");
      if (!btn) return;
      var id = btn.getAttribute("data-id");
      var u = byId(id);
      if (!u) return;
      var act = btn.getAttribute("data-act");
      if (act === "toggle") {
        var suspending = u.status !== "Suspended";
        change(u, { status: suspending ? "suspended" : "active" }, u.name + (suspending ? " was suspended." : " was reactivated."));
      } else if (act === "delete") {
        armedDelete = id;
        clearTimeout(armedTimer);
        armedTimer = setTimeout(function () { armedDelete = null; renderUserRows(); }, 4000);
        renderUserRows();
      } else if (act === "confirm-delete") {
        clearTimeout(armedTimer);
        armedDelete = null;
        remove(u);
      }
    });
  }

  function say(kind, text) { usersToast = { kind: kind, text: text }; drawUsersDynamic(); }

  function change(u, patch, okText) {
    api("PATCH", "/api/admin/users/" + u.id, patch).then(function (r) {
      if (!r.ok) { say("error", r.error); return; }
      users = users.map(function (x) { return x.id === u.id ? r.data : x; });
      say("good", okText);
    });
  }
  function remove(u) {
    api("DELETE", "/api/admin/users/" + u.id).then(function (r) {
      if (!r.ok) { say("error", r.error); return; }
      users = users.filter(function (x) { return x.id !== u.id; });
      say("good", u.name + " was deleted. This cannot be undone.");
    });
  }

  function drawUsersDynamic() {
    var live = plans.filter(function (p) { return p.live; }).map(function (p) { return p.id; });
    $("#plans").innerHTML = plans.map(function (p) {
      var n = users.filter(function (u) { return u.plan === p.id; }).length;
      return '<div class="plan' + (p.live ? " live" : "") + '"><div class="row-between"><span class="plan-name">' + esc(p.name) + '</span><span class="plan-badge">' + (p.live ? "Live" : "Soon") + "</span></div>" +
        '<span class="mono" style="font-size:24px">' + fmt(n) + '</span><span class="faint" style="font-size:13px">' + (p.live ? "Accounts on this plan" : "Paid plan, not launched") + "</span></div>";
    }).join("");
    var counts = { all: users.length, candidate: 0, recruiter: 0, admin: 0 };
    users.forEach(function (u) { counts[u.role]++; });
    $("#role-filters").innerHTML = [["all", "All"], ["candidate", "Candidates"], ["recruiter", "Recruiters"], ["admin", "Admins"]].map(function (f) {
      return '<button type="button" class="filter-pill" data-filter="' + f[0] + '" aria-pressed="' + (userFilter === f[0]) + '">' + f[1] + ' <span class="mono" style="opacity:.7">' + counts[f[0]] + "</span></button>";
    }).join("");
    view.querySelectorAll("[data-filter]").forEach(function (b) {
      b.addEventListener("click", function () { userFilter = b.getAttribute("data-filter"); drawUsersDynamic(); });
    });
    $("#toast").innerHTML = usersToast
      ? '<div class="toast' + (usersToast.kind === "error" ? " toast-error" : "") + '" role="' + (usersToast.kind === "error" ? "alert" : "status") + '">' +
        icon(usersToast.kind === "error" ? "info" : "check", 18) + "<span>" + esc(usersToast.text) + "</span></div>"
      : "";
    renderUserRows();
  }

  function renderUserRows() {
    var q = userQuery.toLowerCase();
    var shown = users.filter(function (u) {
      var hay = (u.name + " " + u.email + " " + (u.username || "") + " " + (u.phone || "") + " " + (u.company || "") + " " + (u.designation || "")).toLowerCase();
      return (userFilter === "all" || u.role === userFilter) && (!q || hay.indexOf(q) >= 0);
    });
    $("#user-rows").innerHTML = shown.map(function (u) {
      var dis = u.locked ? " disabled" : "";
      var roleOpts = ["candidate", "recruiter", "admin"].map(function (r) {
        var blocked = r === "admin" && !iAmSuper && u.role !== "admin";
        return '<option value="' + r + '"' + (u.role === r ? " selected" : "") + (blocked ? " disabled" : "") + ">" + r.charAt(0).toUpperCase() + r.slice(1) + "</option>";
      }).join("");
      var planOpts = plans.map(function (p) {
        return '<option value="' + esc(p.id) + '"' + (u.plan === p.id ? " selected" : "") + (p.live ? "" : " disabled") + ">" + esc(p.name) + (p.live ? "" : " (soon)") + "</option>";
      }).join("");
      var toggleLabel = (u.status === "Suspended" ? "Reactivate " : "Suspend ") + u.name;
      var del = armedDelete === u.id
        ? '<button type="button" class="btn-danger" data-act="confirm-delete" data-id="' + esc(u.id) + '">Delete for good?</button>'
        : '<button type="button" class="icon-btn" data-act="delete" data-id="' + esc(u.id) + '" aria-label="Delete ' + esc(u.name) + '" title="Delete ' + esc(u.name) + '"' + dis + ">" + icon("trash", 16, "trash") + "</button>";
      return (
        "<tr>" +
        '<td><div class="who"><span class="avatar sm ' + avatarClass(u) + '">' + esc(u.name.charAt(0).toUpperCase()) + "</span>" +
          '<span class="cell-stack"><strong>' + esc(u.name) + (u.you ? ' <span class="faint">(you)</span>' : "") + "</strong><small>" + esc(u.email) + "</small>" +
          (u.username ? '<small class="mono" style="color:rgb(var(--ink)/.8)">@' + esc(u.username) + "</small>" : "") +
          '<small class="mono" style="color:rgb(var(--ink)/.8)">' + esc(u.phone || "—") + "</small></span></div></td>" +
        '<td><span class="cell-stack"><span>' + esc(u.designation || "—") + "</span><small>" + esc(u.company || "—") + "</small></span></td>" +
        '<td><select class="field" style="width:124px" data-field="role" data-id="' + esc(u.id) + '" aria-label="Role for ' + esc(u.name) + '"' + dis + ">" + roleOpts + "</select></td>" +
        '<td><select class="field" style="width:132px" data-field="plan" data-id="' + esc(u.id) + '" aria-label="Plan for ' + esc(u.name) + '"' + dis + ">" + planOpts + "</select></td>" +
        '<td><span class="chip chip-neutral"><span class="dot" style="background:' + (STATUS_DOT[u.status] || "rgb(255 255 255 / .35)") + '"></span>' + esc(u.status) + "</span></td>" +
        '<td class="nowrap"><span class="cell-stack"><span>' + (u.last ? "Active " + esc(ago(u.last)) : "Never signed in") + "</span><small>Joined " + esc(dateShort(u.joined)) + "</small></span></td>" +
        '<td><div class="actions">' +
          '<button type="button" class="icon-btn" data-act="toggle" data-id="' + esc(u.id) + '" aria-label="' + esc(toggleLabel) + '" title="' + esc(toggleLabel) + '"' + dis + ">" + icon("ban", 16) + "</button>" +
          del +
        "</div></td></tr>"
      );
    }).join("");
    $("#no-users").hidden = shown.length > 0;
  }

  // =====================================================
  // JOBS & MODEL QUALITY: nothing real to show yet
  // =====================================================
  function renderNotBuilt(title, text) {
    ++navId;
    view.innerHTML = '<div class="view">' + header(title, "", false) +
      '<div class="card card-stack" style="gap:10px"><h2 class="card-title">Nothing to show yet</h2><p class="muted" style="margin:0;max-width:62ch">' + esc(text) + "</p></div></div>";
  }
  function renderJobs() {
    renderNotBuilt("Jobs & sources", "Job ingestion starts with the job-recommendation step. Until postings are stored there are no sources, counts or searches to show, and this page will not show made-up numbers.");
  }
  function renderModel() {
    renderNotBuilt("Model quality", "Ranking quality needs a labeled set of resume and job pairs to measure against (see ml/README.md). Once the matcher exists and is evaluated, its real scores will appear here.");
  }

  // =====================================================
  // AUDIT LOG (real events)
  // =====================================================
  var auditFilter = "all";
  var TAG = { Auth: "a2", Users: "a3", Model: "a1", Data: "a4" };
  function renderAudit() {
    var mine = ++navId;
    loading("Audit log");
    api("GET", "/api/admin/audit?limit=200&category=" + encodeURIComponent(auditFilter)).then(function (r) {
      if (mine !== navId) return;
      if (!r.ok) { failure("Audit log", r.error); return; }
      var filters = [["all", "All"], ["Auth", "Sign-ins"], ["Users", "Users"], ["Model", "Model"], ["Data", "Data"]].map(function (f) {
        return '<button type="button" class="filter-pill" data-af="' + f[0] + '" aria-pressed="' + (auditFilter === f[0]) + '">' + f[1] + "</button>";
      }).join("");
      var rows = r.data.events.map(function (e, i) {
        return '<div class="audit-row" style="animation-delay:' + Math.min(i, 20) * 0.03 + 's"><span class="mono">' + esc(dateTime(e.at)) + '</span><span class="audit-tag" style="border-color:rgb(var(--' + (TAG[e.category] || "a1") + '))">' + esc(e.category) +
          "</span><span><strong>" + esc(e.actor) + "</strong> " + esc(e.action) + "</span></div>";
      }).join("");
      view.innerHTML = '<div class="view">' + header("Audit log") + '<div class="filters" role="group" aria-label="Filter by event type">' + filters + "</div>" +
        '<div class="card" style="padding:8px 0">' + (rows || '<p class="empty">No events yet.</p>') + "</div></div>";
      view.querySelectorAll("[data-af]").forEach(function (b) {
        b.addEventListener("click", function () { auditFilter = b.getAttribute("data-af"); renderAudit(); });
      });
    });
  }

  // =====================================================
  // Router
  // =====================================================
  var VIEWS = { overview: [renderOverview, "Overview"], users: [renderUsers, "Users & roles"], jobs: [renderJobs, "Jobs & sources"], model: [renderModel, "Model quality"], audit: [renderAudit, "Audit log"] };
  function route() {
    var key = (location.hash || "#overview").slice(1);
    if (!VIEWS[key]) key = "overview";
    document.querySelectorAll(".side-nav a").forEach(function (a) {
      if (a.getAttribute("href") === "#" + key) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    });
    document.title = VIEWS[key][1] + " · Hiriq admin";
    VIEWS[key][0]();
    window.scrollTo(0, 0);
  }

  function setRole(isSuper) {
    var el = document.getElementById("me-role");
    if (el) el.textContent = isSuper ? "Super admin" : "Admin";
  }

  document.getElementById("logout").addEventListener("click", function () { window.HiriqAuth.logout(); });
  if (session) {
    document.getElementById("me-name").textContent = session.user;
    document.querySelector(".me .avatar").textContent = String(session.user || "A").charAt(0).toUpperCase();
  }

  window.addEventListener("hashchange", route);
  if (cfg.mode !== "api") {
    failure("Overview", 'The admin console shows live data, so it needs the backend. Start it and set mode to "api" in assets/js/config.js, then log in again.');
  } else {
    route();
  }
})();
