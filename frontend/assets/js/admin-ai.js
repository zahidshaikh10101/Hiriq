/* Hiriq — admin console: AI usage (reads /api/admin/ai-usage, which reads the ai_calls log).
   A factory: admin.js calls window.HiriqAdminAI(helpers) and gets { show() } back.
   A "call" here is one model ATTEMPT: a retry, or the backup model after a failure, is its own row, so the numbers show how
   often the free models misbehave, not just how often a feature was used. No prompts or resume text are stored, so none can be shown.
   Below the model numbers sits the RapidAPI panel: requests to the outside job feed (Indeed), from the external_calls log. */
window.HiriqAdminAI = function (H) {
  var view = H.view, esc = H.esc, fmt = H.fmt, icon = H.icon, api = H.api;
  var range = "7d";

  function pct(n) { return n == null ? "—" : n + "%"; }
  function secs(ms) { return ms == null ? "—" : (ms < 1000 ? ms + " ms" : (ms / 1000).toFixed(1) + " s"); }
  function tone(rate) { return rate == null ? "" : rate >= 90 ? "up" : rate >= 60 ? "" : "down"; }
  function short(model) { return String(model || "").replace(/:free$/, ""); }

  function kpi(label, value, sub, i) {
    var colors = ["a1", "a2", "a3", "a4"];
    return '<div class="card kpi" style="animation-delay:' + i * 0.08 + 's"><div class="kpi-top"><span>' + esc(label) + '</span><span class="kpi-icon"><span class="bg-' + colors[i] +
      '" style="color:rgb(var(--' + colors[i] + '))"></span></span></div><div class="kpi-value">' + value + '</div><div class="kpi-delta">' + (sub || '<span class="faint">&nbsp;</span>') + "</div></div>";
  }

  function show() {
    var mine = H.next();
    H.loading("AI usage");
    var tz = -new Date().getTimezoneOffset();
    api("GET", "/api/admin/ai-usage?range=" + range + "&tz=" + tz).then(function (r) {
      if (!H.current(mine)) return;
      if (!r.ok) { H.failure("AI usage", r.error); return; }
      draw(r.data);
    });
  }

  function draw(D) {
    var t = D.totals;
    var ranges = [["7d", "7 days"], ["30d", "30 days"], ["90d", "90 days"]].map(function (x) {
      return '<button type="button" data-range="' + x[0] + '" aria-pressed="' + (x[0] === range) + '">' + x[1] + "</button>";
    }).join("");

    var diff = t.calls - t.previous_calls;
    var vs = t.previous_calls || t.calls ? '<span class="' + (diff >= 0 ? "up" : "down") + '">' + (diff === 0 ? "no change" : (diff > 0 ? "▲ +" : "▼ −") + Math.abs(diff)) + '</span> <span class="faint">vs previous period</span>' : "";
    var kpis = [
      kpi("Model attempts", fmt(t.calls), vs, 0),
      kpi("Succeeded", t.success_rate == null ? "—" : t.success_rate + "%", t.calls ? '<span class="' + tone(t.success_rate) + '">' + fmt(t.failed) + " failed</span>" : "", 1),
      kpi("Average speed", secs(t.avg_latency_ms), '<span class="faint">per attempt</span>', 2),
      kpi("Tokens used", fmt(t.prompt_tokens + t.completion_tokens), '<span class="faint">' + fmt(t.prompt_tokens) + " in · " + fmt(t.completion_tokens) + " out</span>", 3)
    ].join("");

    var maxP = Math.max(1, Math.max.apply(null, D.by_purpose.map(function (p) { return p.calls; }).concat([1])));
    var features = D.by_purpose.length ? D.by_purpose.map(function (p, i) {
      return H.meter(p.label, '<span class="mono">' + fmt(p.calls) + '</span> <span class="' + tone(p.success_rate) + '">' + pct(p.success_rate) + " ok</span> <span class=\"faint\">" + secs(p.avg_latency_ms) + "</span>",
        (p.calls / maxP) * 100, p.success_rate != null && p.success_rate < 60 ? "bad" : "", 0.1 + i * 0.1);
    }).join("") : '<p class="empty">No AI calls in this period.</p>';

    var models = D.by_model.length ? '<div class="table-scroll"><table style="min-width:420px"><thead><tr><th>Model</th><th class="right">Attempts</th><th class="right">OK</th><th class="right">Speed</th></tr></thead><tbody>' +
      D.by_model.map(function (m) {
        return "<tr><td><span class=\"mono\" style=\"font-size:13px\">" + esc(short(m.model)) + "</span></td><td class=\"right mono\">" + fmt(m.calls) + '</td><td class="right ' + tone(m.success_rate) + '">' + pct(m.success_rate) +
          '</td><td class="right mono">' + secs(m.avg_latency_ms) + "</td></tr>";
      }).join("") + "</tbody></table></div>" : '<p class="empty">No models used yet.</p>';

    var errors = D.errors.length ? D.errors.map(function (e) {
      return '<div class="health-row"><span class="status-badge status-warn" aria-hidden="true">!</span><span>' + esc(e.reason) + '</span><span class="mono">' + fmt(e.count) + "</span></div>";
    }).join("") : '<p class="empty">No failures. Nice.</p>';

    var recent = D.recent_failures.length ? D.recent_failures.map(function (f) {
      return '<div class="activity"><span class="dot bg-a3" style="color:rgb(var(--a3))"></span><span>' + esc(f.purpose) + " · " + esc(short(f.model)) + ": " + esc(f.error) + "<small>" + esc(H.ago(f.at)) + "</small></span></div>";
    }).join("") : '<p class="empty">Nothing has failed in this period.</p>';

    var users = D.top_users.length ? D.top_users.map(function (u, i) {
      return H.meter(u.name, '<span class="mono">' + fmt(u.calls) + "</span>", (u.calls / Math.max(1, D.top_users[0].calls)) * 100, "", 0.1 + i * 0.1);
    }).join("") : '<p class="empty">No usage yet.</p>';

    var keyNote = D.key_set ? "" : '<div class="notice notice-warn" role="status">' + icon("warn", 18) + "<span>No OPENROUTER_API_KEY is set on the server, so every AI feature is switched off. Add it to backend/.env and restart.</span></div>";

    view.innerHTML = '<div class="view">' + H.header("AI usage", '<div class="range" role="group" aria-label="Date range">' + ranges + "</div>" + H.pdfBtn()) + keyNote +
      '<div class="grid-auto">' + kpis + "</div>" +
      '<div class="row">' +
        '<div class="glow-border grow-2" style="--r:22px"><div class="glow-inner card-stack" style="padding:22px">' +
          '<div class="stack-2"><h2 class="card-title">Model attempts</h2><span class="card-sub">' + esc(D.daily.sub) + "</span></div>" +
          H.barChart("ai", D.daily.values, D.daily.labels, { totalLabel: "Total for the period" }) +
          '<p class="hint" style="margin:0">' + fmt(D.daily.failed.reduce(function (a, b) { return a + b; }, 0)) + " of these attempts failed. A retry, or the backup model after a failure, counts as its own attempt.</p>" +
        "</div></div>" +
        '<div class="card card-stack grow-1"><div class="stack-2"><h2 class="card-title">By feature</h2><span class="card-sub">Attempts, success rate, average speed</span></div>' + features + "</div>" +
      "</div>" +
      '<div class="row">' +
        '<div class="card card-stack grow-2"><div class="stack-2"><h2 class="card-title">By model</h2><span class="card-sub">Free models come and go; a low success rate here is the sign to change LLM_MODELS in .env</span></div>' + models + "</div>" +
        '<div class="card card-stack grow-1"><div class="stack-2"><h2 class="card-title">Why attempts fail</h2></div>' + errors + "</div>" +
      "</div>" +
      '<div class="row">' +
        '<div class="card card-stack grow-2"><div class="stack-2"><h2 class="card-title">Latest failures</h2><span class="card-sub">Short reasons only. Prompts and resume text are never stored.</span></div>' + recent + "</div>" +
        '<div class="card card-stack grow-1"><div class="stack-2"><h2 class="card-title">Most active recruiters</h2><span class="card-sub">' + fmt(t.users) + " in this period</span></div>" + users + "</div>" +
      "</div>" + rapidHtml(D.rapidapi) + "</div>";

    view.querySelectorAll("[data-range]").forEach(function (b) {
      b.addEventListener("click", function () { range = b.getAttribute("data-range"); show(); });
    });
    H.wireBarChart("ai", D.daily.values, D.daily.labels, "Total for the period");
    H.wireBarChart("rapi", D.rapidapi.daily.values, D.rapidapi.daily.labels, "Total for the period");
    H.wirePdf("hiriq-ai-usage-" + range + ".pdf", function () { return pdfSpec(D); });
  }

  // ---------- RapidAPI (the outside job feed) ----------
  function rapidHtml(R) {
    var diff = R.calls - R.previous_calls;
    var vs = R.previous_calls || R.calls ? '<span class="' + (diff >= 0 ? "up" : "down") + '">' + (diff === 0 ? "no change" : (diff > 0 ? "▲ +" : "▼ −") + Math.abs(diff)) + '</span> <span class="faint">vs previous period</span>' : "";
    var usedPct = R.daily_cap ? Math.min(100, Math.round((R.used_today / R.daily_cap) * 100)) : 0;
    var kpis = [
      kpi("Requests", fmt(R.calls), vs, 0),
      kpi("Succeeded", R.success_rate == null ? "—" : R.success_rate + "%", R.calls ? '<span class="' + tone(R.success_rate) + '">' + fmt(R.failed) + " failed</span>" : "", 1),
      kpi("Average speed", secs(R.avg_latency_ms), '<span class="faint">' + fmt(R.posts) + " posts returned</span>", 2),
      kpi("Today's searches", fmt(R.used_today) + ' <span class="faint" style="font-size:15px">/ ' + fmt(R.daily_cap) + "</span>", '<span class="' + (usedPct >= 90 ? "down" : "faint") + '">' + usedPct + "% of the daily cap</span>", 3)
    ].join("");
    var errors = R.errors.length ? R.errors.map(function (e) {
      return '<div class="health-row"><span class="status-badge status-warn" aria-hidden="true">!</span><span>' + esc(e.reason) + '</span><span class="mono">' + fmt(e.count) + "</span></div>";
    }).join("") : '<p class="empty">No failed requests.</p>';
    var recent = R.recent_failures.length ? R.recent_failures.map(function (f) {
      return '<div class="activity"><span class="dot bg-a3" style="color:rgb(var(--a3))"></span><span>' + esc(f.error) + "<small>" + esc(H.ago(f.at)) + "</small></span></div>";
    }).join("") : '<p class="empty">Nothing has failed in this period.</p>';
    var note = R.configured ? "" : '<div class="notice notice-warn" role="status">' + icon("warn", 18) + "<span>No RAPIDAPI_KEY is set on the server, so outside job search is switched off. Add it to backend/.env and restart.</span></div>";
    return (
      '<div class="stack-2" style="padding:18px 4px 0"><h2 class="card-title" style="font-size:22px">RapidAPI usage</h2>' +
      '<span class="card-sub">Outside job feed: ' + esc(R.host) + " · country " + esc(R.country) + ". Only requests that reach RapidAPI count; repeat searches served from the 15-minute cache do not.</span></div>" + note +
      '<div class="grid-auto">' + kpis + "</div>" +
      '<div class="row">' +
        '<div class="glow-border grow-2" style="--r:22px"><div class="glow-inner card-stack" style="padding:22px">' +
          '<div class="stack-2"><h2 class="card-title">Requests</h2><span class="card-sub">Same period as above</span></div>' +
          H.barChart("rapi", R.daily.values, R.daily.labels, { totalLabel: "Total for the period", color: "rgb(var(--a3))" }) +
        "</div></div>" +
        '<div class="card card-stack grow-1"><div class="stack-2"><h2 class="card-title">Why requests fail</h2></div>' + errors + "</div>" +
      "</div>" +
      '<div class="card card-stack"><div class="stack-2"><h2 class="card-title">Latest failed requests</h2></div>' + recent + "</div>"
    );
  }

  // ---------- PDF ----------
  function pdfSpec(D) {
    var t = D.totals, R = D.rapidapi;
    var span = { "7d": "Last 7 days", "30d": "Last 30 days", "90d": "Last 90 days" }[D.range];
    return {
      title: "AI usage", subtitle: span + "  |  language models and the outside job feed (RapidAPI)",
      blocks: [
        { type: "heading", text: "Language models (OpenRouter)" },
        { type: "kpis", items: [["Model attempts", fmt(t.calls), "vs " + fmt(t.previous_calls) + " before"], ["Succeeded", pct(t.success_rate), fmt(t.failed) + " failed"],
          ["Average speed", secs(t.avg_latency_ms), "per attempt"], ["Tokens used", fmt(t.prompt_tokens + t.completion_tokens), fmt(t.prompt_tokens) + " in / " + fmt(t.completion_tokens) + " out"]] },
        { type: "heading", text: "By feature" },
        { type: "table", head: ["Feature", "Attempts", "Success", "Failed", "Speed"], widths: [3, 1, 1, 1, 1], align: ["l", "r", "r", "r", "r"],
          rows: D.by_purpose.map(function (p) { return [p.label, fmt(p.calls), pct(p.success_rate), fmt(p.failed), secs(p.avg_latency_ms)]; }) },
        { type: "heading", text: "By model" },
        { type: "table", head: ["Model", "Attempts", "Success", "Speed"], widths: [4, 1, 1, 1], align: ["l", "r", "r", "r"],
          rows: D.by_model.map(function (m) { return [short(m.model), fmt(m.calls), pct(m.success_rate), secs(m.avg_latency_ms)]; }) },
        { type: "heading", text: "Why attempts fail" },
        { type: "table", head: ["Reason", "Count"], widths: [5, 1], align: ["l", "r"], rows: D.errors.map(function (e) { return [e.reason, fmt(e.count)]; }) },
        { type: "heading", text: "Most active recruiters" },
        { type: "table", head: ["Recruiter", "Attempts"], widths: [5, 1], align: ["l", "r"], rows: D.top_users.map(function (u) { return [u.name, fmt(u.calls)]; }) },
        { type: "heading", text: "RapidAPI (outside job feed)" },
        { type: "kpis", items: [["Requests", fmt(R.calls), "vs " + fmt(R.previous_calls) + " before"], ["Succeeded", pct(R.success_rate), fmt(R.failed) + " failed"],
          ["Average speed", secs(R.avg_latency_ms), fmt(R.posts) + " posts returned"], ["Today's searches", fmt(R.used_today) + " / " + fmt(R.daily_cap), "daily cap"]] },
        { type: "table", head: ["Period", "Requests", "Failed"], widths: [3, 1, 1], align: ["l", "r", "r"],
          rows: R.daily.labels.map(function (l, i) { return [l, fmt(R.daily.values[i]), fmt(R.daily.failed[i])]; }) },
        { type: "heading", text: "Why RapidAPI requests fail" },
        { type: "table", head: ["Reason", "Count"], widths: [5, 1], align: ["l", "r"], rows: R.errors.map(function (e) { return [e.reason, fmt(e.count)]; }) }
      ]
    };
  }

  return { show: show };
};
