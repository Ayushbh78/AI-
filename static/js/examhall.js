/* Exam hall: a real computer-based exam. Server-side timer, autosave, MCQ / MSQ / NAT, palette, calculator, submit. */
(function () {
  "use strict";
  const $ = function (s, r) { return (r || document).querySelector(s); };
  const $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  const esc = U.esc;
  const hall = $("#hall");
  if (!hall) return;
  const pid = hall.dataset.pid;
  const TYPE_NAME = { mcq: "MCQ", msq: "MSQ", nat: "NAT" };
  let S = null;            // exam state
  let timerId = null, saveTimer = null, submitting = false, running = false;

  const num = function (x) { return String(Math.round(x * 100) / 100); };
  function clock(sec) {
    sec = Math.max(0, Math.floor(sec));
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    return (h < 10 ? "0" : "") + h + ":" + (m < 10 ? "0" : "") + m + ":" + (s < 10 ? "0" : "") + s;
  }
  function inlineMd(t) { return esc(t).replace(/`([^`]+)`/g, "<code>$1</code>"); }

  /* ================= instructions screen ================= */
  async function showIntro() {
    const body = $("#i-body");
    try {
      const m = await U.api("/api/exams/paper/" + encodeURIComponent(pid) + "/meta", {});
      const kinds = Object.keys(m.types).map(function (k) { return m.types[k] + " " + TYPE_NAME[k]; }).join(", ");
      const resume = m.running;
      body.innerHTML =
        '<div class="h-facts"><div><b>' + m.duration_min + ' min</b><span>duration</span></div><div><b>' + m.questions + '</b><span>questions</span></div><div><b>' + num(m.total_marks) + '</b><span>maximum marks</span></div></div>' +
        '<table class="h-table"><thead><tr><th>Section</th><th>Questions</th><th>Marks</th></tr></thead><tbody>' +
        m.sections.map(function (s) { return '<tr><td>' + esc(s.name) + '</td><td>' + s.questions + '</td><td>' + num(s.marks) + '</td></tr>'; }).join("") + '</tbody></table>' +
        '<h3>Instructions</h3><ol class="h-rules">' +
        '<li>The countdown timer at the top right shows your remaining time. When it reaches zero the exam ends and your answers are submitted automatically. The clock keeps running even if you refresh the page.</li>' +
        '<li>Question types in this paper: ' + esc(kinds) + '. <b>MCQ</b>: choose one option. <b>MSQ</b>: choose one or more options. <b>NAT</b>: type a number with the on-screen keypad.</li>' +
        m.rules.map(function (r) { return '<li>' + esc(r) + '</li>'; }).join("") +
        '<li>Use the question palette to jump to any question. <span class="h-dot na"></span> not answered, <span class="h-dot an"></span> answered, <span class="h-dot nv"></span> not visited, <span class="h-dot mr"></span> marked for review, <span class="h-dot am"></span> answered and marked.</li>' +
        '<li>An answer you give is saved at once. "Mark for Review" is only a reminder for you: a marked question that has an answer is still evaluated.</li>' +
        '<li>A calculator is available in the top bar. Rough work is done on paper.</li></ol>' +
        (m.warnings || []).map(function (w) { return '<p class="warn-box">' + esc(w) + '</p>'; }).join("") +
        '<label class="h-agree"><input type="checkbox" id="i-agree"> I have read and understood the instructions.</label>' +
        '<button type="button" class="h-begin" id="i-begin" disabled>' + (resume ? "Resume exam (" + clock(resume.remaining_s) + " left)" : "I am ready to begin") + '</button>' +
        '<p class="h-back"><a href="/exam">← Back to Exam Paper</a></p>';
      $("#i-agree").addEventListener("change", function () { $("#i-begin").disabled = !this.checked; });
      $("#i-begin").addEventListener("click", begin);
    } catch (err) {
      body.innerHTML = '<p class="error">' + esc(err.message) + '</p><p><a href="/exam">← Back to Exam Paper</a></p>';
    }
  }

  /* ================= start / resume ================= */
  async function begin() {
    const btn = $("#i-begin"); btn.disabled = true; btn.textContent = "Starting…";
    goFullscreen();
    try {
      const res = await U.api("/api/exams/attempt/start", { json: { paper_id: pid } });
      if (res.status !== "running") { window.location.replace("/exam-result/" + res.attempt_id); return; }
      initExam(res);
    } catch (err) { btn.disabled = false; btn.textContent = "I am ready to begin"; U.toast(err.message); }
  }

  function initExam(res) {
    const saved = res.saved || {};
    S = { aid: res.attempt_id, paper: res.paper, qs: res.paper.questions, offset: res.server_now - Date.now() / 1000,
          started: res.started, duration: res.duration_s, answers: saved.answers || {}, marked: new Set(saved.marked || []),
          visited: new Set(saved.visited || []), spent: saved.time_spent || {}, cur: saved.current || 0, dirty: false, nat: {} };
    S.sections = res.paper.sections;
    $("#h-intro").hidden = true; $("#h-exam").hidden = false;
    $("#h-exam-title").textContent = res.paper.title;
    document.body.classList.add("hall-on");
    running = true;
    window.addEventListener("beforeunload", warnLeave);
    renderSections(); go(S.cur); tick();
    timerId = setInterval(tick, 1000);
    setInterval(function () { if (S.dirty) saveNow(); }, 15000);
  }
  function warnLeave(e) { if (running) { e.preventDefault(); e.returnValue = ""; } }

  /* ================= timer ================= */
  function remaining() { return S.started + S.duration - (Date.now() / 1000 + S.offset); }
  function tick() {
    const left = remaining();
    const t = $("#h-timer"); t.textContent = clock(left);
    $("#h-timer-wrap").classList.toggle("low", left < 600);
    const q = S.qs[S.cur];
    if (q && $("#h-modal").hidden) S.spent[q.id] = (S.spent[q.id] || 0) + 1;     // time is counted per question while no pop-up is open
    if (left <= 0 && !submitting) { clearInterval(timerId); finish(true); }
  }

  /* ================= status of a question ================= */
  function has(q) { const a = S.answers[q.id]; return a !== undefined && a !== "" && !(Array.isArray(a) && !a.length); }
  function status(q) {
    const answered = has(q), marked = S.marked.has(q.id);
    if (answered && marked) return "am";
    if (answered) return "an";
    if (marked) return "mr";
    return S.visited.has(q.id) ? "na" : "nv";
  }

  /* ================= sections and palette ================= */
  function renderSections() {
    $("#h-sections").innerHTML = S.sections.map(function (name) {
      return '<button type="button" data-sec="' + esc(name) + '">' + esc(name) + '</button>';
    }).join("");
  }
  $("#h-sections").addEventListener("click", function (e) {
    const b = e.target.closest("[data-sec]"); if (!b) return;
    const i = S.qs.findIndex(function (q) { return q.section === b.dataset.sec; });
    if (i >= 0) go(i);
  });
  function renderPalette() {
    const cur = S.qs[S.cur];
    $$("#h-sections button").forEach(function (b) { b.classList.toggle("on", b.dataset.sec === cur.section); });
    const counts = { an: 0, na: 0, nv: 0, mr: 0, am: 0 };
    S.qs.forEach(function (q) { counts[status(q)]++; });
    $("#h-legend").innerHTML =
      '<span><i class="h-dot an"></i>' + counts.an + ' Answered</span><span><i class="h-dot na"></i>' + counts.na + ' Not answered</span>' +
      '<span><i class="h-dot nv"></i>' + counts.nv + ' Not visited</span><span><i class="h-dot mr"></i>' + counts.mr + ' Marked</span>' +
      '<span class="wide"><i class="h-dot am"></i>' + counts.am + ' Answered &amp; marked</span>';
    $("#h-palsec").textContent = cur.section;
    $("#h-grid").innerHTML = S.qs.map(function (q, i) {
      return q.section !== cur.section ? "" :
        '<button type="button" class="h-n ' + status(q) + (i === S.cur ? " cur" : "") + '" data-i="' + i + '" aria-label="Question ' + q.no + '">' + q.no + '</button>';
    }).join("");
    $("#h-pal-count").textContent = (counts.an + counts.am) + "/" + S.qs.length;
  }
  $("#h-grid").addEventListener("click", function (e) {
    const b = e.target.closest("[data-i]"); if (!b) return;
    go(+b.dataset.i); palette(false);
  });
  function palette(open) { $("#h-pal").classList.toggle("open", open); $("#h-pal-back").classList.toggle("open", open); }
  $("#h-pal-btn").addEventListener("click", function () { palette(!$("#h-pal").classList.contains("open")); });
  $("#h-pal-close").addEventListener("click", function () { palette(false); });
  $("#h-pal-back").addEventListener("click", function () { palette(false); });

  /* ================= showing a question ================= */
  function go(i) {
    S.cur = Math.max(0, Math.min(S.qs.length - 1, i));
    const q = S.qs[S.cur];
    S.visited.add(q.id);
    renderQuestion(q); renderPalette();
    $("#h-q").scrollTop = 0;
    $("#h-mark").textContent = S.marked.has(q.id) ? "Unmark & Next" : "Mark & Next";
    $("#h-prev").disabled = S.cur === 0;
    changed();
  }
  function renderQuestion(q) {
    const a = S.answers[q.id];
    let input = "";
    if (q.type === "mcq" || q.type === "msq") {
      input = '<p class="h-hint">' + (q.type === "mcq" ? "Select one option." : "Select one or more options.") + '</p><div class="h-opts">' +
        q.options.map(function (o, k) {
          const L = "ABCD"[k], on = q.type === "mcq" ? a === L : (a || []).indexOf(L) >= 0;
          return '<label class="h-opt' + (on ? " on" : "") + '"><input type="' + (q.type === "mcq" ? "radio" : "checkbox") + '" name="opt" value="' + L + '"' + (on ? " checked" : "") + '>' +
            '<span class="h-letter">' + L + '</span><span class="h-otext">' + inlineMd(o) + '</span></label>';
        }).join("") + '</div>';
    } else {
      input = '<p class="h-hint">Type your numerical answer using the keypad.</p><div class="h-nat"><input type="text" id="h-natv" readonly value="' + esc(natText(q)) + '" placeholder="Your answer" aria-label="Numerical answer">' +
        '<div class="h-keys">' + [["7"], ["8"], ["9"], ["back", "⌫"], ["4"], ["5"], ["6"], ["clear", "C"], ["1"], ["2"], ["3"], ["-", "−"], ["0", "0", "s2"], [".", ".", "s2"]].map(function (k) {
          return '<button type="button" data-k="' + k[0] + '" class="' + (k[2] || "") + (k[0] === "back" || k[0] === "clear" ? " fn" : "") + '" aria-label="' + (k[0] === "back" ? "Backspace" : k[0] === "clear" ? "Clear" : k[0]) + '">' + (k[1] || k[0]) + '</button>'; }).join("") + '</div></div>';
    }
    $("#h-q").innerHTML =
      '<div class="h-qhead"><b>Question ' + q.no + ' of ' + S.qs.length + '</b><span class="h-chip t">' + TYPE_NAME[q.type] + '</span>' +
      '<span class="h-chip m">+' + num(q.marks) + ' marks</span><span class="h-chip n' + (q.neg ? "" : " zero") + '">' + (q.neg ? "−" + num(q.neg) + " if wrong" : "No negative marking") + '</span></div>' +
      '<div class="h-qtext md">' + U.md(q.text) + '</div>' + input;
  }

  /* ================= answering ================= */
  $("#h-q").addEventListener("change", function (e) {
    const t = e.target; if (t.name !== "opt") return;
    const q = S.qs[S.cur];
    if (q.type === "mcq") S.answers[q.id] = t.value;
    else {
      const set = $$('#h-q input[name="opt"]:checked').map(function (x) { return x.value; });
      if (set.length) S.answers[q.id] = set; else delete S.answers[q.id];
    }
    $$("#h-q .h-opt").forEach(function (l) { l.classList.toggle("on", l.querySelector("input").checked); });
    renderPalette(); changed(true);
  });
  function typeNat(k) {
    const q = S.qs[S.cur]; if (q.type !== "nat") return;
    let v = natText(q);
    if (k === "back") v = v.slice(0, -1);
    else if (k === "clear") v = "";
    else if (k === "-") v = v.charAt(0) === "-" ? v.slice(1) : "-" + v;        // the minus key toggles the sign
    else if (k === ".") { if (v.indexOf(".") < 0 && v.length < 14) v += (v === "" || v === "-" ? "0." : "."); }
    else if (/^\d$/.test(k) && v.length < 14) v += k;
    S.nat[q.id] = v;
    if (/\d/.test(v)) S.answers[q.id] = v; else delete S.answers[q.id];       // "-" alone is not an answer yet
    $("#h-natv").value = v;
    renderPalette(); changed(true);
  }
  function natText(q) { return S.nat[q.id] !== undefined ? S.nat[q.id] : String(S.answers[q.id] || ""); }
  $("#h-q").addEventListener("click", function (e) { const k = e.target.closest("[data-k]"); if (k) typeNat(k.dataset.k); });
  document.addEventListener("keydown", function (e) {
    if (!running || !$("#h-modal").hidden || e.ctrlKey || e.metaKey || e.altKey) return;
    if (/^[0-9.]$/.test(e.key) || e.key === "-") typeNat(e.key);
    else if (e.key === "Backspace") { typeNat("back"); e.preventDefault(); }
  });

  $("#h-save").addEventListener("click", function () { go(S.cur + 1); });
  $("#h-prev").addEventListener("click", function () { go(S.cur - 1); });
  $("#h-mark").addEventListener("click", function () {
    const id = S.qs[S.cur].id;
    if (S.marked.has(id)) S.marked.delete(id); else S.marked.add(id);
    go(S.cur + 1);
  });
  $("#h-clear").addEventListener("click", function () {
    delete S.answers[S.qs[S.cur].id]; delete S.nat[S.qs[S.cur].id]; renderQuestion(S.qs[S.cur]); renderPalette(); changed(true);
  });

  /* ================= saving ================= */
  function snapshot() {
    return { answers: S.answers, marked: Array.from(S.marked), visited: Array.from(S.visited), time_spent: S.spent, current: S.cur };
  }
  function changed(now) { S.dirty = true; clearTimeout(saveTimer); saveTimer = setTimeout(saveNow, now ? 1200 : 4000); }
  function saveNow() {
    if (!S || submitting) return;
    S.dirty = false;
    fetch("/api/exams/attempt/" + encodeURIComponent(S.aid) + "/save", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(snapshot()), keepalive: true
    }).catch(function () { S.dirty = true; });
  }
  document.addEventListener("visibilitychange", function () { if (document.hidden && S && S.dirty) saveNow(); });

  /* ================= modals ================= */
  function modal(html) { $("#h-modal-box").innerHTML = html; $("#h-modal").hidden = false; }
  function closeModal() { $("#h-modal").hidden = true; $("#h-modal-box").innerHTML = ""; }

  $("#h-instr").addEventListener("click", function () {
    modal('<h3>Instructions</h3><ul class="h-rules"><li>The timer shows your remaining time; the exam ends automatically at zero.</li><li>MCQ: one option. MSQ: one or more options. NAT: type a number with the keypad.</li>' +
          (S.paper.rules || []).map(function (r) { return '<li>' + esc(r) + '</li>'; }).join("") + '</ul><button type="button" class="h-btn primary" data-close>Close</button>');
  });
  $("#h-modal").addEventListener("click", function (e) { if (e.target.matches("[data-close]") || e.target.id === "h-modal") closeModal(); });

  $("#h-submit").addEventListener("click", function () {
    const c = { an: 0, na: 0, nv: 0, mr: 0, am: 0 };
    S.qs.forEach(function (q) { c[status(q)]++; });
    modal('<h3>Submit the exam?</h3><table class="h-table"><tbody><tr><td>Answered</td><td>' + (c.an + c.am) + '</td></tr><tr><td>Not answered</td><td>' + c.na + '</td></tr>' +
          '<tr><td>Not visited</td><td>' + c.nv + '</td></tr><tr><td>Marked for review</td><td>' + (c.mr + c.am) + '</td></tr></tbody></table>' +
          '<p class="muted">Time left: ' + clock(remaining()) + '. After submitting you cannot change your answers.</p>' +
          '<div class="h-btnrow"><button type="button" class="h-btn" data-close>No, go back</button><button type="button" class="h-btn primary" id="h-yes">Yes, submit</button></div>');
    $("#h-yes").addEventListener("click", function () { closeModal(); finish(false); });
  });

  async function finish(auto) {
    if (submitting) return;
    submitting = true; running = false;
    modal('<h3>' + (auto ? "Time is up" : "Submitting") + '</h3><p class="muted">' + (auto ? "Your answers are being submitted…" : "Please wait while your paper is checked…") + '</p>');
    for (let attempt = 0; attempt < 40; attempt++) {              // keep trying if the connection drops
      try {
        const res = await fetch("/api/exams/attempt/" + encodeURIComponent(S.aid) + "/submit", {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(snapshot()) });
        const data = await res.json().catch(function () { return {}; });
        if (res.ok && data.url) {
          window.removeEventListener("beforeunload", warnLeave);
          try { if (document.fullscreenElement) await document.exitFullscreen(); } catch (e) { /* ignore */ }
          window.location.replace(data.url); return;
        }
        if (res.status === 401) { await U.resumeLogin(); }
      } catch (err) { /* offline: try again */ }
      modal('<h3>Connection problem</h3><p class="muted">Your answers are safe. Trying again…</p>');
      await new Promise(function (r) { setTimeout(r, 4000); });
    }
    modal('<h3>Could not submit</h3><p class="muted">Check your internet and reload this page: your exam will continue where you left it.</p>');
  }

  /* ================= full screen ================= */
  function goFullscreen() {
    const el = document.documentElement;
    try { const p = (el.requestFullscreen || el.webkitRequestFullscreen || function () {}).call(el); if (p && p.catch) p.catch(function () {}); } catch (e) { /* not supported */ }
  }
  const fsOn = function () { return !!(document.fullscreenElement || document.webkitFullscreenElement); };
  $("#h-full").addEventListener("click", function () {
    if (fsOn()) { try { (document.exitFullscreen || document.webkitExitFullscreen).call(document); } catch (e) { /* ignore */ } } else goFullscreen();
  });
  $("#h-fsback").addEventListener("click", goFullscreen);
  document.addEventListener("fullscreenchange", function () {
    $("#h-fsbar").hidden = !running || fsOn() || !(document.documentElement.requestFullscreen);
  });

  /* ================= calculator ================= */
  function calc() {
    let deg = true, expr = "";
    modal('<h3>Scientific calculator</h3><input id="c-disp" class="h-cdisp" readonly value="" aria-label="Calculator display"><p class="muted small" id="c-res">0</p>' +
          '<div class="h-ckeys">' + ["sin(", "cos(", "tan(", "log(", "ln(", "sqrt(", "(", ")", "^", "7", "8", "9", "/", "pi", "4", "5", "6", "*", "e", "1", "2", "3", "-", "!", "0", ".", "+", "ans", "⌫", "C", "="].map(function (k) {
            return '<button type="button" data-c="' + esc(k) + '">' + esc(k) + '</button>'; }).join("") + '</div>' +
          '<div class="h-btnrow"><button type="button" class="h-btn" id="c-mode">Degrees</button><button type="button" class="h-btn primary" data-close>Close</button></div>');
    let last = 0;
    const disp = $("#c-disp"), res = $("#c-res");
    $("#c-mode").addEventListener("click", function () { deg = !deg; this.textContent = deg ? "Degrees" : "Radians"; });
    $(".h-ckeys").addEventListener("click", function (e) {
      const b = e.target.closest("[data-c]"); if (!b) return;
      const k = b.dataset.c;
      if (k === "C") expr = "";
      else if (k === "⌫") expr = expr.replace(/(sin\(|cos\(|tan\(|log\(|ln\(|sqrt\(|pi|ans|.)$/, "");
      else if (k === "=") { try { last = evaluate(expr, deg, last); res.textContent = "= " + String(+last.toPrecision(12)); } catch (err) { res.textContent = "Error"; } }
      else expr += k;
      disp.value = expr;
    });
  }
  $("#h-calc").addEventListener("click", calc);
  function evaluate(src, deg, ans) {                                   // small safe expression parser (no eval)
    const tokens = src.match(/\d+\.?\d*|\.\d+|sin\(|cos\(|tan\(|log\(|ln\(|sqrt\(|pi|ans|e|[-+*/^()!]/g) || [];
    let p = 0;
    const toRad = function (x) { return deg ? x * Math.PI / 180 : x; };
    function peek() { return tokens[p]; }
    function expr() { let v = term(); while (peek() === "+" || peek() === "-") { const o = tokens[p++]; const r = term(); v = o === "+" ? v + r : v - r; } return v; }
    function term() { let v = pow(); while (peek() === "*" || peek() === "/") { const o = tokens[p++]; const r = pow(); v = o === "*" ? v * r : v / r; } return v; }
    function pow() { const b = unary(); if (peek() === "^") { p++; return Math.pow(b, pow()); } return b; }
    function unary() { if (peek() === "-") { p++; return -unary(); } if (peek() === "+") { p++; return unary(); } return post(); }
    function post() { let v = atom(); while (peek() === "!") { p++; let f = 1; for (let i = 2; i <= Math.round(v) && i < 171; i++) f *= i; v = f; } return v; }
    function atom() {
      const t = tokens[p++];
      if (t === undefined) throw new Error("end");
      if (t === "(") { const v = expr(); if (tokens[p++] !== ")") throw new Error("paren"); return v; }
      if (t === "pi") return Math.PI;
      if (t === "e") return Math.E;
      if (t === "ans") return ans;
      if (/^[a-z]+\($/.test(t)) {
        const v = expr(); if (tokens[p++] !== ")") throw new Error("paren");
        return ({ "sin(": function () { return Math.sin(toRad(v)); }, "cos(": function () { return Math.cos(toRad(v)); }, "tan(": function () { return Math.tan(toRad(v)); },
                  "log(": function () { return Math.log10(v); }, "ln(": function () { return Math.log(v); }, "sqrt(": function () { return Math.sqrt(v); } })[t]();
      }
      const n = parseFloat(t); if (isNaN(n)) throw new Error("num"); return n;
    }
    const v = expr(); if (p !== tokens.length || !isFinite(v)) throw new Error("bad"); return v;
  }

  /* ================= go ================= */
  showIntro();
})();
