/* Hiriq — recruiter: Ask the pool (a plain-English question about your candidates, answered from their resumes).
   A factory: recruiter.js calls window.HiriqAsk(helpers) and gets { show() } back.
   The answer is short and cites people by name (a link to their profile) with the resume line that backs it up. Quotes the
   server could not find in the resume are never shown as quotes. Under every answer the keyword matches are listed, so if
   the AI is unavailable the page still works as a search. Nothing is saved: the conversation lives in this tab only. */
window.HiriqAsk = function (R) {
  var view = R.view, esc = R.esc, icon = R.icon, api = R.api;

  var EXAMPLES = [
    "Who has built Power BI dashboards?",
    "Which candidates have worked with Airflow or dbt?",
    "Who has fintech or banking experience?",
    "Anyone who has led a team of analysts?"
  ];
  var SOURCES = [["all", "Everyone I can see"], ["upload", "Resumes I uploaded"], ["platform", "Hiriq members"]];

  // The conversation outlives route changes inside the page: coming back to Ask shows it again.
  var feed = [];       // newest first: { q, source, state: "asking"|"done"|"error", data, error }
  var draft = { q: "", source: "all" };

  function say(r, fallback) {
    var d = r.data && r.data.detail;
    if (Array.isArray(d) && d.length) return d.slice(0, 2).map(function (e) { return String(e.msg || "").replace(/^Value error, /, ""); }).join(" ");
    return (d && d.message) || r.error || fallback || "Something went wrong. Try again.";
  }
  function link(id, text) { return '<a class="ask-ref" href="#candidates/' + encodeURIComponent(id) + '">' + esc(text) + "</a>"; }

  // ---------- one answer ----------
  function answerHtml(item) {
    var d = item.data, byRef = {};
    (d.sources || []).forEach(function (s) { byRef[s.ref] = s; });
    var text = esc(d.answer || "").replace(/\[(C\d+)\]/g, function (m, ref) { return byRef[ref] ? link(byRef[ref].candidate_id, byRef[ref].name) : ""; });
    var out = "";
    if (d.answer) {
      out += '<p class="ask-answer">' + text + "</p>";
      if ((d.sources || []).length) {
        out += '<ul class="ask-sources">' + d.sources.map(function (s) {
          return "<li>" + link(s.candidate_id, s.name) + (s.headline ? ' <small class="faint">' + esc(s.headline) + "</small>" : "") +
            (s.quote ? '<span class="ask-quote">“' + esc(s.quote) + "”</span>" : '<span class="ask-quote none">No exact resume line could be confirmed for this one.</span>') + "</li>";
        }).join("") + "</ul>";
      }
      if (d.stats && d.stats.unverified) out += '<p class="hint">' + d.stats.unverified + " quoted line" + (d.stats.unverified === 1 ? " was" : "s were") + " left out because it is not in the resume.</p>";
    }
    if (d.ai_error) {
      out += '<div class="notice notice-warn" role="status">' + icon("warn", 18) + "<span>The AI could not write an answer: " + esc(d.ai_error.message) + " The keyword matches are below.</span></div>";
    }
    var m = d.matches || [];
    if (m.length) {
      out += '<details class="ask-matches"' + (d.answer ? "" : " open") + "><summary>" + m.length + " keyword match" + (m.length === 1 ? "" : "es") +
        (d.stats ? " from " + d.stats.searched + " resume" + (d.stats.searched === 1 ? "" : "s") : "") + "</summary><ol>" + m.map(function (c) {
          return "<li><div class=\"ask-m-top\">" + link(c.candidate_id, c.name) + (c.source === "platform" ? ' <span class="chip chip-violet">Hiriq member</span>' : "") +
            ' <span class="ask-m-score mono" title="How strongly the words of your question appear, relative to the best match">' + c.score + "</span></div>" +
            '<small class="faint">' + [c.headline, c.location, c.years != null ? (c.years === 1 ? "1 yr" : +Number(c.years).toFixed(1) + " yrs") : ""].filter(Boolean).map(esc).join(" · ") + "</small>" +
            (c.snippet ? '<span class="ask-snippet">' + esc(c.snippet) + "</span>" : "") + "</li>";
        }).join("") + "</ol></details>";
    } else if (!d.answer) {
      out += '<p class="muted" style="margin:0">Nothing to show.</p>';
    }
    if (d.model) out += '<p class="hint" style="margin:6px 0 0">Answered by ' + esc(String(d.model).replace(/:free$/, "")) + " from the passages above. Check the resume before you decide anything.</p>";
    return out;
  }

  function itemHtml(item) {
    var scope = item.source !== "all" ? ' <span class="chip chip-neutral">' + esc((SOURCES.filter(function (s) { return s[0] === item.source; })[0] || [0, ""])[1]) + "</span>" : "";
    var body;
    if (item.state === "asking") body = '<p class="ask-wait" role="status"><span class="spin" aria-hidden="true"></span> Searching resumes and writing an answer. Free models can take up to a minute.</p>';
    else if (item.state === "error") body = '<div class="notice notice-' + (item.kind || "error") + '" role="alert">' + icon("info", 18) + "<span>" + esc(item.error) + "</span></div>";
    else body = answerHtml(item);
    return '<li class="card ask-item"><p class="ask-q">' + esc(item.q) + scope + "</p>" + body + "</li>";
  }

  function drawFeed() {
    var box = view.querySelector("#ask-feed");
    if (!box) return;
    box.innerHTML = feed.length ? feed.map(itemHtml).join("") : "";
    var busy = feed.some(function (i) { return i.state === "asking"; });
    var btn = view.querySelector("#ask-go");
    if (btn) { btn.disabled = busy; btn.textContent = busy ? "Asking…" : "Ask"; }
  }

  // ---------- the page ----------
  function show() {
    R.nav();
    var head = R.header("Ask the pool", "");
    view.innerHTML = '<div class="view">' + head + '<form class="card card-stack" id="ask-form" novalidate>' +
      '<div class="field-group"><label class="label" for="ask-q">Ask about your candidates</label>' +
      '<textarea class="field" id="ask-q" rows="2" maxlength="400" placeholder="For example: who has fintech experience and used Airflow?">' + esc(draft.q) + "</textarea>" +
      '<span class="hint">Answers come from the resumes you can see, and always name where they came from. Questions that ask to filter people by gender, age, religion, caste, nationality, marital status or disability are not answered.</span></div>' +
      '<div class="chips-row" id="ask-eg">' + EXAMPLES.map(function (e) { return '<button type="button" class="chip chip-neutral ask-eg" data-eg="' + esc(e) + '">' + esc(e) + "</button>"; }).join(" ") + "</div>" +
      '<div class="actions-bar"><div class="field-group" style="min-width:210px"><label class="label" for="ask-src">Search in</label><select class="field field-sm" id="ask-src">' +
      SOURCES.map(function (s) { return '<option value="' + s[0] + '"' + (s[0] === draft.source ? " selected" : "") + ">" + esc(s[1]) + "</option>"; }).join("") + "</select></div>" +
      '<button type="submit" class="btn btn-grad" id="ask-go">Ask</button></div></form>' +
      '<ul class="ask-feed" id="ask-feed" aria-live="polite"></ul></div>';
    drawFeed();

    var q = view.querySelector("#ask-q"), src = view.querySelector("#ask-src");
    q.addEventListener("input", function () { draft.q = q.value; });
    src.addEventListener("change", function () { draft.source = src.value; });
    q.addEventListener("keydown", function (e) { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } });
    view.querySelector("#ask-eg").addEventListener("click", function (e) {
      var b = e.target.closest("[data-eg]");
      if (!b) return;
      q.value = draft.q = b.getAttribute("data-eg");
      q.focus();
    });
    view.querySelector("#ask-form").addEventListener("submit", function (e) { e.preventDefault(); submit(); });
  }

  function submit() {
    var question = draft.q.replace(/\s+/g, " ").trim();
    if (feed.some(function (i) { return i.state === "asking"; })) return;
    if (question.length < 3) {
      feed.unshift({ q: question || "(empty question)", source: draft.source, state: "error", kind: "warn", error: "Type a question of at least a few words first." });
      drawFeed();
      return;
    }
    var item = { q: question, source: draft.source, state: "asking" };
    feed.unshift(item);
    draft.q = "";
    var box = view.querySelector("#ask-q"); if (box) box.value = "";
    drawFeed();
    api("POST", "/api/recruiter/ask", { question: question, source: item.source }).then(function (r) {
      if (r.ok) { item.state = "done"; item.data = r.data; }
      else {
        item.state = "error";
        item.kind = r.status === 422 || r.status === 429 ? "warn" : "error";
        item.error = r.status === 403 ? "This area is for recruiter accounts." : say(r);
      }
      drawFeed();
    });
  }

  return { show: show };
};
