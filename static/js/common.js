/* Shared helpers: api(), toast(), md() */
(function () {
  function esc(value) {
    return String(value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  /* Remember me: the server keeps the login cookie for 90 days. A second copy (signed token) is kept on the phone,
     so the person stays logged in even if the app or browser drops its cookies. */
  const TOKEN_KEY = "vidyalaya_remember";
  function saveToken(token) { try { if (token) localStorage.setItem(TOKEN_KEY, token); } catch (e) { /* private mode */ } }
  function clearToken() { try { localStorage.removeItem(TOKEN_KEY); } catch (e) { /* ignore */ } }
  function getToken() { try { return localStorage.getItem(TOKEN_KEY) || ""; } catch (e) { return ""; } }
  async function resumeLogin() {
    const token = getToken();
    if (!token) return false;
    try {
      const res = await fetch("/api/resume", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token: token }), credentials: "same-origin" });
      if (res.ok) { const d = await res.json(); if (d && d.token) saveToken(d.token); return true; }
      if (res.status === 401) clearToken();
    } catch (e) { /* offline: keep the token and try again next time */ }
    return false;
  }

  /* Phones and tablets: do not pop the keyboard open on its own. Only desktops auto-focus. */
  const isTouch = !!(window.matchMedia && window.matchMedia("(pointer: coarse), (hover: none)").matches);
  function focusDesktop(el) { if (el && !isTouch) { try { el.focus({ preventScroll: true }); } catch (e) { el.focus(); } } }

  async function api(url, options) {
    const opts = Object.assign({ headers: {} }, options || {});
    const retried = !!opts._retried;
    delete opts._retried;
    if (opts.json !== undefined) {
      opts.method = opts.method || "POST";
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(opts.json);
      delete opts.json;
    }
    const controller = new AbortController();
    const limit = opts.timeout || 150000;
    delete opts.timeout;
    opts.signal = controller.signal;
    const timer = setTimeout(function () { controller.abort(); }, limit);
    let res;
    try {
      res = await fetch(url, opts);
    } catch (err) {
      if (err && err.name === "AbortError") {
        throw new Error("This is taking too long, so it was stopped. Check your internet and try again.");
      }
      throw new Error("No connection to the app. Check your internet and try again.");
    } finally {
      clearTimeout(timer);
    }
    let data = null;
    try { data = await res.json(); } catch (err) { /* not JSON */ }
    if (res.status === 401 && !/\/api\/(login|signup|resume)$/.test(url)) {
      if (!retried && await resumeLogin()) { return api(url, Object.assign({}, options, { _retried: true })); }
      window.location.href = "/";
    }
    if (!res.ok) throw new Error((data && data.error) || "Something went wrong (" + res.status + ").");
    return data;
  }

  /* Copy text: works on http pages and inside phone app browsers where navigator.clipboard is missing. */
  function copyText(text) {
    return new Promise(function (resolve) {
      function fallback() {
        const ta = document.createElement("textarea");
        ta.value = text; ta.setAttribute("readonly", ""); ta.style.position = "fixed"; ta.style.opacity = "0";
        document.body.appendChild(ta); ta.select();
        let ok = false;
        try { ok = document.execCommand("copy"); } catch (e) { /* ignore */ }
        document.body.removeChild(ta); resolve(ok);
      }
      if (navigator.clipboard && window.isSecureContext) { navigator.clipboard.writeText(text).then(function () { resolve(true); }, fallback); }
      else fallback();
    });
  }

  let toastTimer = null;
  function toast(message) {
    const el = document.getElementById("toast");
    if (!el) return;
    el.textContent = message;
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.hidden = true; }, 3500);
  }

  function inline(text) {
    let s = esc(text);
    s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
    s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    s = s.replace(/(^|[^*\w])\*([^*\s][^*]*?)\*(?!\w)/g, "$1<em>$2</em>");
    s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
    s = s.replace(/\[Source (\d+)\]/g, '<span class="cite">Source $1</span>');
    return s;
  }

  /* Light syntax colouring for code blocks (no libraries). */
  const KEYWORDS = new Set(("def class return if elif else for while in not and or is import from as with try except finally raise " +
    "lambda None True False pass break continue yield async await function const let var new this super static public private " +
    "protected void int float double char long short boolean bool string String true false null undefined typeof switch case " +
    "default do throw throws catch extends implements interface struct enum namespace using include template typedef self " +
    "SELECT FROM WHERE INSERT INTO UPDATE DELETE CREATE TABLE JOIN ON GROUP BY ORDER LIMIT AND OR NOT NULL AS").split(" "));

  function highlight(code, lang) {
    lang = (lang || "").toLowerCase();
    if (/^(text|txt|output|plaintext|console|math)$/.test(lang)) return esc(code);
    const hashComment = /^(python|py|bash|sh|shell|zsh|ruby|rb|yaml|yml|r|perl)$/.test(lang);
    const comment = hashComment ? "#[^\\n]*" : "\\/\\/[^\\n]*|\\/\\*[\\s\\S]*?(?:\\*\\/|$)|--[^\\n]*";
    const re = new RegExp("(" + comment + ")|(\"\"\"[\\s\\S]*?(?:\"\"\"|$)|\"(?:\\\\.|[^\"\\\\\\n])*\"?|'(?:\\\\.|[^'\\\\\\n])*'?|`(?:\\\\.|[^`\\\\])*`?)|(\\b\\d+(?:\\.\\d+)?\\b)|([A-Za-z_]\\w*)", "g");
    let out = "", last = 0, m;
    while ((m = re.exec(code)) !== null) {
      out += esc(code.slice(last, m.index));
      last = m.index + m[0].length;
      const t = esc(m[0]);
      if (m[1]) out += '<span class="tk-c">' + t + "</span>";
      else if (m[2]) out += '<span class="tk-s">' + t + "</span>";
      else if (m[3]) out += '<span class="tk-n">' + t + "</span>";
      else if (KEYWORDS.has(m[4])) out += '<span class="tk-k">' + t + "</span>";
      else if (code.charAt(last) === "(") out += '<span class="tk-f">' + t + "</span>";
      else out += t;
      if (m[0].length === 0) re.lastIndex++;
    }
    return out + esc(code.slice(last));
  }

  function codeBlock(code, lang) {
    const label = lang ? esc(lang) : "code";
    return '<div class="codeblock"><div class="code-head"><span class="code-lang">' + label +
      '</span><button type="button" class="code-copy">Copy</button></div><pre><code>' + highlight(code, lang) + "</code></pre></div>";
  }

  /* Small Markdown renderer: headings, lists, code blocks, tables, quotes, bold, italic, inline code. */
  function md(source) {
    const lines = String(source).replace(/\r/g, "").split("\n");
    let html = "", i = 0, list = null, para = [];

    let quote = [];
    function flushPara() {
      if (para.length) { html += "<p>" + inline(para.join(" ")) + "</p>"; para = []; }
      if (quote.length) { html += "<blockquote>" + quote.map(inline).join("<br>") + "</blockquote>"; quote = []; }
    }
    function closeList() {
      if (list) { html += "</" + list + ">"; list = null; }
    }
    function openList(kind, start) {
      if (list === kind) return;
      closeList();
      list = kind;
      html += kind === "ol" && start > 1 ? '<ol start="' + start + '">' : "<" + kind + ">";
    }
    function cells(row) {
      return row.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map(function (c) { return c.trim(); });
    }

    while (i < lines.length) {
      const line = lines[i];
      let m;

      if (/^```/.test(line)) {
        flushPara(); closeList();
        const lang = line.replace(/^```\s*/, "").trim().split(/\s+/)[0];
        const code = [];
        i++;
        while (i < lines.length && !/^```/.test(lines[i])) { code.push(lines[i]); i++; }
        i++;
        html += codeBlock(code.join("\n"), lang);
        continue;
      }

      if (/^\s*([-*_])\1{2,}\s*$/.test(line)) { flushPara(); closeList(); html += "<hr>"; i++; continue; }

      if (/^\s*\|.*\|\s*$/.test(line) && i + 1 < lines.length && /^\s*\|?[\s:\-|]+\|[\s:\-|]*$/.test(lines[i + 1])) {
        flushPara(); closeList();
        const head = cells(line);
        i += 2;
        const body = [];
        while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) { body.push(cells(lines[i])); i++; }
        html += '<div class="table-wrap">' + "<table><thead><tr>" + head.map(function (c) { return "<th>" + inline(c) + "</th>"; }).join("") + "</tr></thead><tbody>" +
          body.map(function (r) { return "<tr>" + r.map(function (c) { return "<td>" + inline(c) + "</td>"; }).join("") + "</tr>"; }).join("") +
          "</tbody></table></div>";
        continue;
      }

      if ((m = line.match(/^(#{1,4})\s+(.*)$/))) {
        flushPara(); closeList();
        const level = Math.max(2, Math.min(4, m[1].length + (m[1].length === 1 ? 1 : 0)));
        html += "<h" + level + ">" + inline(m[2]) + "</h" + level + ">";
        i++; continue;
      }

      if ((m = line.match(/^\s*[-*+]\s+(.*)$/))) {
        flushPara(); openList("ul", 1);
        html += "<li>" + inline(m[1]) + "</li>";
        i++; continue;
      }

      if ((m = line.match(/^\s*(\d+)[.)]\s+(.*)$/))) {
        flushPara(); openList("ol", parseInt(m[1], 10));
        html += "<li>" + inline(m[2]) + "</li>";
        i++; continue;
      }

      if ((m = line.match(/^>\s?(.*)$/))) {
        if (para.length) { html += "<p>" + inline(para.join(" ")) + "</p>"; para = []; }
        closeList();
        quote.push(m[1]);
        i++; continue;
      }

      if (/^\s*$/.test(line)) { flushPara(); i++; continue; }

      closeList();
      para.push(line.trim());
      i++;
    }
    flushPara(); closeList();
    return html;
  }

  /* Copy button on code blocks. */
  document.addEventListener("click", function (event) {
    const btn = event.target.closest && event.target.closest(".code-copy");
    if (!btn) return;
    const code = btn.closest(".codeblock").querySelector("code").textContent;
    function done() { btn.textContent = "Copied"; setTimeout(function () { btn.textContent = "Copy"; }, 1500); }
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(code).then(done, function () { done(); });
    } else {
      const ta = document.createElement("textarea");
      ta.value = code; ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select();
      try { document.execCommand("copy"); } catch (e) { /* ignore */ }
      document.body.removeChild(ta); done();
    }
  });

  /* Back buttons: go to the previous page; if the page was opened directly, follow the link's own address. */
  document.addEventListener("click", function (event) {
    const link = event.target.closest && event.target.closest("[data-back]");
    if (!link) return;
    let sameSite = false;
    try { sameSite = document.referrer && new URL(document.referrer).origin === window.location.origin; } catch (e) { /* ignore */ }
    if (sameSite && window.history.length > 1) {
      event.preventDefault();
      window.history.back();
    }
  });

  /* Typing effect: show an answer word by word (click the answer to show it all at once). */
  function typeMd(el, source, onTick) {
    return new Promise(function (resolve) {
      const text = String(source);
      const tokens = text.match(/\S+\s*/g) || [];
      let shown = 0, finished = false, timer = null;

      function caret() {
        let last = el;
        while (last.lastElementChild) last = last.lastElementChild;
        const c = document.createElement("span");
        c.className = "caret";
        last.appendChild(c);
      }
      function finish() {
        if (finished) return;
        finished = true;
        clearTimeout(timer);
        el.removeEventListener("click", finish);
        el.innerHTML = md(text);
        if (onTick) onTick();
        resolve();
      }
      if (tokens.length < 2) { finish(); return; }

      // about 35 ms a word, but never longer than ~10 seconds in total
      const delay = Math.max(8, Math.min(35, 10000 / tokens.length));
      el.addEventListener("click", finish);
      (function step() {
        if (finished) return;
        shown = Math.min(tokens.length, shown + (tokens.length > 400 ? 2 : 1));
        el.innerHTML = md(tokens.slice(0, shown).join(""));
        caret();
        if (onTick) onTick();
        if (shown >= tokens.length) { finish(); return; }
        const last = tokens[shown - 1];
        timer = setTimeout(step, /[.!?:]\s*$/.test(last) ? delay * 4 : delay);
      })();
    });
  }

  window.U = { copyText: copyText, typeMd: typeMd, esc: esc, api: api, toast: toast, md: md, isTouch: isTouch, focusDesktop: focusDesktop,
               saveToken: saveToken, clearToken: clearToken, resumeLogin: resumeLogin };

  /* Profile circle (top right): open the menu, log out. */
  const avatar = document.getElementById("avatar-btn");
  const menu = document.getElementById("profile-menu");
  if (avatar && menu) {
    avatar.addEventListener("click", function (event) {
      event.stopPropagation();
      menu.hidden = !menu.hidden;
      avatar.setAttribute("aria-expanded", String(!menu.hidden));
    });
    document.addEventListener("click", function (event) {
      if (!menu.hidden && !menu.contains(event.target)) { menu.hidden = true; avatar.setAttribute("aria-expanded", "false"); }
    });
    document.addEventListener("keydown", function (event) { if (event.key === "Escape") menu.hidden = true; });
    document.getElementById("logout-btn").addEventListener("click", async function () {
      clearToken();
      try { await api("/api/logout", { json: {} }); } catch (err) { /* already signed out */ }
      window.location.href = "/";
    });
  }
})();

/* Top bar: keep the active menu item in view. */
(function () {
  const on = document.querySelector(".topnav a.on");
  if (on && on.scrollIntoView) { try { on.scrollIntoView({ inline: "center", block: "nearest" }); } catch (e) { /* old browser */ } }
})();


/* Phone bottom bar: the "More" sheet. */
(function () {
  const btn = document.getElementById("more-btn");
  const sheet = document.getElementById("more-sheet");
  if (!btn || !sheet) return;
  function setOpen(open) { sheet.hidden = !open; btn.setAttribute("aria-expanded", String(open)); }
  btn.addEventListener("click", function () { setOpen(sheet.hidden); });
  sheet.addEventListener("click", function (e) { if (e.target.closest("[data-more-close], a")) setOpen(false); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") setOpen(false); });
})();


/* Tapping a menu item: show the loading bar immediately (the page itself arrives a moment later). */
(function () {
  const bar = document.createElement("div");
  bar.className = "nav-bar";
  document.body.appendChild(bar);
  function start() {
    document.body.classList.add("navigating");
    bar.classList.remove("go"); void bar.offsetWidth; bar.classList.add("go");
  }
  document.addEventListener("click", function (e) {
    const a = e.target.closest && e.target.closest("a[href]");
    if (!a || e.defaultPrevented || e.button || e.metaKey || e.ctrlKey || e.shiftKey) return;
    if (a.target && a.target !== "_self") return;
    const href = a.getAttribute("href") || "";
    if (!href || href.charAt(0) === "#" || /^(mailto:|tel:|javascript:)/i.test(href) || a.hasAttribute("download")) return;
    try { const u = new URL(a.href, location.href); if (u.origin !== location.origin || (u.pathname === location.pathname && u.search === location.search)) return; } catch (err) { return; }
    start();
  });
  /* Back/forward from the browser cache: remove the bar again. */
  window.addEventListener("pageshow", function (e) { if (e.persisted) { document.body.classList.remove("navigating"); bar.classList.remove("go"); } });
})();
