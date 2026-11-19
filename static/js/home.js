/* Home page: login window, chat, and the two pop-up windows (new course, enrolled courses). */
(function () {
  const U = window.U;

  /* ---------- login and sign up ---------- */
  function nextPage() {   // where to go after logging in: the page that was asked for (same site only)
    const n = new URLSearchParams(window.location.search).get("next") || "";
    return /^\/(?!\/)/.test(n) && n.indexOf("\\") === -1 ? n : "/";
  }
  const loginForm = document.getElementById("form-login");
  if (loginForm) {
    const $ = function (id) { return document.getElementById(id); };
    const forms = { login: loginForm, signup: $("form-signup"), email: $("form-email"), otp: $("form-otp") };
    const titles = {
      login: ["Welcome back", "Log in with your email and password."],
      signup: ["Create your account", "Free for every student. We will verify your email."],
      forgot: ["Forgot password?", "Enter your email and we will send a 6-digit code."],
      logincode: ["Log in with email code", "No password needed. We will send a 6-digit code."],
      otp: ["Check your email", ""]
    };
    const flow = { purpose: "", email: "", timer: null };

    function show(view, key) {              // view: which form; key: which heading
      Object.keys(forms).forEach(function (k) { forms[k].hidden = k !== view; });
      $("auth-tabs").hidden = !(view === "login" || view === "signup");
      document.querySelectorAll("[data-auth-tab]").forEach(function (t) { t.classList.toggle("active", t.dataset.authTab === view); });
      const h = titles[key || view];
      $("auth-title").textContent = h[0];
      $("auth-sub").textContent = h[1];
      $("auth-sub").hidden = !h[1];
      document.querySelectorAll("[data-err]").forEach(function (e) { e.hidden = true; });
    }
    function fail(form, message) {
      const box = form.querySelector("[data-err]");
      box.textContent = message; box.hidden = false;
    }
    async function work(form, fn) {         // one tap = one request: the button is locked while waiting
      const btn = form.querySelector('button[type="submit"]');
      if (form.dataset.busy) return;
      form.dataset.busy = "1"; btn.disabled = true;
      form.querySelector("[data-err]").hidden = true;
      try { await fn(); }
      catch (err) { fail(form, err.message); }
      finally { delete form.dataset.busy; btn.disabled = false; }
    }
    function done(res) { U.saveToken(res && res.token); window.location.replace(nextPage()); }

    function startCountdown(seconds) {
      const btn = $("otp-resend");
      clearInterval(flow.timer);
      let left = seconds;
      function tick() {
        btn.disabled = left > 0;
        btn.textContent = left > 0 ? "Resend code in " + left + "s" : "Resend code";
        if (left-- <= 0) clearInterval(flow.timer);
      }
      tick(); flow.timer = setInterval(tick, 1000);
    }
    function openOtp(purpose, email, masked, cooldown) {
      flow.purpose = purpose; flow.email = email;
      $("otp-sent").textContent = "We sent a 6-digit code to " + masked + ". It works for 10 minutes.";
      $("otp-newpw").hidden = purpose !== "reset";
      $("otp-submit").textContent = purpose === "signup" ? "Verify and create account" : purpose === "reset" ? "Reset password" : "Verify and log in";
      $("otp-code").value = ""; $("otp-pw").value = ""; $("otp-pw2").value = "";
      show("otp", "otp");
      startCountdown(cooldown || 60);
      U.focusDesktop($("otp-code"));
    }

    /* tabs, links, show/hide password */
    document.querySelectorAll("[data-auth-tab]").forEach(function (t) { t.addEventListener("click", function () { show(t.dataset.authTab); }); });
    document.querySelectorAll("[data-go]").forEach(function (b) {
      b.addEventListener("click", function () {
        const go = b.dataset.go;
        if (go === "login") return show("login");
        flow.purpose = go === "forgot" ? "reset" : "login";
        $("em-email").value = $("login-id").value.indexOf("@") > 0 ? $("login-id").value.trim() : "";
        show("email", go);
        U.focusDesktop($("em-email"));
      });
    });
    document.addEventListener("click", function (e) {
      const t = e.target.closest(".pw-toggle");
      if (!t) return;
      const input = $(t.dataset.for);
      const reveal = input.type === "password";
      input.type = reveal ? "text" : "password";
      t.textContent = reveal ? "Hide" : "Show";
      t.setAttribute("aria-label", reveal ? "Hide password" : "Show password");
    });
    U.focusDesktop($("login-id"));          // never on phones: it would open the keyboard

    /* Already logged in before? Restore it silently instead of showing the login form again. */
    (async function () {
      const root = document.documentElement;
      const showForm = function () { root.classList.remove("resuming"); };
      const failsafe = setTimeout(showForm, 8000);       // never leave the person on a blank screen
      if (await U.resumeLogin()) { window.location.replace(nextPage()); return; }   // stays hidden until the home page opens
      clearTimeout(failsafe);
      showForm();
    })();

    /* log in with email + password */
    loginForm.addEventListener("submit", function (e) {
      e.preventDefault();
      work(loginForm, async function () {
        const id = $("login-id").value.trim(), pw = $("login-pw").value;
        if (!id || !pw) throw new Error("Please type your email and your password.");
        done(await U.api("/api/login", { json: { username: id, password: pw } }));
      });
    });

    /* sign up -> code */
    forms.signup.addEventListener("submit", function (e) {
      e.preventDefault();
      work(forms.signup, async function () {
        if ($("su-pw").value !== $("su-confirm").value) throw new Error("The two passwords do not match.");
        const email = $("su-email").value.trim().toLowerCase();
        const res = await U.api("/api/signup/start", { json: {
          name: $("su-name").value, email: email, password: $("su-pw").value } });
        openOtp("signup", email, res.email, res.cooldown);
      });
    });

    /* forgot password / login with code: ask for the email */
    forms.email.addEventListener("submit", function (e) {
      e.preventDefault();
      work(forms.email, async function () {
        const email = $("em-email").value.trim().toLowerCase();
        const res = await U.api(flow.purpose === "reset" ? "/api/forgot/start" : "/api/login/otp/start", { json: { email: email } });
        openOtp(flow.purpose, email, res.email, res.cooldown);
      });
    });

    /* enter the code */
    forms.otp.addEventListener("submit", function (e) {
      e.preventDefault();
      work(forms.otp, async function () {
        const code = $("otp-code").value.replace(/\D/g, "");
        if (code.length !== 6) throw new Error("Please type the 6-digit code from your email.");
        if (flow.purpose === "signup") return done(await U.api("/api/signup/verify", { json: { email: flow.email, code: code } }));
        if (flow.purpose === "login") return done(await U.api("/api/login/otp/verify", { json: { email: flow.email, code: code } }));
        const pw = $("otp-pw").value;
        if (pw !== $("otp-pw2").value) throw new Error("The two passwords do not match.");
        done(await U.api("/api/forgot/verify", { json: { email: flow.email, code: code, password: pw } }));
      });
    });
    $("otp-code").addEventListener("input", function () {
      this.value = this.value.replace(/\D/g, "").slice(0, 6);
      if (this.value.length === 6 && flow.purpose !== "reset") forms.otp.requestSubmit();   // sign up / login: no more taps needed
    });
    $("otp-resend").addEventListener("click", async function () {
      this.disabled = true;
      try {
        const res = await U.api("/api/otp/resend", { json: { purpose: flow.purpose, email: flow.email } });
        startCountdown(res.cooldown || 60);
        U.toast("A new code was sent.");
      } catch (err) { fail(forms.otp, err.message); startCountdown(10); }
    });
    $("otp-back").addEventListener("click", function () {
      clearInterval(flow.timer);
      if (flow.purpose === "signup") show("signup");
      else show("email", flow.purpose === "reset" ? "forgot" : "logincode");
    });
    return;
  }

  /* ---------- pop-up windows ---------- */
  function openModal(id) {
    document.querySelectorAll(".modal").forEach(function (m) { m.hidden = true; });
    const modal = document.getElementById(id);
    if (!modal) return;
    modal.hidden = false;
    document.body.classList.add("modal-open");
    const first = modal.querySelector("select, input, a.btn, button.btn");
    if (first) U.focusDesktop(first);
  }
  function closeModals() {
    document.querySelectorAll(".modal").forEach(function (m) { m.hidden = true; });
    document.body.classList.remove("modal-open");
  }
  document.querySelectorAll("[data-open]").forEach(function (btn) {
    btn.addEventListener("click", function () { openModal(btn.dataset.open); });
  });
  document.querySelectorAll("[data-close]").forEach(function (el) { el.addEventListener("click", closeModals); });
  document.addEventListener("keydown", function (event) { if (event.key === "Escape") closeModals(); });

  /* ---------- start new course (form in the pop-up, Save button) ---------- */
  const form = document.getElementById("course-form");
  if (form) {
    const steps = document.getElementById("steps");
    const errorBox = document.getElementById("form-error");
    const button = document.getElementById("build-btn");
    const subjectSel = document.getElementById("subject-select");
    const customWrap = document.getElementById("custom-wrap");
    const customInput = document.getElementById("custom-input");

    function syncSubject() {
      const other = subjectSel.value === "other";
      customWrap.hidden = !other;
      customInput.required = other;
    }
    subjectSel.addEventListener("change", syncSubject);
    syncSubject();

    function setStep(name) {
      const order = ["syllabus", "open"];
      steps.querySelectorAll("li").forEach(function (li) {
        const index = order.indexOf(li.dataset.step);
        const current = order.indexOf(name);
        li.className = index < current ? "done" : index === current ? "active" : "";
      });
    }

    form.addEventListener("submit", async function (event) {
      event.preventDefault();
      errorBox.hidden = true;
      const data = Object.fromEntries(new FormData(form).entries());
      button.disabled = true;
      button.textContent = "Saving...";
      steps.hidden = false;

      const started = Date.now();
      const ticker = setInterval(function () {
        button.textContent = "Saving... " + Math.round((Date.now() - started) / 1000) + "s";
      }, 1000);

      try {
        setStep("syllabus");
        const courseId = (await U.api("/api/courses", { json: data, timeout: 140000 })).id;
        clearInterval(ticker);
        setStep("open");
        window.location.href = "/course/" + courseId;
      } catch (err) {
        clearInterval(ticker);
        errorBox.textContent = err.message;
        errorBox.hidden = false;
        button.disabled = false;
        button.textContent = "Save";
        steps.hidden = true;
      }
    });
  }

  /* ---------- enrolled courses: delete ---------- */
  document.querySelectorAll("[data-delete]").forEach(function (btn) {
    btn.addEventListener("click", async function () {
      if (!window.confirm('Delete "' + btn.dataset.name + '"? This removes its lessons and progress.')) return;
      try {
        await U.api("/api/courses/" + btn.dataset.delete, { method: "DELETE" });
        window.location.reload();
      } catch (err) {
        U.toast(err.message);
      }
    });
  });

  /* ---------- chat ---------- */
  const chatForm = document.getElementById("home-chat-form");
  if (chatForm) {
    const home = document.getElementById("home");
    const log = document.getElementById("home-chat-log");
    const input = document.getElementById("home-chat-input");
    const send = document.getElementById("home-chat-send");
    const history = [];

    function bubble(kind, html) {
      log.hidden = false;
      home.classList.add("chatting");   // first message: welcome and the two buttons move to the side
      document.body.classList.add("chat-open");
      const div = document.createElement("div");
      div.className = "bubble " + kind;
      div.innerHTML = html;
      log.appendChild(div);
      log.scrollTop = log.scrollHeight;
      return div;
    }

    async function ask(text) {
      bubble("user", U.esc(text));
      const waiting = bubble("model", '<span class="muted loading">Thinking</span>');
      send.disabled = true;
      try {
        const res = await U.api("/api/chat", { json: { message: text, history: history }, timeout: 50000 });
        history.push({ role: "user", text: text }, { role: "model", text: res.answer });
        await U.typeMd(waiting, res.answer, function () { log.scrollTop = log.scrollHeight; });
      } catch (err) {
        waiting.innerHTML = '<span class="error">' + U.esc(err.message) + "</span>";
      }
      send.disabled = false;
      log.scrollTop = log.scrollHeight;
      U.focusDesktop(input);   // on phones the keyboard stays closed after an answer
    }

    chatForm.addEventListener("submit", function (event) {
      event.preventDefault();
      const text = input.value.trim();
      if (!text) return;
      input.value = "";
      ask(text);
    });
  }

  /* Coming back with the browser's Back button: always show a fresh page (new courses, closed pop-ups). */
  window.addEventListener("pageshow", function (event) {
    if (event.persisted) window.location.reload();
  });
})();
