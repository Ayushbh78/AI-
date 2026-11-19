/* Coding Space & Practical Lab Workspace Controller */
(function () {
  const U = window.U;
  const $ = function (id) { return document.getElementById(id); };

  const config = window.LAB_CONFIG || {};
  let exercises = config.exercises || [];
  let currentExIndex = 0;
  let activeLanguage = config.primaryLanguage || "python";
  let lastStderr = "";

  const langExtensions = {
    python: "solution.py",
    sql: "query.sql",
    javascript: "index.js",
    html: "preview.html"
  };

  // Initialize
  function init() {
    setupTabSwitching();
    setupLanguageSelector();
    setupCourseSwitcher();
    setupEditorKeys();
    setupCustomExModal();
    setupActions();

    if (exercises.length > 0) {
      selectExercise(0);
    } else {
      loadDefaultStarterCode();
    }
  }

  // Console Tab Switching
  function setupTabSwitching() {
    const tabs = document.querySelectorAll("#console-tabs .seg-btn");
    tabs.forEach(function (btn) {
      btn.addEventListener("click", function () {
        switchConsoleTab(btn.dataset.tab);
      });
    });
  }

  function switchConsoleTab(tabName) {
    document.querySelectorAll("#console-tabs .seg-btn").forEach(function (b) {
      b.classList.toggle("on", b.dataset.tab === tabName);
    });
    $("tab-stdout").hidden = tabName !== "stdout";
    $("tab-review").hidden = tabName !== "review";
    $("tab-debug").hidden = tabName !== "debug";
    $("tab-viva").hidden = tabName !== "viva";
  }

  // Language Selector
  function setupLanguageSelector() {
    const selector = $("lang-selector");
    if (selector) {
      selector.value = activeLanguage;
      selector.addEventListener("change", function () {
        activeLanguage = this.value;
        $("editor-filename").textContent = langExtensions[activeLanguage] || "code.txt";
      });
      $("editor-filename").textContent = langExtensions[activeLanguage] || "code.txt";
    }
  }

  // Course Switcher
  function setupCourseSwitcher() {
    const switcher = $("course-switcher");
    if (switcher) {
      switcher.addEventListener("change", function () {
        window.location.href = "/lab/" + this.value;
      });
    }
  }

  // Handle Tab key in editor and line counts
  function setupEditorKeys() {
    const editor = $("lab-code");
    if (!editor) return;

    editor.addEventListener("keydown", function (e) {
      // Ctrl + Enter to run code
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        e.preventDefault();
        runStudentCode();
        return;
      }

      // Tab indentation
      if (e.key === "Tab") {
        e.preventDefault();
        const start = this.selectionStart;
        const end = this.selectionEnd;
        this.value = this.value.substring(0, start) + "    " + this.value.substring(end);
        this.selectionStart = this.selectionEnd = start + 4;
        updateCursorPosition();
      }
    });

    editor.addEventListener("keyup", updateCursorPosition);
    editor.addEventListener("click", updateCursorPosition);

    $("btn-toggle-stdin").addEventListener("click", function () {
      const wrap = $("stdin-wrap");
      wrap.hidden = !wrap.hidden;
      if (!wrap.hidden) $("lab-stdin").focus();
    });

    $("btn-copy-code").addEventListener("click", function () {
      if (navigator.clipboard) {
        navigator.clipboard.writeText(editor.value).then(function () {
          U.toast("Code copied to clipboard!");
        });
      }
    });
  }

  function updateCursorPosition() {
    const editor = $("lab-code");
    const val = editor.value.substr(0, editor.selectionStart);
    const lines = val.split("\n");
    const lineNum = lines.length;
    const colNum = lines[lines.length - 1].length + 1;
    $("char-line-count").textContent = "Ln " + lineNum + ", Col " + colNum;
  }

  // Exercises List & Selection
  function renderExerciseList() {
    const listEl = $("lab-ex-list");
    if (!exercises.length) {
      listEl.innerHTML = '<div class="out-empty small-empty"><p class="muted">No exercises available.</p></div>';
      return;
    }

    listEl.innerHTML = exercises.map(function (ex, idx) {
      return '<div class="lab-ex-item ' + (idx === currentExIndex ? 'active' : '') + '" data-idx="' + idx + '">' +
        '<div class="plan-top"><span class="tag small-tag">' + U.esc(ex.difficulty || "Lab") + '</span>' +
        '<span class="small muted">' + U.esc(ex.language || "code") + '</span></div>' +
        '<strong>' + U.esc(ex.title) + '</strong>' +
        '<p class="small muted truncate-2">' + U.esc(ex.aim || "") + '</p>' +
        '</div>';
    }).join("");

    listEl.querySelectorAll(".lab-ex-item").forEach(function (item) {
      item.addEventListener("click", function () {
        selectExercise(parseInt(this.dataset.idx, 10));
      });
    });
  }

  async function selectExercise(idx) {
    if (idx < 0 || idx >= exercises.length) return;
    currentExIndex = idx;
    const ex = exercises[idx];

    // Highlight active in list
    document.querySelectorAll(".lab-ex-item").forEach(function (el, i) {
      el.classList.toggle("active", i === idx);
    });

    // Update details card
    $("ex-detail-aim").textContent = ex.aim || "Implement the solution according to specifications.";
    
    // Test cases
    const tcWrap = $("ex-test-cases-wrap");
    const tcBox = $("ex-test-cases");
    if (ex.test_cases && ex.test_cases.length) {
      tcWrap.hidden = false;
      tcBox.textContent = ex.test_cases.map(function (tc) {
        return "Input: " + (tc.input || "None") + "\nExpected: " + (tc.expected_output || "");
      }).join("\n---\n");
    } else {
      tcWrap.hidden = true;
    }

    // Update Language if specified in exercise
    if (ex.language && $("lang-selector")) {
      $("lang-selector").value = ex.language;
      activeLanguage = ex.language;
      $("editor-filename").textContent = langExtensions[activeLanguage] || "solution.txt";
    }

    // Load code: check saved draft first, fallback to starter_code
    let codeToLoad = ex.starter_code || "# Write your solution here\n";
    if (config.courseId && ex.id) {
      try {
        const draftRes = await U.api("/api/lab/draft/" + config.courseId + "/" + ex.id);
        if (draftRes && draftRes.code) {
          codeToLoad = draftRes.code;
          $("editor-status").textContent = "Loaded saved draft";
        } else {
          $("editor-status").textContent = "Loaded starter template";
        }
      } catch (e) {
        $("editor-status").textContent = "Ready";
      }
    }

    $("lab-code").value = codeToLoad;
    updateCursorPosition();

    // Populate Viva Voce tab
    renderVivaQuestions(ex.viva_questions || []);
  }

  function loadDefaultStarterCode() {
    $("lab-code").value = "# AI Vidyalaya - Interactive Coding Space\n# Write and execute your code here.\n\ndef main():\n    print('Welcome to the Coding Space!')\n\nif __name__ == '__main__':\n    main()\n";
    updateCursorPosition();
  }

  function renderVivaQuestions(vivaList) {
    const container = $("viva-questions-list");
    if (!vivaList || !vivaList.length) {
      container.innerHTML = '<p class="small muted">No specific viva voce questions defined for this experiment yet.</p>';
      return;
    }

    container.innerHTML = vivaList.map(function (v, i) {
      return '<div class="viva-item">' +
        '<div class="viva-q">Q' + (i + 1) + ': ' + U.esc(v.question) + '</div>' +
        '<details class="mt-1"><summary class="small" style="cursor:pointer; font-weight:700; color:var(--accent);">View Viva Answer</summary>' +
        '<div class="viva-a monospace-box mt-1">' + U.esc(v.answer) + '</div></details>' +
        '</div>';
    }).join("");
  }

  // Setup Actions (Run, AI Review, Debug, Save, Reset)
  function setupActions() {
    $("btn-run-code").addEventListener("click", runStudentCode);
    $("btn-ai-review").addEventListener("click", requestAiReview);
    $("btn-ai-hint").addEventListener("click", requestAiDebug);

    $("btn-save-draft").addEventListener("click", async function () {
      const ex = exercises[currentExIndex];
      const code = $("lab-code").value;
      if (!config.courseId || !ex) {
        U.toast("Draft saved locally.");
        return;
      }
      try {
        await U.api("/api/lab/save", {
          json: { course_id: config.courseId, exercise_id: ex.id, code: code }
        });
        U.toast("Code draft saved successfully!");
        $("editor-status").textContent = "Saved";
      } catch (err) {
        U.toast(err.message || "Failed to save draft.");
      }
    });

    $("btn-reset-code").addEventListener("click", function () {
      const ex = exercises[currentExIndex];
      if (!ex || !ex.starter_code) return;
      if (confirm("Reset code to the original starter template? Unsaved changes will be replaced.")) {
        $("lab-code").value = ex.starter_code;
        $("editor-status").textContent = "Reset to template";
        updateCursorPosition();
      }
    });

    const genFirstBtn = $("btn-gen-first-ex");
    if (genFirstBtn) {
      genFirstBtn.addEventListener("click", function () {
        showCustomModal();
      });
    }
  }

  // ================= 1. RUN CODE =================
  async function runStudentCode() {
    const btn = $("btn-run-code");
    const code = $("lab-code").value;
    const stdin = $("lab-stdin") ? $("lab-stdin").value : "";
    const statusDot = $("exec-status-dot");
    const statusText = $("exec-status-text");
    const durationBadge = $("exec-duration-badge");
    const stdoutEl = $("terminal-stdout");
    const stderrEl = $("terminal-stderr");
    const previewEl = $("terminal-preview");
    const placeholder = $("terminal-placeholder");

    switchConsoleTab("stdout");
    placeholder.hidden = true;
    stdoutEl.hidden = true;
    stderrEl.hidden = true;
    previewEl.hidden = true;

    btn.disabled = true;
    btn.textContent = "Executing...";
    statusDot.className = "status-indicator running";
    statusText.textContent = "Running in isolated sandbox...";
    durationBadge.hidden = true;

    try {
      const res = await U.api("/api/lab/run", {
        json: {
          language: activeLanguage,
          code: code,
          stdin: stdin
        },
        timeout: 20000
      });

      lastStderr = res.stderr || "";

      if (activeLanguage === "html" && res.html_preview) {
        previewEl.hidden = false;
        previewEl.srcdoc = res.html_preview;
        statusDot.className = "status-indicator ok";
        statusText.textContent = "Web preview rendered.";
      } else {
        if (res.stdout) {
          stdoutEl.hidden = false;
          stdoutEl.textContent = res.stdout;
        }
        if (res.stderr) {
          stderrEl.hidden = false;
          stderrEl.textContent = res.stderr;
        }
        if (!res.stdout && !res.stderr) {
          stdoutEl.hidden = false;
          stdoutEl.textContent = "(Program exited with code " + res.exit_code + " and produced no output)";
        }

        statusDot.className = res.ok ? "status-indicator ok" : "status-indicator error";
        statusText.textContent = res.ok ? "Execution successful (Exit 0)" : "Execution finished with errors";
      }

      durationBadge.hidden = false;
      durationBadge.textContent = (res.duration_ms || 0) + " ms";
    } catch (err) {
      stderrEl.hidden = false;
      stderrEl.textContent = "Execution Error: " + err.message;
      statusDot.className = "status-indicator error";
      statusText.textContent = "Execution failed";
      lastStderr = err.message;
    } finally {
      btn.disabled = false;
      btn.textContent = "▶ Run Code";
    }
  }

  // ================= 2. AI CODE REVIEW =================
  async function requestAiReview() {
    const code = $("lab-code").value.trim();
    if (!code) {
      U.toast("Please write some code before requesting review.");
      return;
    }

    const ex = exercises[currentExIndex] || {};
    switchConsoleTab("review");

    $("review-empty").hidden = true;
    $("review-content").hidden = true;
    $("review-loading").hidden = false;

    try {
      const res = await U.api("/api/lab/review", {
        json: {
          code: code,
          aim: ex.aim || "Practical Problem Implementation",
          exercise_title: ex.title || "Lab Exercise",
          language: activeLanguage
        },
        timeout: 90000
      });

      $("review-loading").hidden = true;
      $("review-content").hidden = false;

      // Populate Score & Complexity
      $("review-score").textContent = (res.score || 0) + " / 10 Marks";
      $("review-verdict").textContent = res.verdict || "Reviewed";
      $("review-time-comp").textContent = "Time: " + (res.time_complexity || "N/A");
      $("review-space-comp").textContent = "Space: " + (res.space_complexity || "N/A");

      // Strengths
      const strList = $("review-strengths");
      strList.innerHTML = (res.strengths || []).map(function (s) {
        return "<li>" + U.esc(s) + "</li>";
      }).join("") || "<li>Clean implementation addressing the problem statement.</li>";

      // Improvements
      const impList = $("review-improvements");
      impList.innerHTML = (res.improvements || []).map(function (im) {
        return "<li>" + U.esc(im) + "</li>";
      }).join("") || "<li>No major issues found. Good work!</li>";

      // Model Code
      $("review-model-code").textContent = res.model_code_suggestion || code;

      // Viva Tip
      $("review-viva-tip").textContent = res.viva_tip || "Be ready to explain your algorithmic steps clearly.";

    } catch (err) {
      $("review-loading").hidden = true;
      $("review-empty").hidden = false;
      U.toast(err.message || "Failed to get AI review.");
    }
  }

  // ================= 3. SOCRATIC DEBUGGER =================
  async function requestAiDebug() {
    const code = $("lab-code").value.trim();
    const ex = exercises[currentExIndex] || {};
    switchConsoleTab("debug");

    $("debug-empty").hidden = true;
    $("debug-content").hidden = true;
    $("debug-loading").hidden = false;

    try {
      const res = await U.api("/api/lab/debug", {
        json: {
          code: code,
          error_message: lastStderr || "Code gave unexpected output or was stuck.",
          aim: ex.aim || "Implement solution",
          language: activeLanguage
        },
        timeout: 90000
      });

      $("debug-loading").hidden = true;
      $("debug-content").hidden = false;

      $("debug-error-type").textContent = res.error_type || "Issue Identified";
      $("debug-diagnosis").textContent = res.diagnosis || "Review the logic in your implementation.";
      $("debug-line-hint").textContent = res.line_hint || "Check your conditional branches and variable initialization.";

      const hintsList = $("debug-hints-list");
      hintsList.innerHTML = (res.hints || []).map(function (h) {
        return "<li>" + U.esc(h) + "</li>";
      }).join("");

      $("debug-quick-tip").textContent = res.quick_fix_tip || "Print out your variables to trace execution.";

    } catch (err) {
      $("debug-loading").hidden = true;
      $("debug-empty").hidden = false;
      U.toast(err.message || "Failed to analyze bug.");
    }
  }

  // ================= 4. CUSTOM EXERCISE MODAL =================
  function setupCustomExModal() {
    const modal = $("custom-ex-modal");
    const openBtn = $("btn-add-custom-ex");
    const closeBtn = $("custom-modal-close");
    const cancelBtn = $("custom-modal-cancel");
    const backdrop = $("custom-modal-backdrop");
    const form = $("custom-ex-form");

    function showModal() {
      modal.hidden = false;
      document.body.classList.add("modal-open");
      $("custom-topic-input").focus();
    }
    function hideModal() {
      modal.hidden = true;
      document.body.classList.remove("modal-open");
    }

    if (openBtn) openBtn.addEventListener("click", showModal);
    if (closeBtn) closeBtn.addEventListener("click", hideModal);
    if (cancelBtn) cancelBtn.addEventListener("click", hideModal);
    if (backdrop) backdrop.addEventListener("click", hideModal);

    form.addEventListener("submit", async function (e) {
      e.preventDefault();
      const topic = $("custom-topic-input").value.trim();
      const lang = $("custom-lang-select").value;
      if (!topic) return;

      const submitBtn = $("custom-modal-submit");
      submitBtn.disabled = true;
      submitBtn.textContent = "Synthesizing challenge...";

      try {
        const res = await U.api("/api/lab/generate_exercise", {
          json: {
            course_id: config.courseId,
            topic: topic,
            language: lang
          },
          timeout: 90000
        });

        if (res && res.exercise) {
          exercises.push(res.exercise);
          renderExerciseList();
          selectExercise(exercises.length - 1);
          hideModal();
          form.reset();
          U.toast("New laboratory exercise synthesized successfully!");
        }
      } catch (err) {
        U.toast(err.message || "Failed to generate exercise.");
      } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = "✨ Synthesize Challenge";
      }
    });
  }

  // Start initialization
  init();
})();
