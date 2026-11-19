/* Notes, Books, Exam Paper and Library pages. */
(function () {
  const U = window.U;
  const $ = function (id) { return document.getElementById(id); };
  const esc = U.esc;

  /* ---------- segmented buttons ---------- */
  function segValue(name) {
    const on = document.querySelector('[data-seg="' + name + '"] .seg-btn.on');
    return on ? on.dataset.value : "";
  }
  document.querySelectorAll("[data-seg]").forEach(function (group) {
    group.addEventListener("click", function (event) {
      const b = event.target.closest(".seg-btn");
      if (!b) return;
      group.querySelectorAll(".seg-btn").forEach(function (x) { x.classList.toggle("on", x === b); });
      group.dispatchEvent(new CustomEvent("seg", { detail: b.dataset.value }));
    });
  });

  /* ---------- exam paper renderer (also used by the Library) ---------- */
  function renderPaper(p) {
    const L = ["A", "B", "C", "D"];
    let html = '<div class="paper"><header class="paper-head"><h2>' + esc(p.title || (p.subject + " question paper")) + "</h2>" +
      (p.subtitle ? '<p class="muted">' + esc(p.subtitle) + "</p>" : "") +
      '<div class="paper-meta"><span>Time: ' + esc(p.minutes || "") + " minutes</span><span>Maximum marks: " + esc(p.total_marks) + "</span></div></header>";
    if (p.instructions && p.instructions.length) {
      html += '<div class="paper-instr"><strong>General instructions</strong><ol>' + p.instructions.map(function (i) { return "<li>" + esc(i) + "</li>"; }).join("") + "</ol></div>";
    }
    p.sections.forEach(function (s) {
      html += '<section class="paper-sec"><h3>' + esc(s.name) + "</h3>" + (s.instructions ? '<p class="small muted">' + esc(s.instructions) + "</p>" : "");
      s.questions.forEach(function (q) {
        html += '<div class="pq"><span class="qn">' + q.no + '.</span><div class="qbody"><p><span class="qtext">' + esc(q.text) + '</span><span class="marks">[' + q.marks + "]</span></p>";
        if (q.options) html += '<ol class="pq-opts" type="A">' + q.options.map(function (o, i) { return "<li><b>" + L[i] + ".</b> " + esc(o) + "</li>"; }).join("") + "</ol>";
        if (q.answer) html += '<div class="pq-answer"><strong>Answer:</strong> ' + esc(q.answer) + "</div>";
        html += "</div></div>";
      });
      html += "</section>";
    });
    return html + "</div>";
  }
  function bindAnswers(btn, body) {
    btn.hidden = false;
    btn.textContent = "Show answers";
    body.classList.remove("show-answers");
    btn.onclick = function () {
      const on = body.classList.toggle("show-answers");
      btn.textContent = on ? "Hide answers" : "Show answers";
    };
  }

  function copyText(text, btn) {
    function done() { const t = btn.textContent; btn.textContent = "Copied"; setTimeout(function () { btn.textContent = t; }, 1500); }
    if (navigator.clipboard && window.isSecureContext) { navigator.clipboard.writeText(text).then(done, done); return; }
    const ta = document.createElement("textarea");
    ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select();
    try { document.execCommand("copy"); } catch (e) { /* ignore */ }
    document.body.removeChild(ta); done();
  }

  /* ---------- generator pages ---------- */
  const form = $("tool-form");
  if (form) {
    const tool = form.dataset.tool;
    const out = { empty: $("out-empty"), loading: $("out-loading"), text: $("out-loading-text"), error: $("out-error"),
                  result: $("out-result"), body: $("out-body"), answers: $("act-answers") };
    let plain = "";
    const messages = {
      notes: "Searching trusted sources and writing your notes… about 15 to 30 seconds.",
      books: "Reading about the book and writing the summary… about 15 to 30 seconds.",
      paper: "Setting your question paper and answer key… this can take up to a minute.",
    };
    function state(name) {
      out.empty.hidden = name !== "empty"; out.loading.hidden = name !== "loading";
      out.error.hidden = name !== "error"; out.result.hidden = name !== "result";
    }
    document.querySelectorAll("[data-idea]").forEach(function (c) {
      c.addEventListener("click", function () { $("topic").value = c.dataset.idea; window.U.focusDesktop($("topic")); });
    });
    const modeGroup = document.querySelector('[data-seg="mode"]');
    if (modeGroup) modeGroup.addEventListener("seg", function (e) {
      $("file-wrap").hidden = e.detail !== "file";
      $("title-wrap").querySelector("input").placeholder = e.detail === "file" ? "Book title (optional, taken from the file name)" : "e.g. Atomic Habits, Wings of Fire";
    });
    $("act-copy").addEventListener("click", function () { copyText(plain || out.body.innerText, $("act-copy")); });

    form.addEventListener("submit", async function (event) {
      event.preventDefault();
      const btn = $("go-btn");
      btn.disabled = true; out.text.textContent = messages[tool]; state("loading");
      try {
        let data;
        if (tool === "notes") {
          data = await U.api("/api/notes", { timeout: 170000, json: { topic: $("topic").value, target: $("target").value, depth: segValue("depth") } });
        } else if (tool === "books") {
          const file = $("book-file").files[0];
          if (segValue("mode") === "file" && file) {
            const fd = new FormData();
            fd.append("file", file); fd.append("title", $("book-title").value); fd.append("author", $("author").value);
            fd.append("style", segValue("style")); 
            data = await U.api("/api/books", { method: "POST", body: fd, timeout: 170000 });
          } else {
            data = await U.api("/api/books", { timeout: 170000, json: { title: $("book-title").value, author: $("author").value, style: segValue("style") } });
          }
        } else {
          data = await U.api("/api/paper", { timeout: 170000, json: { subject: $("p-subject").value, topics: $("p-topics").value, pattern: $("p-pattern").value,
            marks: $("p-marks").value, minutes: $("p-minutes").value, difficulty: segValue("difficulty") } });
        }
        if (tool === "paper") {
          out.body.innerHTML = renderPaper(data.paper);
          bindAnswers(out.answers, out.body);
          plain = out.body.innerText;
        } else {
          out.answers.hidden = true;
          out.body.innerHTML = U.md(data.markdown);
          plain = data.markdown;
        }
        state("result");
        out.result.scrollIntoView({ behavior: "smooth", block: "start" });
      } catch (err) {
        out.error.textContent = err.message; state("error");
      } finally { btn.disabled = false; }
    });
  }

  /* ---------- library ---------- */
  const dataEl = $("lib-data");
  if (dataEl) {
    let items = JSON.parse(dataEl.textContent);
    const list = $("lib-list"), empty = $("lib-empty"), modal = $("lib-modal"), body = $("out-body");
    const icon = { notes: "📝", book: "📖", paper: "📄" };
    const label = { notes: "Notes", book: "Book summary", paper: "Exam paper" };
    let filter = "all", query = "", current = null;

    function ago(iso) {
      const d = new Date(iso), days = Math.floor((Date.now() - d.getTime()) / 86400000);
      return days <= 0 ? "Today" : days === 1 ? "Yesterday" : d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
    }
    function render() {
      const q = query.toLowerCase();
      const shown = items.filter(function (i) {
        if (filter === "star" && !i.bookmarked) return false;
        if (filter !== "all" && filter !== "star" && i.type !== filter) return false;
        return !q || (i.title + " " + JSON.stringify(i.meta || {})).toLowerCase().indexOf(q) !== -1;
      });
      list.innerHTML = shown.map(function (i) {
        const m = i.meta || {};
        const sub = [label[i.type], m.target || m.author || m.pattern, m.marks ? m.marks + " marks" : ""].filter(Boolean).join(" · ");
        return '<article class="lib-item" data-id="' + i.id + '"><button type="button" class="lib-open" data-open="' + i.id + '">' +
          '<span class="lib-ico">' + icon[i.type] + '</span><span class="lib-main"><strong>' + esc(i.title) + '</strong><span class="small muted">' + esc(sub) +
          " · " + ago(i.created) + "</span></span></button>" +
          '<button type="button" class="icon-btn star' + (i.bookmarked ? " on" : "") + '" data-star="' + i.id + '" aria-label="Save">' + (i.bookmarked ? "★" : "☆") + "</button>" +
          '<button type="button" class="icon-btn" data-del="' + i.id + '" aria-label="Delete">🗑</button></article>';
      }).join("");
      empty.hidden = items.length > 0;
      list.hidden = !shown.length;
      if (items.length && !shown.length) list.innerHTML = '<p class="muted center">No matches.</p>', list.hidden = false;
    }
    $("lib-search").addEventListener("input", function (e) { query = e.target.value.trim(); render(); });
    $("lib-filter").addEventListener("seg", function (e) { filter = e.detail; render(); });

    list.addEventListener("click", async function (event) {
      const open = event.target.closest("[data-open]"), star = event.target.closest("[data-star]"), del = event.target.closest("[data-del]");
      try {
        if (open) {
          const item = await U.api("/api/library/" + open.dataset.open);
          current = item;
          $("lib-title").textContent = item.title;
          if (item.type === "paper") { body.innerHTML = renderPaper(item.content); bindAnswers($("act-answers"), body); }
          else { body.innerHTML = U.md(item.content); $("act-answers").hidden = true; }
          modal.hidden = false; document.body.classList.add("modal-open");
        } else if (star) {
          const r = await U.api("/api/library/" + star.dataset.star + "/bookmark", { json: {} });
          items.forEach(function (i) { if (i.id === star.dataset.star) i.bookmarked = r.bookmarked; });
          render();
        } else if (del) {
          if (!window.confirm("Delete this from your library?")) return;
          await U.api("/api/library/" + del.dataset.del, { method: "DELETE" });
          items = items.filter(function (i) { return i.id !== del.dataset.del; });
          render(); U.toast("Deleted.");
        }
      } catch (err) { U.toast(err.message); }
    });
    function close() { modal.hidden = true; document.body.classList.remove("modal-open"); }
    modal.addEventListener("click", function (e) { if (e.target.closest("[data-close]")) close(); });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !modal.hidden) close(); });
    $("lib-copy").addEventListener("click", function () { copyText(current && current.type !== "paper" ? current.content : body.innerText, $("lib-copy")); });
    render();
  }
})();
