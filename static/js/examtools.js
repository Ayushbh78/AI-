/* Exams page (/exams) and the exam mode of the Exam Paper page (/exam):
   choose exam -> load syllabus -> study plan / subject tests / full mock -> progress -> start exam. */
(function () {
  "use strict";
  const $ = function (s, r) { return (r || document).querySelector(s); };
  const $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  const esc = U.esc;
  const catalogEl = document.getElementById("exam-catalog");
  const root = document.getElementById("picker");
  if (!catalogEl || !root) return;
  const catalog = JSON.parse(catalogEl.textContent);
  const state = { exam: catalog[0], paper: "", info: null };
  const LAST = "ex-last";

  /* ---------- tiny helpers ---------- */
  function segValue(sel) { const on = $(sel + " .seg-btn.on"); return on ? on.dataset.value : ""; }
  document.addEventListener("click", function (e) {            // seg buttons used on these pages
    const b = e.target.closest(".seg-btn");
    if (!b || !b.parentElement.matches('[data-seg="ex-diff"], #ex-scope, #paper-mode')) return;
    $$(".seg-btn", b.parentElement).forEach(function (x) { x.classList.toggle("on", x === b); });
  });
  function hhmm(min) { return min >= 60 ? Math.floor(min / 60) + " h" + (min % 60 ? " " + (min % 60) + " min" : "") : min + " min"; }

  /* ---------- picker ---------- */
  const cardsEl = $("[data-cards]", root), paperSel = $("[data-paper]", root), customBox = $("[data-custom]", root);
  const statusEl = $("[data-status]", root), loadBtn = $("[data-load]", root);

  function renderCards() {
    cardsEl.innerHTML = catalog.map(function (e) {
      return '<button type="button" class="ex-card' + (e.id === state.exam.id ? " on" : "") + '" role="radio" aria-checked="' + (e.id === state.exam.id) +
        '" data-exam="' + esc(e.id) + '"><span class="ex-ico">' + e.icon + '</span><b>' + esc(e.name) + '</b></button>';
    }).join("");
  }
  function fillPapers(preselect) {
    const e = state.exam, custom = e.id === "custom";
    customBox.hidden = !custom;
    $("[data-paper-wrap]", root).hidden = custom;
    $("[data-paper-label]", root).textContent = e.paper_label;
    paperSel.innerHTML = e.papers.map(function (p) {
      return '<option value="' + esc(p.id) + '">' + (e.id === "gate" ? esc(p.id + " - " + p.name) : esc(p.name)) + '</option>';
    }).join("");
    if (preselect && e.papers.some(function (p) { return p.id === preselect; })) paperSel.value = preselect;
    state.paper = paperSel.value;
  }
  function resetResult() {
    state.info = null;
    const r = $("#ex-result"); if (r) r.hidden = true;
    const c = $("#ex-config"); if (c) c.hidden = true;
    statusEl.textContent = "";
  }
  cardsEl.addEventListener("click", function (e) {
    const b = e.target.closest(".ex-card"); if (!b) return;
    state.exam = catalog.filter(function (x) { return x.id === b.dataset.exam; })[0];
    renderCards(); fillPapers(); resetResult();
  });
  paperSel.addEventListener("change", function () { state.paper = paperSel.value; resetResult(); });
  $$("[data-custom-name],[data-custom-paper]", root).forEach(function (i) { i.addEventListener("input", resetResult); });

  function payload() {
    const custom = state.exam.id === "custom";
    return { exam_id: state.exam.id, paper: custom ? ($("[data-custom-paper]", root).value || "").trim() : state.paper,
             custom: custom ? ($("[data-custom-name]", root).value || "").trim() : "" };
  }
  async function loadInfo(refresh) {
    const body = payload();
    if (state.exam.id === "custom" && body.custom.length < 2) { statusEl.textContent = "Type the name of the exam first."; return; }
    loadBtn.disabled = true;
    statusEl.textContent = "Reading the official syllabus and pattern… the first time this can take up to a minute.";
    try {
      body.refresh = !!refresh;
      const res = await U.api("/api/exams/info", { json: body });
      state.info = res.info;
      try { localStorage.setItem(LAST, JSON.stringify({ exam: state.exam.id, paper: state.paper })); } catch (e) { /* private mode */ }
      statusEl.textContent = "";
      showInfo(res.info);
    } catch (err) { statusEl.textContent = err.message; }
    finally { loadBtn.disabled = false; }
  }
  loadBtn.addEventListener("click", function () { loadInfo(false); });

  /* ---------- showing the syllabus ---------- */
  function originBadge(info) {
    const map = { web: ["ok", "✓ Read from the official web pages (Tavily)"], builtin: ["info", "Built-in official syllabus"], ai: ["warn", "From AI knowledge, not checked on the web"] };
    const m = map[info.origin] || map.ai;
    return '<span class="ex-badge ' + m[0] + '">' + m[1] + '</span>';
  }
  function showInfo(info) {
    const s = info.summary;
    if ($("#ex-overview")) {                                         // Exams page
      $("#ex-result").hidden = false;
      $("#ex-overview").innerHTML =
        '<h2 class="ex-h">' + esc(info.title) + '</h2><div class="ex-badges">' + originBadge(info) +
        (info.pattern_origin === "generic" ? '<span class="ex-badge warn">Standard pattern (official one not found)</span>' : "") + '</div>' +
        '<div class="ex-stats"><div><b>' + s.questions + '</b><span>questions</span></div><div><b>' + s.marks + '</b><span>marks</span></div><div><b>' + hhmm(s.duration_min) + '</b><span>duration</span></div></div>' +
        '<ul class="ex-sections">' + s.sections.map(function (x) { return '<li><b>' + esc(x.name) + '</b>: ' + x.questions + ' questions, ' + x.marks + ' marks</li>'; }).join("") + '</ul>' +
        (s.rules.length ? '<ul class="ex-rules">' + s.rules.map(function (r) { return '<li>' + esc(r) + '</li>'; }).join("") + '</ul>' : "") +
        info.notes.map(function (n) { return '<p class="warn-box">' + esc(n) + '</p>'; }).join("") +
        (info.sources.length ? '<details class="ex-sources"><summary>Sources used (' + info.sources.length + ')</summary><ul>' + info.sources.map(function (x) {
          return '<li><a href="' + esc(x.url) + '" target="_blank" rel="noopener noreferrer">' + esc(x.title || x.url) + '</a></li>'; }).join("") + '</ul></details>' : "") +
        '<button type="button" class="btn ghost small" id="ex-refresh">↻ Refresh from the web</button>';
      $("#ex-refresh").addEventListener("click", function () { loadInfo(true); });
      $("#ex-subjects").innerHTML = info.subjects.map(function (sub, i) {
        return '<details class="ex-subject"><summary><span class="ex-sname">' + esc(sub.name) + '</span><small>about ' + Math.round(sub.marks) + ' marks · ' + sub.topics.length + ' topics</small></summary>' +
          '<ul class="ex-topics">' + sub.topics.map(function (t) { return '<li>' + esc(t) + '</li>'; }).join("") + '</ul>' +
          '<button type="button" class="btn ghost small" data-test="' + i + '">📝 Take subject test</button></details>';
      }).join("");
      $("#ex-result").scrollIntoView({ block: "start" });
    }
    if ($("#ex-config")) {                                           // Exam Paper page
      $("#ex-config").hidden = false;
      $("#ex-pattern-line").innerHTML = '<b>' + esc(info.title) + '</b>: ' + s.questions + ' questions · ' + s.marks + ' marks · ' + hhmm(s.duration_min) + ' ' + originBadge(info);
      $("#ex-subject-list").innerHTML = info.subjects.map(function (sub, i) {
        return '<label class="ex-check"><input type="checkbox" value="' + i + '"> <span>' + esc(sub.name) + ' <small class="muted">(about ' + Math.round(sub.marks) + ' marks)</small></span></label>';
      }).join("");
      $("#ex-config").scrollIntoView({ block: "start" });
    }
  }
  const subjectsEl = $("#ex-subjects");
  if (subjectsEl) subjectsEl.addEventListener("click", function (e) {
    const b = e.target.closest("[data-test]"); if (!b || !state.info) return;
    generate([state.info.subjects[+b.dataset.test].name]);
  });
  const scope = $("#ex-scope");
  if (scope) scope.addEventListener("click", function () { $("#ex-subject-list").hidden = segValue("#ex-scope") !== "subjects"; });

  /* ---------- study plan (Exams page) ---------- */
  const planBtn = $("#plan-btn");
  if (planBtn) planBtn.addEventListener("click", async function () {
    const st = $("#plan-status");
    planBtn.disabled = true; st.textContent = "Building your study plan…";
    try {
      const body = payload(); body.days = $("#plan-days").value; body.hours = $("#plan-hours").value;
      const res = await U.api("/api/exams/prepare", { json: body });
      st.innerHTML = (res.created ? "✅ Your study plan is ready. " : "You already have this study plan. ") + '<a href="' + esc(res.url) + '">Open my study plan →</a>';
    } catch (err) { st.textContent = err.message; }
    finally { planBtn.disabled = false; }
  });
  const mockBtn = $("#mock-btn");
  if (mockBtn) mockBtn.addEventListener("click", function () { generate([]); });
  const genBtn = $("#gen-btn");
  if (genBtn) genBtn.addEventListener("click", function () {
    if (!state.info) return;
    let names = [];
    if (segValue("#ex-scope") === "subjects") {
      names = $$("#ex-subject-list input:checked").map(function (c) { return state.info.subjects[+c.value].name; });
      if (!names.length) { U.toast("Choose at least one subject."); return; }
    }
    generate(names);
  });

  /* ---------- generating a paper with progress ---------- */
  const box = document.getElementById("gen-box");
  let pollTimer = null;
  function genUi(html) { box.hidden = false; box.innerHTML = '<div class="panel ex-genpanel">' + html + '</div>'; box.scrollIntoView({ block: "center" }); }
  async function generate(subjects) {
    clearTimeout(pollTimer);
    const body = payload(); body.subjects = subjects; body.difficulty = segValue('[data-seg="ex-diff"]') || "medium";
    genUi('<h3>Starting…</h3><div class="ex-bar"><i style="width:3%"></i></div>');
    try {
      const res = await U.api("/api/exams/generate", { json: body });
      try { localStorage.setItem("ex-pending", JSON.stringify({ pid: res.paper_id, at: Date.now() })); } catch (e) { /* ignore */ }
      poll(res.paper_id);
    } catch (err) { genUi('<h3>Could not start</h3><p class="error">' + esc(err.message) + '</p>'); }
  }
  async function poll(pid) {
    try {
      const st = await U.api("/api/exams/paper/" + encodeURIComponent(pid) + "/status", {});
      if (st.status === "ready") { done(pid); return; }
      if (st.status === "error") { genUi('<h3>The paper could not be finished</h3><p class="error">' + esc(st.error) + '</p>'); clearPending(); return; }
      const pct = st.total ? Math.max(4, Math.round(100 * st.done / st.total)) : 4;
      genUi('<h3>✍️ Writing your exam paper…</h3><div class="ex-bar"><i style="width:' + pct + '%"></i></div>' +
            '<p class="muted">' + st.done + ' of ' + st.total + ' questions written. A full paper takes one to three minutes. You can keep this page open.</p>');
    } catch (err) { /* a short network problem: keep trying */ }
    pollTimer = setTimeout(function () { poll(pid); }, 2500);
  }
  function clearPending() { try { localStorage.removeItem("ex-pending"); } catch (e) { /* ignore */ } }
  function done(pid) {
    clearPending();
    genUi('<h3>✅ Your paper is ready</h3><p class="muted">It opens in the exam hall with the real timer. Once you start, the clock keeps running even if you refresh.</p>' +
          '<a class="btn primary wide" href="/exam-hall/' + encodeURIComponent(pid) + '">▶ Start exam</a>');
    loadMine();
  }
  try {                                                               // a paper that was being written when the page was closed
    const pending = JSON.parse(localStorage.getItem("ex-pending") || "null");
    if (pending && Date.now() - pending.at < 20 * 60 * 1000) poll(pending.pid); else clearPending();
  } catch (e) { /* ignore */ }

  /* ---------- my papers ---------- */
  async function loadMine() {
    const wrap = document.getElementById("my-papers-wrap"); if (!wrap) return;
    try {
      const res = await U.api("/api/exams/papers", {});
      wrap.hidden = !res.papers.length;
      $("#my-papers").innerHTML = res.papers.slice(0, 12).map(function (p) {
        const running = p.attempts.filter(function (a) { return a.status === "running"; })[0];
        const finished = p.attempts.filter(function (a) { return a.status === "submitted"; });
        return '<div class="ex-paper"><div class="ex-ptitle"><b>' + esc(p.title) + '</b><small class="muted">' + esc(p.difficulty) + ' · ' + p.questions + ' questions · ' + p.total_marks + ' marks · ' + hhmm(p.duration_min) + '</small></div>' +
          '<div class="ex-pbtn"><a class="btn ' + (running ? 'primary' : 'ghost') + ' small" href="/exam-hall/' + encodeURIComponent(p.id) + '">' + (running ? "▶ Continue exam" : finished.length ? "↻ Retake" : "▶ Start exam") + '</a>' +
          finished.map(function (a) { return '<a class="btn ghost small" href="/exam-result/' + encodeURIComponent(a.id) + '">Result: ' + a.score + '/' + a.max + '</a>'; }).join("") + '</div></div>';
      }).join("");
    } catch (err) { /* list is optional */ }
  }

  /* ---------- Exam Paper page: mode tabs ---------- */
  const mode = document.getElementById("paper-mode");
  if (mode) mode.addEventListener("click", function (e) {
    const b = e.target.closest(".seg-btn"); if (!b) return;
    document.getElementById("mode-exam").hidden = b.dataset.mode !== "exam";
    document.getElementById("mode-custom").hidden = b.dataset.mode !== "custom";
  });

  /* ---------- start ---------- */
  let last = null;
  try { last = JSON.parse(localStorage.getItem(LAST) || "null"); } catch (e) { /* ignore */ }
  if (last) { const found = catalog.filter(function (x) { return x.id === last.exam; })[0]; if (found) state.exam = found; }
  renderCards(); fillPapers(last && last.paper);
  loadMine();
})();
