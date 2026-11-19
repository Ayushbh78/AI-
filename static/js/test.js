(function () {
  const U = window.U;
  const boot = JSON.parse(document.getElementById("boot").textContent);
  const form = document.getElementById("test-form");
  const card = document.getElementById("test-card");
  const box = document.getElementById("quiz-box");

  form.addEventListener("submit", async function (event) {
    event.preventDefault();
    const scope = document.getElementById("scope").value;
    const format = document.getElementById("test-format") ? document.getElementById("test-format").value : "mcq";
    const count = parseInt(document.getElementById("count").value, 10);
    const module = boot.modules.find(function (m) { return m.id === scope; });
    const topicIds = module ? module.topicIds : [];
    card.hidden = false;
    card.scrollIntoView({ behavior: "smooth", block: "start" });

    if (format === "mcq") {
      window.Quiz.start(box, boot.courseId, { topic_ids: topicIds, count: count, kind: "test" });
    } else {
      // Comprehensive test with subjective questions and AI evaluation
      box.innerHTML = '<p class="muted loading"><span class="spinner small"></span> AI Examiner is preparing your calibrated test...</p>';
      try {
        const res = await U.api("/api/courses/" + boot.courseId + "/test_comprehensive", {
          json: {
            topic_ids: topicIds,
            count: count,
            test_type: format
          },
          timeout: 180000
        });
        renderComprehensiveTest(res, box, boot.courseId);
      } catch (err) {
        box.innerHTML = '<p class="error">' + U.esc(err.message) + '</p>';
      }
    }
  });

  function renderComprehensiveTest(testData, container, courseId) {
    const questions = testData.questions || [];
    let html = '<form id="ctest-exec-form" novalidate>';
    html += '<div class="plan-top mb-3"><div><h3>' + U.esc(testData.title) + '</h3><span class="small muted">Total Marks: ' + testData.total_marks + '</span></div></div>';

    questions.forEach(function (q, idx) {
      html += '<div class="test-q-card" data-qid="' + q.id + '" data-type="' + q.type + '">';
      html += '<div class="plan-top"><span class="tag">' + (q.type === "subjective" ? "✍️ Written Question" : "🔘 Multiple Choice") + '</span>' +
              '<span class="score-badge">[' + q.max_marks + ' Mark' + (q.max_marks > 1 ? 's' : '') + ']</span></div>';
      html += '<p class="test-q-text">' + (idx + 1) + '. ' + U.esc(q.question) + '</p>';

      if (q.type === "mcq") {
        html += '<div class="opt-group">';
        (q.options || []).forEach(function (opt, oIdx) {
          html += '<label class="opt"><input type="radio" name="ans_' + q.id + '" value="' + oIdx + '"><span><strong>' +
            String.fromCharCode(65 + oIdx) + '.</strong> ' + U.esc(opt) + '</span></label>';
        });
        html += '</div>';
      } else {
        html += '<label class="small muted">Type your answer below (evaluated by AI):</label>';
        html += '<textarea class="test-sub-input" name="ans_' + q.id + '" placeholder="Write your full explanation, steps, or definitions here..."></textarea>';
      }

      html += '<div class="eval-result-area" hidden></div>';
      html += '</div>';
    });

    html += '<div class="mt-3" id="ctest-submit-wrap"><button type="submit" class="btn primary wide" id="btn-submit-ctest">✨ Submit Answers for AI Evaluation</button></div>';
    html += '</form><div id="ctest-grade-summary" class="mt-3"></div>';

    container.innerHTML = html;

    const execForm = document.getElementById("ctest-exec-form");
    execForm.addEventListener("submit", async function (e) {
      e.preventDefault();
      const submitBtn = document.getElementById("btn-submit-ctest");
      submitBtn.disabled = true;
      submitBtn.textContent = "AI Examiner is grading your answers...";

      const answers = {};
      questions.forEach(function (q) {
        if (q.type === "mcq") {
          const checked = execForm.querySelector('input[name="ans_' + q.id + '"]:checked');
          answers[q.id] = checked ? parseInt(checked.value, 10) : null;
        } else {
          const ta = execForm.querySelector('textarea[name="ans_' + q.id + '"]');
          answers[q.id] = ta ? ta.value.trim() : "";
        }
      });

      try {
        const gradeRes = await U.api("/api/test/evaluate", {
          json: {
            test_id: testData.test_id,
            answers: answers
          },
          timeout: 180000
        });

        displayTestResults(gradeRes, execForm, container);
      } catch (err) {
        U.toast(err.message || "Failed to grade answers.");
        submitBtn.disabled = false;
        submitBtn.textContent = "Submit Answers for AI Evaluation";
      }
    });
  }

  function displayTestResults(result, form, container) {
    const questions = result.questions || [];

    questions.forEach(function (q) {
      const card = form.querySelector('.test-q-card[data-qid="' + q.id + '"]');
      if (!card) return;
      const area = card.querySelector(".eval-result-area");
      area.hidden = false;

      if (q.type === "mcq") {
        const isOk = q.is_correct;
        area.innerHTML = '<div class="eval-box ' + (isOk ? 'ok' : 'warn') + '">' +
          '<strong>' + (isOk ? '✅ Correct (+ ' + q.marks_awarded + ' Marks)' : '❌ Incorrect (0 Marks)') + '</strong>' +
          '<p class="small mt-1">' + U.esc(q.explanation || "") + '</p>' +
          '</div>';
      } else {
        const marks = q.marks_awarded;
        const max = q.max_marks;
        const isGreat = marks >= max * 0.7;
        area.innerHTML = '<div class="eval-box ' + (isGreat ? 'ok' : 'warn') + '">' +
          '<div class="plan-top"><strong>Examiner Score: ' + marks + ' / ' + max + ' Marks</strong>' +
          '<span class="score-badge ' + (isGreat ? 'ok-text' : '') + '">' + Math.round((marks / max) * 100) + '%</span></div>' +
          '<p class="mt-1"><strong>✅ Strengths:</strong> ' + U.esc(q.strengths) + '</p>' +
          '<p class="mt-1"><strong>💡 Missing / Improvement:</strong> ' + U.esc(q.missed_points) + '</p>' +
          '<details class="mt-2"><summary class="small" style="cursor:pointer; font-weight:700;">📖 View Model Answer</summary>' +
          '<div class="small muted mt-1" style="background:var(--surface); padding:8px; border-radius:6px; border:1px solid var(--line);">' + U.esc(q.model_answer) + '</div></details>' +
          '</div>';
      }
    });

    const summaryTarget = document.getElementById("ctest-grade-summary");
    summaryTarget.innerHTML = '<section class="panel" style="border: 2px solid var(--accent);">' +
      '<div class="plan-top"><div><h2>Test Score: ' + result.total_obtained + ' / ' + result.total_max + ' Marks (' + result.percent + '%)</h2>' +
      '<p class="muted">' + U.esc(result.overall_feedback) + '</p></div>' +
      '<span class="grade g-' + result.grade.replace("+", "p").toLowerCase() + '" style="font-size:1.6rem; padding:8px 20px;">' + result.grade + '</span></div>' +
      '<div class="btn-row mt-3"><a href="/adaptive" class="btn primary">🧠 View Adaptive Learning Matrix</a>' +
      '<a href="/books" class="btn">📖 Study with Book Teacher</a></div>' +
      '</section>';

    summaryTarget.scrollIntoView({ behavior: "smooth", block: "start" });
    document.getElementById("ctest-submit-wrap").hidden = true;
  }
})();
