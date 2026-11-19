/* Onboarding: what you study -> details -> study plan -> choose subjects -> enroll. */
(function () {
  const U = window.U;
  const boot = JSON.parse(document.getElementById("boot").textContent);
  const catalog = {};
  boot.catalog.forEach(function (s) { catalog[s.id] = s; });
  const state = { stage: null, values: {}, language: "en", subjects: [], builtin: [], chosen: new Map(), hours: 2, days: 60 };
  const $ = function (id) { return document.getElementById(id); };
  const show = function (el, on) { el.hidden = !on; };

  /* ---------- steps ---------- */
  function go(step) {
    document.querySelectorAll(".onb-card").forEach(function (c) { c.hidden = Number(c.dataset.step) !== step; });
    document.querySelectorAll("#onb-steps li").forEach(function (li) {
      const n = Number(li.dataset.s);
      li.classList.toggle("on", n === Math.min(step, 4));
      li.classList.toggle("done", n < Math.min(step, 4));
    });
    show($("onb-steps"), step <= 4);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  document.querySelectorAll("[data-back-step]").forEach(function (b) {
    b.addEventListener("click", function () { go(Number(b.dataset.backStep)); });
  });

  /* ---------- 1. stage ---------- */
  function pickStage(id) {
    if (state.stage && state.stage !== id) state.values = {};
    state.stage = id;
    document.querySelectorAll(".stage-card").forEach(function (c) { c.classList.toggle("on", c.dataset.stage === id); });
    renderDetails();
    go(2);
  }
  document.querySelectorAll(".stage-card").forEach(function (c) {
    c.addEventListener("click", function () { pickStage(c.dataset.stage); });
  });
  const skip = $("skip-btn");
  if (skip) skip.addEventListener("click", async function () {
    try { await U.api("/api/school/skip", { json: {} }); } catch (e) { /* ignore */ }
    window.location.href = "/";
  });

  /* ---------- 2. details ---------- */
  function renderDetails() {
    const stage = catalog[state.stage];
    $("detail-title").textContent = stage.icon + " " + stage.label + ": tell us more";
    const form = $("detail-form");
    form.innerHTML = "";
    stage.fields.forEach(function (f) {
      const wrap = document.createElement("label");
      wrap.className = "field";
      wrap.dataset.field = f.id;
      wrap.appendChild(document.createTextNode(f.label));
      let input;
      if (f.type === "select") {
        input = document.createElement("select");
        f.options.forEach(function (o) {
          const opt = document.createElement("option");
          opt.value = o; opt.textContent = o; input.appendChild(opt);
        });
        input.value = state.values[f.id] || f.default || f.options[0];
      } else {
        input = document.createElement("input");
        input.type = "text"; input.maxLength = 80;
        input.value = state.values[f.id] || "";
        if (f.type === "combo") {
          const list = document.createElement("datalist");
          list.id = "dl-" + f.id;
          f.options.forEach(function (o) { const opt = document.createElement("option"); opt.value = o; list.appendChild(opt); });
          wrap.appendChild(list);
          input.setAttribute("list", list.id);
          input.placeholder = "Choose or type, e.g. " + f.options[0];
        }
      }
      input.id = "f-" + f.id;
      input.addEventListener("input", function () { state.values[f.id] = input.value; applyShowIf(); });
      input.addEventListener("change", function () { state.values[f.id] = input.value; applyShowIf(); });
      state.values[f.id] = input.value;
      wrap.appendChild(input);
      form.appendChild(wrap);
    });
    applyShowIf();
  }
  function applyShowIf() {
    catalog[state.stage].fields.forEach(function (f) {
      if (!f.showIf) return;
      const wrap = document.querySelector('[data-field="' + f.id + '"]');
      const ok = Object.keys(f.showIf).every(function (k) { return f.showIf[k].indexOf(state.values[k]) !== -1; });
      wrap.hidden = !ok;
      if (!ok) state.values[f.id] = "";
    });
  }
  $("to-plan").addEventListener("click", function () {
    const err = $("detail-error");
    const first = catalog[state.stage].fields[0];
    if (!String(state.values[first.id] || "").trim()) {
      err.textContent = "Please fill in: " + first.label + ".";
      show(err, true);
      return;
    }
    show(err, false);
    go(3);
  });

  /* ---------- 3. plan ---------- */
  $("to-subjects").addEventListener("click", async function () {
    const btn = $("to-subjects"), err = $("plan-error");
    show(err, false);
    btn.disabled = true;
    try {
      await saveProfile();
      go(4);
      loadSubjects(false);
    } catch (e) {
      err.textContent = e.message; show(err, true);
    } finally { btn.disabled = false; }
  });
  function saveProfile() {
    const body = Object.assign({}, state.values, {
      stage: state.stage, goal: $("goal").value, daily_hours: $("daily-hours").value,
      plan_days: $("plan-days").value, language: state.language,
    });
    return U.api("/api/school/profile", { json: body });
  }

  /* ---------- 4. subjects ---------- */
  async function loadSubjects(refresh) {
    show($("subj-loading"), true);
    show($("subj-list"), false); show($("custom-form"), false); show($("enroll-bar"), false); show($("subj-note"), false);
    show($("subj-error"), false);
    $("subj-loading-text").textContent = refresh ? "Asking the AI for a fresh list…" : "Finding the right subjects for you…";
    try {
      const data = await U.api("/api/school/suggest", { json: { refresh: !!refresh } });
      state.subjects = data.subjects; state.builtin = data.builtin;
      state.hours = data.hours; state.days = data.days;
      $("subj-summary").textContent = data.summary;
      if (data.source === "offline") {
        $("subj-note").textContent = data.ai
          ? "The AI could not be reached just now, so this is a basic list. Press “New suggestions” to try again, or add your own subjects below."
          : "The AI key is not set on the server, so this is a basic list. You can still add any subject below once the key is set.";
        show($("subj-note"), true);
      }
      // keep earlier choices, otherwise pre-select the first core subjects
      const keep = new Set(state.chosen.keys());
      if (!keep.size) {
        let n = 0;
        data.subjects.forEach(function (s) { if (!s.enrolled && s.kind !== "Elective" && s.kind !== "Skill" && n < 6) { keep.add(s.name); n += 1; } });
      }
      state.chosen = new Map();
      data.subjects.forEach(function (s) { if (!s.enrolled && keep.has(s.name)) state.chosen.set(s.name, {}); });
      renderSubjects();
    } catch (e) {
      $("subj-error").textContent = e.message; show($("subj-error"), true);
    } finally { show($("subj-loading"), false); }
  }
  $("refresh-subjects").addEventListener("click", function () { loadSubjects(true); });

  function card(s, extra) {
    const on = state.chosen.has(s.name);
    return '<button type="button" class="subj-card' + (on ? " on" : "") + (s.enrolled ? " enrolled" : "") + '" data-name="' + U.esc(s.name) + '"' +
      (extra ? ' data-builtin="' + U.esc(extra) + '"' : "") + (s.enrolled ? " disabled" : "") + ">" +
      '<span class="check">' + (s.enrolled ? "✓" : on ? "✓" : "") + "</span>" +
      '<span class="subj-main"><strong>' + U.esc(s.name) + "</strong>" +
      (s.kind ? '<span class="tag kind-' + U.esc(String(s.kind).toLowerCase().replace(/\W/g, "")) + '">' + U.esc(s.kind) + "</span>" : "") +
      (s.why ? '<span class="muted small">' + U.esc(s.why) + "</span>" : "") +
      (s.enrolled ? '<span class="small ok-text">Already enrolled</span>' : "") + "</span></button>";
  }
  function renderSubjects() {
    const groups = {};
    state.subjects.forEach(function (s) { (groups[s.kind || "Core"] = groups[s.kind || "Core"] || []).push(s); });
    let html = "";
    ["Core", "Practical", "Elective", "Skill", "Exam prep"].forEach(function (k) {
      if (!groups[k]) return;
      html += "<h3 class=\"group-title\">" + (k === "Core" ? "Core subjects" : k === "Exam prep" ? "Exam preparation" : k === "Elective" ? "Electives" : k === "Practical" ? "Practicals and labs" : "Skills") + "</h3>";
      html += '<div class="subj-grid">' + groups[k].map(function (s) { return card(s); }).join("") + "</div>";
    });
    const custom = Array.from(state.chosen.keys()).filter(function (n) { return !state.subjects.some(function (s) { return s.name === n; }) && !state.builtin.some(function (b) { return b.name === n; }); });
    if (custom.length) {
      html += '<h3 class="group-title">Added by you</h3><div class="subj-grid">' + custom.map(function (n) { return card({ name: n, kind: "" }); }).join("") + "</div>";
    }
    if (state.builtin.length) {
      html += '<h3 class="group-title">Ready-made courses <span class="muted small">(work without the AI)</span></h3><div class="subj-grid">' +
        state.builtin.map(function (b) { return card({ name: b.name, kind: "", enrolled: b.enrolled }, b.id); }).join("") + "</div>";
    }
    $("subj-list").innerHTML = html;
    show($("subj-list"), true); show($("custom-form"), true); show($("enroll-bar"), true);
    updateCount();
  }
  $("subj-list").addEventListener("click", function (event) {
    const c = event.target.closest(".subj-card");
    if (!c || c.disabled) return;
    const name = c.dataset.name;
    if (state.chosen.has(name)) state.chosen.delete(name); else state.chosen.set(name, { builtin: c.dataset.builtin || null });
    c.classList.toggle("on", state.chosen.has(name));
    c.querySelector(".check").textContent = state.chosen.has(name) ? "✓" : "";
    updateCount();
  });
  $("custom-form").addEventListener("submit", function (event) {
    event.preventDefault();
    const input = $("custom-name"), name = input.value.replace(/\s+/g, " ").trim();
    if (name.length < 2) return;
    state.chosen.set(name, {});
    input.value = "";
    renderSubjects();
  });
  function updateCount() {
    const n = state.chosen.size;
    $("enroll-count").textContent = n + " subject" + (n === 1 ? "" : "s") + " selected";
    $("enroll-btn").disabled = n === 0;
  }

  /* ---------- 5. enroll, one subject at a time with progress ---------- */
  let queue = [];
  function startBuild(list) {
    go(5);
    show($("build-actions"), false); show($("retry-btn"), false);
    $("build-title").textContent = "Building your study plan…";
    queue = list;
    $("build-list").innerHTML = list.map(function (item, i) {
      return '<li id="b' + i + '" class="wait"><span class="b-ico">•</span><span class="b-name">' + U.esc(item.name) +
        '</span><span class="b-state small muted">Waiting</span></li>';
    }).join("");
    runBuild();
  }
  async function runBuild() {
    let failed = 0, done = 0;
    for (let i = 0; i < queue.length; i++) {
      const item = queue[i], row = $("b" + i);
      if (item.ok) { done += 1; continue; }
      row.className = "run";
      row.querySelector(".b-ico").innerHTML = '<span class="spinner small"></span>';
      row.querySelector(".b-state").textContent = "Building syllabus…";
      try {
        const res = await U.api("/api/school/enroll", { json: { name: item.name, builtin: item.builtin, count: queue.length }, timeout: 170000 });
        item.ok = true; done += 1;
        row.className = "ok";
        row.querySelector(".b-ico").textContent = "✓";
        if (res && res.practical_course) {
          row.querySelector(".b-state").textContent = "Ready (+ Auto " + res.practical_course.title + ")";
          U.toast("🔬 Practical component detected: Auto-enrolled " + res.practical_course.title);
        } else {
          row.querySelector(".b-state").textContent = "Ready";
        }
      } catch (e) {
        failed += 1;
        row.className = "bad"; row.querySelector(".b-ico").textContent = "!"; row.querySelector(".b-state").textContent = e.message;
      }
    }
    show($("build-actions"), true);
    show($("retry-btn"), failed > 0);
    $("build-title").textContent = failed ? done + " of " + queue.length + " subjects are ready" : "Your study plan is ready!";
    if (!failed) setTimeout(function () { window.location.href = "/study"; }, 1200);
  }
  $("retry-btn").addEventListener("click", function () { show($("build-actions"), false); runBuild(); });
  $("enroll-btn").addEventListener("click", function () {
    if (!state.chosen.size) return;
    startBuild(Array.from(state.chosen.entries()).map(function (e) { return { name: e[0], builtin: e[1].builtin || null }; }));
  });

  /* ---------- start ---------- */
  const p = boot.profile || {};
  if (p.stage && catalog[p.stage]) {
    state.stage = p.stage;
    ["level", "field", "term", "board", "institution"].forEach(function (k) { if (p[k]) state.values[k] = p[k]; });
    $("goal").value = p.goal || "";
    if (p.daily_hours) $("daily-hours").value = String(p.daily_hours);
    if (p.plan_days) $("plan-days").value = String(p.plan_days);
    document.querySelectorAll(".stage-card").forEach(function (c) { c.classList.toggle("on", c.dataset.stage === p.stage); });
    renderDetails();
  }
  if (boot.mode === "subjects" && p.onboarded) { go(4); loadSubjects(false); $("onb-title").textContent = "Add subjects"; }
  else if (boot.mode === "edit" && p.stage) { $("onb-title").textContent = "Your study profile"; go(2); }
  else go(1);
})();
