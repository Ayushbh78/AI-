/* Book Teacher & On-page Test Runner */
(function () {
  const U = window.U;
  const $ = function (id) { return document.getElementById(id); };

  let currentBook = null;
  let currentBooksList = [];
  let activeTeacherMode = "teach";

  // Tab switching
  const tabButtons = document.querySelectorAll("#book-tabs .seg-btn");
  tabButtons.forEach(function (btn) {
    btn.addEventListener("click", function () {
      tabButtons.forEach(function (b) { b.classList.remove("on"); });
      btn.classList.add("on");
      const tab = btn.dataset.tab;
      $("tab-teacher").hidden = tab !== "teacher";
      $("tab-summarizer").hidden = tab !== "summarizer";
    });
  });

  // Teacher mode switching
  const modeButtons = document.querySelectorAll("#teacher-mode-seg .seg-btn");
  modeButtons.forEach(function (btn) {
    btn.addEventListener("click", function () {
      modeButtons.forEach(function (b) { b.classList.remove("on"); });
      btn.classList.add("on");
      activeTeacherMode = btn.dataset.mode;
    });
  });

  // Modal Upload Dialog
  const uploadModal = $("upload-modal");
  function showUploadModal() {
    uploadModal.hidden = false;
    document.body.classList.add("modal-open");
  }
  function hideUploadModal() {
    uploadModal.hidden = true;
    document.body.classList.remove("modal-open");
  }

  $("btn-upload-modal").addEventListener("click", showUploadModal);
  if ($("modal-upload-close")) $("modal-upload-close").addEventListener("click", hideUploadModal);
  $("modal-upload-cancel").addEventListener("click", hideUploadModal);
  $("upload-backdrop").addEventListener("click", hideUploadModal);
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !uploadModal.hidden) {
      hideUploadModal();
    }
  });

  // Auto-fill title from filename
  $("modal-book-file").addEventListener("change", function () {
    const f = this.files[0];
    if (f && !$("modal-book-title").value.trim()) {
      const clean = f.name.replace(/\.[^/.]+$/, "").replace(/[-_]/g, " ");
      $("modal-book-title").value = clean.charAt(0).toUpperCase() + clean.slice(1);
    }
  });

  $("upload-book-form").addEventListener("submit", async function (e) {
    e.preventDefault();
    const file = $("modal-book-file").files[0];
    if (!file) {
      U.toast("Please select a file to upload.");
      return;
    }
    if (!/\.(pdf|txt|md)$/i.test(file.name || "")) {
      U.toast("Please choose a PDF, TXT or MD file.");
      return;
    }
    if (file.size > 25 * 1024 * 1024) {
      U.toast("This file is " + Math.round(file.size / 1048576) + " MB. The limit is 25 MB.");
      return;
    }
    const btn = $("modal-upload-submit");
    btn.disabled = true;
    btn.textContent = "Uploading… please wait";
    const stepTimer = setTimeout(function () { btn.textContent = "Reading pages…"; }, 4000);
    const fd = new FormData();
    fd.append("file", file);
    fd.append("title", $("modal-book-title").value);
    fd.append("author", $("modal-book-author").value);

    try {
      const res = await U.api("/api/books/upload", { method: "POST", body: fd, timeout: 180000 });
      U.toast("Book added! (" + (res.book.chunk_count || 0) + " passages)");
      hideUploadModal();
      $("upload-book-form").reset();
      await loadBooksList();
      selectBook(res.book.id);
    } catch (err) {
      U.toast(err.message || "Failed to upload book");
    } finally {
      clearTimeout(stepTimer);
      btn.disabled = false;
      btn.textContent = "Index & Add Book";
    }
  });

  // Load books
  async function loadBooksList() {
    try {
      const res = await U.api("/api/books/list");
      currentBooksList = res.books || [];
      renderBooksPicker(currentBooksList);
      if (currentBooksList.length && !currentBook) {
        selectBook(currentBooksList[0].id);
      }
    } catch (err) {
      $("book-picker-list").innerHTML = '<p class="error">Could not load books: ' + U.esc(err.message) + '</p>';
    }
  }

  function renderBooksPicker(books) {
    const list = $("book-picker-list");
    $("books-count-label").textContent = books.length + " books available";
    let html = '';
    
    // Upload Action Card
    html += '<div class="book-card" id="card-upload-trigger" style="border: 2px dashed var(--accent); background: var(--bg); display:flex; align-items:center; justify-content:center; text-align:center; min-height: 120px;">' +
      '<div><div style="font-size: 1.8rem; margin-bottom: 4px;">➕</div>' +
      '<strong>Upload New Book</strong>' +
      '<div class="small muted mt-1">PDF, TXT, or MD</div></div>' +
      '</div>';

    html += books.map(function (b) {
      const isSel = currentBook && currentBook.id === b.id;
      return '<div class="book-card ' + (isSel ? 'selected' : '') + '" data-id="' + b.id + '">' +
        '<div><span class="tag">' + U.esc(b.category) + '</span>' +
        '<h4>' + U.esc(b.title) + '</h4>' +
        '<p class="small muted">' + U.esc(b.author) + ' · ' + b.chunk_count + ' passages</p></div>' +
        '<div class="mt-2"><span class="small ' + (b.is_curated ? 'ok-text' : 'muted') + '">' + (b.is_curated ? '✓ Verified Textbook' : 'Uploaded Book') + '</span></div>' +
        '</div>';
    }).join("");

    list.innerHTML = html;

    const upCard = $("card-upload-trigger");
    if (upCard) {
      upCard.addEventListener("click", showUploadModal);
    }

    list.querySelectorAll(".book-card[data-id]").forEach(function (card) {
      card.addEventListener("click", function () {
        selectBook(card.dataset.id, true);
      });
    });
  }

  function selectBook(bookId, userInitiated) {
    currentBook = currentBooksList.find(function (b) { return b.id === bookId; });
    if (!currentBook) return;

    document.querySelectorAll("#book-picker-list .book-card[data-id]").forEach(function (card) {
      card.classList.toggle("selected", card.dataset.id === currentBook.id);
    });
    const studio = $("active-book-studio");
    studio.hidden = false;
    $("ab-title").textContent = currentBook.title;
    $("ab-author").textContent = currentBook.author + " · " + (currentBook.chunk_count || "") + " indexed sections";
    $("ab-category").textContent = currentBook.category;

    // Render chapters
    const chWrap = $("ab-chapters");
    const chapters = currentBook.chapters || [];
    if (chapters.length) {
      chWrap.innerHTML = chapters.map(function (ch) {
        return '<button type="button" class="ch-chip" data-title="' + U.esc(ch.title) + '">' +
          (ch.number ? 'Ch ' + ch.number + ': ' : '') + U.esc(ch.title) + '</button>';
      }).join("");

      chWrap.querySelectorAll(".ch-chip").forEach(function (chip) {
        chip.addEventListener("click", function () {
          $("teacher-topic-input").value = chip.dataset.title;
          triggerTeaching(chip.dataset.title);
        });
      });
    } else {
      chWrap.innerHTML = '<span class="small muted">Click Teach to explore key sections.</span>';
    }

    // Hide previous test if open
    $("book-test-section").hidden = true;

    if (userInitiated) {
      studio.scrollIntoView({ block: "start" });
    }
  }

  // Teacher Form Submission
  $("teacher-form").addEventListener("submit", function (e) {
    e.preventDefault();
    const topic = $("teacher-topic-input").value.trim();
    if (!topic) {
      U.toast("Please enter a topic or select a chapter.");
      return;
    }
    triggerTeaching(topic);
  });

  async function triggerTeaching(topic) {
    if (!currentBook) return;
    const empty = $("teacher-empty");
    const loading = $("teacher-loading");
    const result = $("teacher-result");
    const body = $("teacher-body");
    const citationsList = $("citations-list");
    const submitBtn = $("btn-teach-submit");

    empty.hidden = true;
    result.hidden = true;
    loading.hidden = false;
    submitBtn.disabled = true;

    try {
      const res = await U.api("/api/books/teach", {
        json: {
          book_id: currentBook.id,
          topic: topic,
          mode: activeTeacherMode
        },
        timeout: 180000
      });

      $("lesson-topic-title").textContent = res.topic + " (" + res.mode.toUpperCase() + ")";
      body.innerHTML = U.md(res.teaching);

      // Render Citations
      const citations = res.citations || [];
      if (citations.length) {
        citationsList.innerHTML = citations.map(function (c) {
          return '<div class="citation-item">' +
            '<div class="citation-page">📖 Page ' + c.page + ' (Relevance: ' + Math.round((c.score || 1) * 100) / 100 + ')</div>' +
            '<div class="small mt-1">"' + U.esc(c.excerpt) + '"</div>' +
            '</div>';
        }).join("");
      } else {
        citationsList.innerHTML = '<p class="small muted">No direct page excerpts retrieved.</p>';
      }

      loading.hidden = true;
      result.hidden = false;
      result.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (err) {
      loading.hidden = true;
      empty.hidden = false;
      U.toast(err.message || "Failed to teach topic.");
    } finally {
      submitBtn.disabled = false;
    }
  }

  // Copy lesson
  $("btn-copy-lesson").addEventListener("click", function () {
    U.copyText($("teacher-body").innerText).then(function (ok) {
      U.toast(ok ? "Lesson copied!" : "Could not copy. Press and hold the text to copy it.");
    });
  });

  // ================= ON-PAGE BOOK TEST RUNNER =================
  $("btn-start-book-test").addEventListener("click", async function () {
    if (!currentBook) return;
    const testSec = $("book-test-section");
    const loading = $("test-loading");
    const container = $("test-runner-container");

    testSec.hidden = false;
    loading.hidden = false;
    container.innerHTML = "";
    testSec.scrollIntoView({ behavior: "smooth", block: "start" });

    try {
      const res = await U.api("/api/books/generate_test", {
        json: {
          book_id: currentBook.id,
          scope: $("teacher-topic-input").value.trim() || "all",
          count: 5,
          test_type: "mixed"
        },
        timeout: 180000
      });
      loading.hidden = true;
      renderBookTest(res, container);
    } catch (err) {
      loading.hidden = true;
      container.innerHTML = '<p class="error">Could not generate test: ' + U.esc(err.message) + '</p>';
    }
  });

  $("btn-close-test").addEventListener("click", function () {
    $("book-test-section").hidden = true;
  });

  function renderBookTest(testData, container) {
    const questions = testData.questions || [];
    let html = '<form id="book-test-form" novalidate>';
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
        html += '<label class="small muted">Type your complete answer below (evaluated by AI):</label>';
        html += '<textarea class="test-sub-input" name="ans_' + q.id + '" placeholder="Write your full explanation, steps, or definitions here..."></textarea>';
      }

      html += '<div class="eval-result-area" hidden></div>';
      html += '</div>';
    });

    html += '<div class="mt-3" id="test-submit-bar"><button type="submit" class="btn primary wide" id="btn-submit-test">✨ Submit Answers for AI Evaluation</button></div>';
    html += '</form><div id="test-grade-summary" class="mt-3"></div>';

    container.innerHTML = html;

    const form = $("book-test-form");
    form.addEventListener("submit", async function (e) {
      e.preventDefault();
      const submitBtn = $("btn-submit-test");
      submitBtn.disabled = true;
      submitBtn.textContent = "AI Examiner is grading complete answers...";

      // Gather answers
      const answers = {};
      questions.forEach(function (q) {
        if (q.type === "mcq") {
          const checked = form.querySelector('input[name="ans_' + q.id + '"]:checked');
          answers[q.id] = checked ? parseInt(checked.value, 10) : null;
        } else {
          const ta = form.querySelector('textarea[name="ans_' + q.id + '"]');
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

        displayTestResults(gradeRes, form, container);
      } catch (err) {
        U.toast(err.message || "Failed to grade test.");
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

    // Overall scorecard
    const summaryTarget = $("test-grade-summary");
    summaryTarget.innerHTML = '<section class="panel" style="border: 2px solid var(--accent);">' +
      '<div class="plan-top"><div><h2>Result: ' + result.total_obtained + ' / ' + result.total_max + ' Marks (' + result.percent + '%)</h2>' +
      '<p class="muted">' + U.esc(result.overall_feedback) + '</p></div>' +
      '<span class="grade g-' + result.grade.replace("+", "p").toLowerCase() + '" style="font-size:1.6rem; padding:8px 20px;">' + result.grade + '</span></div>' +
      '<div class="btn-row mt-3"><button type="button" class="btn primary" onclick="document.getElementById(\'btn-start-book-test\').click()">🔄 Take Another Test</button>' +
      '<a href="/adaptive" class="btn">🧠 View Adaptive Learning Matrix</a></div>' +
      '</section>';

    summaryTarget.scrollIntoView({ behavior: "smooth", block: "start" });
    $("test-submit-bar").hidden = true;
  }

  // Initial load
  loadBooksList();
})();
