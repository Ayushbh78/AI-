/* Quiz runner shared by the lesson page and the test page. */
(function () {
  const U = window.U;
  const LETTERS = ["A", "B", "C", "D"];

  async function start(box, courseId, options, onResult) {
    box.innerHTML = '<p class="muted loading">Writing questions...</p>';
    let quiz;
    try {
      quiz = await U.api("/api/courses/" + courseId + "/quiz", { json: options });
    } catch (err) {
      box.innerHTML = '<p class="error">' + U.esc(err.message) + '</p><button type="button" class="btn" id="quiz-retry">Try again</button>';
      document.getElementById("quiz-retry").addEventListener("click", function () { start(box, courseId, options, onResult); });
      return;
    }
    render(box, courseId, options, quiz, onResult);
  }

  function render(box, courseId, options, quiz, onResult) {
    const questions = quiz.questions;
    let html = '<form class="quiz" novalidate>';
    questions.forEach(function (q, i) {
      html += '<div class="q"><p class="q-text">' + (i + 1) + ". " + U.esc(q.question) + "</p>";
      q.options.forEach(function (opt, j) {
        html += '<label class="opt"><input type="radio" name="q' + i + '" value="' + j + '"><span><strong>' +
          LETTERS[j] + ".</strong> " + U.esc(opt) + "</span></label>";
      });
      html += '<div class="explain" hidden></div></div>';
    });
    html += '<div id="quiz-actions"><button class="btn primary" type="submit">Submit answers</button></div></form><div id="quiz-result"></div>';
    box.innerHTML = html;

    const form = box.querySelector("form");
    form.addEventListener("submit", async function (event) {
      event.preventDefault();
      const answers = questions.map(function (q, i) {
        const checked = form.querySelector('input[name="q' + i + '"]:checked');
        return checked ? parseInt(checked.value, 10) : null;
      });
      if (answers.some(function (a) { return a === null; })) {
        U.toast("Answer every question before submitting.");
        return;
      }
      const submit = form.querySelector("button[type=submit]");
      submit.disabled = true;
      submit.textContent = "Marking...";
      try {
        const result = await U.api("/api/courses/" + courseId + "/quiz/" + quiz.quiz_id + "/grade", { json: { answers: answers } });
        showResult(box, form, result);
        if (onResult) onResult(result);
        const actions = document.getElementById("quiz-actions");
        actions.innerHTML = '<button type="button" class="btn" id="quiz-again">Try new questions</button>';
        document.getElementById("quiz-again").addEventListener("click", function () { start(box, courseId, options, onResult); });
      } catch (err) {
        U.toast(err.message);
        submit.disabled = false;
        submit.textContent = "Submit answers";
      }
    });
  }

  function showResult(box, form, result) {
    result.questions.forEach(function (detail, i) {
      const block = form.querySelectorAll(".q")[i];
      const options = block.querySelectorAll(".opt");
      options.forEach(function (label, j) {
        label.classList.add("locked");
        label.querySelector("input").disabled = true;
        if (j === detail.answer_index) label.classList.add("correct");
        else if (j === detail.chosen) label.classList.add("wrong");
      });
      const explain = block.querySelector(".explain");
      const verdict = detail.correct ? "Correct. " : "Not quite. The right answer is " + LETTERS[detail.answer_index] + ". ";
      explain.textContent = verdict + (detail.explanation || "");
      explain.hidden = false;
    });

    let html = '<div class="result-head"><strong>' + result.score + " of " + result.total + " correct (" + result.percent + "%)</strong></div>";
    if (result.notes.length) {
      html += '<div class="result-notes">' + result.notes.map(function (n) { return "<p>" + U.esc(n) + "</p>"; }).join("") + "</div>";
    }
    if (result.topics.length) {
      html += '<ul class="result-topics">' + result.topics.map(function (t) {
        return "<li>" + U.esc(t.title) + ": scored " + t.score + "%, mastery now " + t.mastery + "%</li>";
      }).join("") + "</ul>";
    }
    const target = box.querySelector("#quiz-result");
    target.innerHTML = html;
    target.scrollIntoView({ block: "nearest" });
  }

  window.Quiz = { start: start };
})();
