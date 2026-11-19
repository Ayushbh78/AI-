(function () {
  const U = window.U;
  const boot = JSON.parse(document.getElementById("boot").textContent);
  const base = "/api/courses/" + boot.courseId;

  const body = document.getElementById("lesson-body");
  const sourcesBox = document.getElementById("lesson-sources");
  const quizCard = document.getElementById("quiz-card");
  const quizBox = document.getElementById("quiz-box");
  const startQuiz = document.getElementById("start-quiz");
  const completeBtn = document.getElementById("complete-btn");
  const regenBtn = document.getElementById("regen-btn");
  const masteryLine = document.getElementById("mastery-line");

  /* ----- lesson ----- */
  function showLesson(lesson) {
    body.innerHTML = U.md(lesson.markdown);
    const cardsPanel = document.getElementById("cards-panel");
    if (cardsPanel && lesson.cards && lesson.cards.length && window.Rote) {
      cardsPanel.hidden = false;
      window.Rote.mount(document.getElementById("cards-box"), lesson.cards);
    }
    if (lesson.sources && lesson.sources.length) {
      sourcesBox.innerHTML = "<h3>From your study material</h3><ol>" + lesson.sources.map(function (s) {
        return "<li><strong>Source " + s.n + ":</strong> " + U.esc(s.name) + ", page " + s.page + ". " + U.esc(s.snippet) + "...</li>";
      }).join("") + "</ol>";
      sourcesBox.hidden = false;
    } else {
      sourcesBox.hidden = true;
    }
  }

  async function loadLesson(refresh) {
    body.innerHTML = '<p class="muted loading">' + (refresh ? "Rewriting the lesson." : "Preparing your lesson. This takes a few seconds the first time.") + "</p>";
    regenBtn.disabled = true;
    try {
      showLesson(await U.api(base + "/topics/" + boot.topicId + "/lesson", { json: { refresh: !!refresh } }));
      if (boot.autoQuiz && !refresh) { boot.autoQuiz = false; runQuiz(); }
    } catch (err) {
      body.innerHTML = '<p class="error">' + U.esc(err.message) + '</p><button type="button" class="btn" id="lesson-retry">Try again</button>';
      document.getElementById("lesson-retry").addEventListener("click", function () { loadLesson(false); });
    } finally {
      regenBtn.disabled = false;
    }
  }

  if (boot.rote) regenBtn.hidden = true;
  regenBtn.addEventListener("click", function () { loadLesson(true); });

  /* ----- quiz ----- */
  function runQuiz() {
    quizCard.hidden = false;
    quizCard.scrollIntoView({ behavior: "smooth", block: "start" });
    window.Quiz.start(quizBox, boot.courseId, { topic_ids: [boot.topicId], count: 4, kind: "lesson" }, function (result) {
      const t = result.topics.find(function (x) { return x.id === boot.topicId; });
      if (t) masteryLine.textContent = "Mastery on this topic: " + t.mastery + "%";
    });
  }
  startQuiz.addEventListener("click", runQuiz);

  /* ----- complete ----- */
  if (boot.done) completeBtn.classList.add("quiet");
  completeBtn.addEventListener("click", async function () {
    completeBtn.disabled = true;
    try {
      const result = await U.api(base + "/topics/" + boot.topicId + "/complete", { json: {} });
      U.toast("Topic marked complete.");
      setTimeout(function () { window.location.href = result.next_url; }, 600);
    } catch (err) {
      U.toast(err.message);
      completeBtn.disabled = false;
    }
  });

  /* ----- ask a question ----- */
  const log = document.getElementById("chat-log");
  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");
  const send = document.getElementById("chat-send");

  function addBubble(role, html) {
    const div = document.createElement("div");
    div.className = "bubble " + role;
    div.innerHTML = html;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
    return div;
  }

  (boot.chat || []).forEach(function (turn) {
    if (turn.role === "user") addBubble("user", "<p>" + U.esc(turn.text) + "</p>");
    else addBubble("model", U.md(turn.text));
  });

  form.addEventListener("submit", async function (event) {
    event.preventDefault();
    const message = input.value.trim();
    if (!message) return;
    addBubble("user", "<p>" + U.esc(message) + "</p>");
    input.value = "";
    send.disabled = true;
    const pending = addBubble("model", '<p class="muted loading">Thinking...</p>');
    try {
      const data = await U.api(base + "/ask", { json: { topic_id: boot.topicId, message: message } });
      await U.typeMd(pending, data.answer, function () { log.scrollTop = log.scrollHeight; });
    } catch (err) {
      pending.innerHTML = '<p class="error">' + U.esc(err.message) + "</p>";
    } finally {
      send.disabled = false;
      log.scrollTop = log.scrollHeight;
      U.focusDesktop(input);
    }
  });

  input.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  /* ----- go ----- */
  if (boot.lesson) {
    showLesson(boot.lesson);
    if (boot.autoQuiz) { boot.autoQuiz = false; runQuiz(); }
  } else {
    loadLesson(false);
  }
})();
