/* Exam result: score, analysis by subject / topic / type, and a full review of every question. */
(function () {
  "use strict";
  const root = document.getElementById("res");
  if (!root) return;
  const esc = U.esc;
  const aid = root.dataset.aid;
  const TYPE = { mcq: "MCQ", msq: "MSQ", nat: "NAT" };
  const n2 = function (x) { return String(Math.round(x * 100) / 100); };
  function dur(sec) { const m = Math.floor(sec / 60), s = sec % 60; return m >= 60 ? Math.floor(m / 60) + " h " + (m % 60) + " min" : m + " min " + (s < 10 ? "0" : "") + s + " s"; }
  function level(acc) { return acc === null ? ["na", "Not attempted"] : acc >= 70 ? ["good", "Strong"] : acc >= 40 ? ["mid", "Average"] : ["bad", "Needs work"]; }
  function bar(pct, cls) { return '<div class="r-bar"><i class="' + cls + '" style="width:' + Math.max(0, Math.min(100, pct)) + '%"></i></div>'; }

  function table(rows, withSubject) {
    return '<div class="r-scroll"><table class="r-table"><thead><tr><th>' + (withSubject ? "Topic" : "Name") + '</th><th>Marks</th><th>Right</th><th>Wrong</th><th>Skipped</th><th>Accuracy</th><th>Avg time</th></tr></thead><tbody>' +
      rows.map(function (r) {
        const lv = level(r.accuracy);
        return '<tr><td><b>' + esc(r.name) + '</b>' + (withSubject ? '<br><small class="muted">' + esc(r.subject) + '</small>' : "") + '</td>' +
          '<td>' + n2(r.marks) + ' / ' + n2(r.max_marks) + bar(r.max_marks ? 100 * Math.max(0, r.marks) / r.max_marks : 0, "good") + '</td>' +
          '<td>' + r.correct + '</td><td>' + r.wrong + '</td><td>' + r.skipped + '</td>' +
          '<td><span class="r-tag ' + lv[0] + '">' + (r.accuracy === null ? "–" : r.accuracy + "%") + '</span></td><td>' + (r.avg_time_s ? dur(r.avg_time_s) : "–") + '</td></tr>';
      }).join("") + '</tbody></table></div>';
  }

  function answerText(q, v) {
    if (v === null || v === undefined || v === "" || (Array.isArray(v) && !v.length)) return "Not answered";
    if (q.type === "nat") return typeof v === "object" ? (v.low === v.high ? String(v.low) : v.low + " to " + v.high) : String(v);
    return Array.isArray(v) ? v.join(", ") : String(v);
  }
  function reviewCard(q) {
    const sign = q.status === "correct" ? "✓ +" + n2(q.got) : q.status === "wrong" ? "✗ " + (q.got < 0 ? "−" + n2(-q.got) : "0") : "– Skipped";
    let body = '<div class="md r-qtext">' + U.md(q.text) + '</div>';
    if (q.options) {
      body += '<div class="r-opts">' + q.options.map(function (o, k) {
        const L = "ABCD"[k], right = q.correct.indexOf(L) >= 0;
        const mine = Array.isArray(q.your) ? q.your.indexOf(L) >= 0 : q.your === L;
        return '<div class="r-opt' + (right ? " right" : mine ? " mine" : "") + '"><b>' + L + '</b><span>' + esc(o) + '</span>' + (right ? '<em>correct</em>' : mine ? '<em>your answer</em>' : "") + (right && mine ? '<em class="you">your answer</em>' : "") + '</div>';
      }).join("") + '</div>';
    } else {
      body += '<p class="r-nat"><b>Your answer:</b> ' + esc(answerText(q, q.your)) + ' &nbsp; <b>Correct:</b> ' + esc(answerText(q, q.correct)) + '</p>';
    }
    body += (q.explanation ? '<p class="r-expl"><b>Explanation:</b> ' + esc(q.explanation) + '</p>' : "") +
      '<p class="muted small">Topic: ' + esc(q.topic) + ' · Time on this question: ' + (q.time_s ? dur(q.time_s) : "not recorded") + '</p>';
    return '<details class="r-q ' + q.status + '" data-status="' + q.status + '"><summary><span class="r-no">Q' + q.no + '</span><span class="r-sub">' + esc(q.subject) + ' · ' + TYPE[q.type] + ' · ' + n2(q.marks) + ' marks</span><span class="r-sign">' + sign + '</span></summary>' + body + '</details>';
  }

  async function load() {
    try {
      const data = await U.api("/api/exams/attempt/" + encodeURIComponent(aid) + "/result", {});
      const r = data.result, p = data.paper;
      const lv = level(r.percent);
      root.innerHTML =
        '<section class="tool-head"><h1>📊 Result</h1><p class="muted">' + esc(p.title) + ' · ' + esc(p.difficulty) + ' · ' + p.duration_min + ' min</p></section>' +
        '<section class="panel r-hero"><div class="r-ring ' + lv[0] + '"><b>' + n2(r.score) + '</b><span>out of ' + n2(r.max) + '</span></div>' +
        '<div class="r-stats"><div><b>' + r.percent + '%</b><span>score</span></div><div><b>' + r.attempted + '/' + r.questions + '</b><span>attempted</span></div>' +
        '<div class="good"><b>' + r.correct + '</b><span>correct</span></div><div class="bad"><b>' + r.wrong + '</b><span>wrong</span></div><div><b>' + r.skipped + '</b><span>skipped</span></div>' +
        '<div class="bad"><b>−' + n2(r.negative_total) + '</b><span>negative marks</span></div><div><b>' + (r.accuracy === null ? "–" : r.accuracy + "%") + '</b><span>accuracy</span></div><div><b>' + dur(r.time_used_s) + '</b><span>time used</span></div></div></section>' +
        (r.insights.length ? '<section class="panel"><h2 class="ex-h">What to do next</h2><ul class="r-tips">' + r.insights.map(function (t) { return '<li>' + esc(t) + '</li>'; }).join("") + '</ul></section>' : "") +
        '<section class="panel"><h2 class="ex-h">Subject-wise analysis</h2>' + table(r.by_subject) + '</section>' +
        (r.by_section.length > 1 ? '<section class="panel"><h2 class="ex-h">Section-wise</h2>' + table(r.by_section) + '</section>' : "") +
        '<section class="panel"><h2 class="ex-h">Topic-wise analysis</h2><p class="muted small">Weakest topics first. Revise the ones marked "Needs work".</p>' + table(r.by_topic, true) + '</section>' +
        '<section class="panel"><h2 class="ex-h">Question types</h2>' + table(r.by_type) + '</section>' +
        '<section class="panel"><h2 class="ex-h">Review every question</h2><div class="seg" id="r-filter">' +
        '<button type="button" class="seg-btn on" data-f="all">All (' + r.questions + ')</button><button type="button" class="seg-btn" data-f="wrong">Wrong (' + r.wrong + ')</button>' +
        '<button type="button" class="seg-btn" data-f="skipped">Skipped (' + r.skipped + ')</button><button type="button" class="seg-btn" data-f="correct">Correct (' + r.correct + ')</button></div>' +
        '<div id="r-list">' + r.review.map(reviewCard).join("") + '</div></section>' +
        '<div class="r-actions"><a class="btn primary" href="/exam-hall/' + encodeURIComponent(p.id) + '">↻ Retake this paper</a><a class="btn ghost" href="/exam">New paper</a><a class="btn ghost" href="/exams">Exams and study plan</a><button type="button" class="btn ghost" onclick="window.print()">🖨️ Print</button></div>';
      document.getElementById("r-filter").addEventListener("click", function (e) {
        const b = e.target.closest("[data-f]"); if (!b) return;
        Array.prototype.forEach.call(this.children, function (x) { x.classList.toggle("on", x === b); });
        Array.prototype.forEach.call(document.querySelectorAll("#r-list .r-q"), function (el) { el.hidden = b.dataset.f !== "all" && el.dataset.status !== b.dataset.f; });
      });
    } catch (err) {
      root.innerHTML = '<p class="error">' + esc(err.message) + '</p><p><a href="/exam">← Back to Exam Paper</a></p>';
    }
  }
  load();
})();
