(function () {
  const U = window.U;
  const cid = window.COURSE_ID;

  /* tabs */
  const tabs = document.querySelectorAll("[data-tab]");
  const panels = document.querySelectorAll("[data-panel]");
  function showTab(name) {
    if (!document.querySelector('[data-panel="' + name + '"]')) name = "roadmap";
    tabs.forEach(function (t) { t.classList.toggle("active", t.dataset.tab === name); });
    panels.forEach(function (p) { p.hidden = p.dataset.panel !== name; });
    history.replaceState(null, "", "#" + name);
  }
  tabs.forEach(function (t) { t.addEventListener("click", function () { showTab(t.dataset.tab); }); });
  showTab(location.hash.replace("#", "") || "roadmap");

  /* plan or re-plan the schedule */
  document.querySelectorAll('[data-action="schedule"]').forEach(function (btn) {
    btn.addEventListener("click", async function () {
      if (btn.dataset.busy) return;
      btn.dataset.busy = "1";
      const label = btn.textContent;
      btn.disabled = true;
      btn.textContent = "Planning...";
      try {
        await U.api("/api/courses/" + cid + "/schedule", { json: {} });
        location.hash = "#schedule";
        location.reload();
      } catch (err) {
        U.toast(err.message);
        btn.disabled = false;
        btn.textContent = label;
        delete btn.dataset.busy;
      }
    });
  });

  /* upload study material */
  const upload = document.getElementById("upload-form");
  if (upload) {
    upload.addEventListener("submit", async function (event) {
      event.preventDefault();
      const button = upload.querySelector("button");
      const body = new FormData(upload);
      button.disabled = true;
      button.textContent = "Reading file...";
      try {
        await U.api("/api/courses/" + cid + "/materials", { method: "POST", body: body });
        location.hash = "#materials";
        location.reload();
      } catch (err) {
        U.toast(err.message);
        button.disabled = false;
        button.textContent = "Upload";
      }
    });
  }

  document.querySelectorAll("[data-remove-material]").forEach(function (btn) {
    btn.addEventListener("click", async function () {
      try {
        await U.api("/api/courses/" + cid + "/materials/" + btn.dataset.removeMaterial, { method: "DELETE" });
        location.hash = "#materials";
        location.reload();
      } catch (err) {
        U.toast(err.message);
      }
    });
  });
})();
