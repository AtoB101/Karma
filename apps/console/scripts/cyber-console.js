/**
 * Cyber console — navigation, i18n, API binding (capacity + settlement lookup).
 */
(function () {
  const LS_BASE = "karma_cyber_api_base";
  const LS_KEY = "karma_cyber_api_key";
  const LS_ID = "karma_cyber_identity_id";
  const LS_TASKS = "karma_console_task_ids";
  const LS_AUTO = "karma_console_auto_sync";

  const pages = {
    overview: ["page.overview.title", "page.overview.sub"],
    center: ["page.center.title", "page.center.sub"],
    tasks: ["page.tasks.title", "page.tasks.sub"],
    receipts: ["page.receipts.title", "page.receipts.sub"],
    bills: ["page.bills.title", "page.bills.sub"],
    disputes: ["page.disputes.title", "page.disputes.sub"],
    identity: ["page.identity.title", "page.identity.sub"],
    settings: ["page.settings.title", "page.settings.sub"],
  };

  function el(sel) {
    return document.querySelector(sel);
  }

  function loadCfgIntoInputs() {
    try {
      if (el("[data-cfg=api_base]"))
        el("[data-cfg=api_base]").value =
          localStorage.getItem(LS_BASE) || window.KARMA_API_BASE || "http://127.0.0.1:8000";
      if (el("[data-cfg=api_key]"))
        el("[data-cfg=api_key]").value = localStorage.getItem(LS_KEY) || window.KARMA_API_KEY || "";
      if (el("[data-cfg=identity_id]"))
        el("[data-cfg=identity_id]").value =
          localStorage.getItem(LS_ID) || window.KARMA_IDENTITY_ID || "worker-001";
      if (el("[data-cfg=task_ids]"))
        el("[data-cfg=task_ids]").value = localStorage.getItem(LS_TASKS) || "";
      if (el("[data-cfg=auto_sync]")) el("[data-cfg=auto_sync]").checked = localStorage.getItem(LS_AUTO) === "1";
    } catch (_) {}
  }

  function saveCfg() {
    const base = el("[data-cfg=api_base]")?.value?.trim() || "";
    const key = el("[data-cfg=api_key]")?.value?.trim() || "";
    const id = el("[data-cfg=identity_id]")?.value?.trim() || "";
    const tasks = el("[data-cfg=task_ids]")?.value?.trim() || "";
    const auto = el("[data-cfg=auto_sync]")?.checked;
    try {
      localStorage.setItem(LS_BASE, base);
      localStorage.setItem(LS_KEY, key);
      localStorage.setItem(LS_ID, id);
      localStorage.setItem(LS_TASKS, tasks);
      if (auto !== undefined) localStorage.setItem(LS_AUTO, auto ? "1" : "");
    } catch (_) {}
    window.KARMA_API_BASE = base;
    window.KARMA_API_KEY = key;
    window.KARMA_IDENTITY_ID = id;
    const mainId = el(".id-main");
    if (mainId && id) mainId.textContent = id;
    setApiStatus(window.CYBER_I18N.t("api.status_ok") + " — " + base, false);
  }

  function setApiStatus(msg, isErr) {
    const n = el("[data-api-status]");
    if (!n) return;
    n.textContent = msg;
    n.classList.toggle("err", !!isErr);
  }

  function fmtNum(x) {
    const n = Number(x);
    if (Number.isNaN(n)) return "—";
    return n.toFixed(2);
  }

  async function refreshCapacity() {
    const id = el("[data-cfg=identity_id]")?.value?.trim();
    if (!id) {
      setApiStatus("Identity ID empty", true);
      return;
    }
    setApiStatus("…", false);
    try {
      const c = await window.cyberKarmaApi.getCapacity(id);
      const map = [
        ["[data-bind=total_locked_usdc]", c.total_locked_usdc],
        ["[data-bind=available_credits]", c.available_credits],
        ["[data-bind=in_progress_bucket]", (c.in_progress_credits || 0) + (c.reserved_credits || 0)],
        ["[data-bind=pending_settlement_credits]", c.pending_settlement_credits],
        ["[data-bind=disputed_credits]", c.disputed_credits],
      ];
      map.forEach(function (row) {
        const node = el(row[0]);
        if (node) node.textContent = fmtNum(row[1]);
      });
      setApiStatus(window.CYBER_I18N.t("api.status_ok") + " · capacity @" + new Date().toLocaleTimeString(), false);
    } catch (e) {
      setApiStatus(String(e.message || e), true);
    }
  }

  async function fetchSettlement() {
    const tid = el("[data-cfg=task_id]")?.value?.trim();
    const out = el("[data-settlement-preview]");
    if (!tid) {
      if (out) out.textContent = "task id empty";
      return;
    }
    if (out) out.textContent = "…";
    try {
      const s = await window.cyberKarmaApi.getSettlement(tid);
      if (out) out.textContent = JSON.stringify(s, null, 2);
      setApiStatus("settlement loaded", false);
    } catch (e) {
      if (out) out.textContent = String(e.message || e);
      setApiStatus(String(e.message || e), true);
    }
  }

  function switchPage(page) {
    document.querySelectorAll(".page").forEach(function (p) {
      p.classList.remove("active");
    });
    const sec = document.getElementById(page);
    if (sec) sec.classList.add("active");
    document.querySelectorAll(".nav button").forEach(function (b) {
      b.classList.remove("active");
    });
    const btn = document.querySelector('.nav button[data-page="' + page + '"]');
    if (btn) btn.classList.add("active");
    const h = el("#pageHeading");
    const sub = el("#pageSubheading");
    if (h && sub && pages[page]) {
      h.setAttribute("data-i18n", pages[page][0]);
      sub.setAttribute("data-i18n", pages[page][1]);
      window.CYBER_I18N.applyCyberI18n();
    }
    try {
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (_) {}
  }

  /** Exposed for `onclick` / action cards in static HTML */
  window.cyberSwitchPage = switchPage;

  function bindNav() {
    document.querySelectorAll(".nav button").forEach(function (btn) {
      btn.addEventListener("click", function () {
        switchPage(btn.getAttribute("data-page"));
      });
    });
  }

  function bindLang() {
    const sel = el("#cyberLang");
    if (!sel) return;
    sel.value = window.CYBER_I18N.getLang();
    sel.addEventListener("change", function () {
      window.CYBER_I18N.setLang(sel.value);
      window.CYBER_I18N.applyCyberI18n();
    });
  }

  function bindActions() {
    el("[data-action=save-cfg]")?.addEventListener("click", function () {
      saveCfg();
    });
    el("[data-action=refresh-api]")?.addEventListener("click", function () {
      saveCfg();
      refreshCapacity();
    });
    el("[data-action=fetch-settlement]")?.addEventListener("click", function () {
      saveCfg();
      fetchSettlement();
    });
  }

  function bindAiToggle() {
    const aiToggle = document.getElementById("aiAgentToggle");
    const aiStatus = document.getElementById("aiAgentStatus");
    if (aiToggle && aiStatus) {
      aiToggle.addEventListener("change", function () {
        aiStatus.textContent = aiToggle.checked ? "开启 / ON" : "关闭 / OFF";
      });
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    loadCfgIntoInputs();
    window.KARMA_API_BASE = el("[data-cfg=api_base]")?.value?.trim();
    window.KARMA_API_KEY = el("[data-cfg=api_key]")?.value?.trim();
    window.KARMA_IDENTITY_ID = el("[data-cfg=identity_id]")?.value?.trim();
    const mainId = el(".id-main");
    if (mainId && window.KARMA_IDENTITY_ID) mainId.textContent = window.KARMA_IDENTITY_ID;

    window.CYBER_I18N.applyCyberI18n();
    bindLang();
    bindNav();
    document.querySelectorAll("[data-go]").forEach(function (node) {
      node.addEventListener("click", function () {
        switchPage(node.getAttribute("data-go") || "overview");
      });
    });
    bindActions();
    bindAiToggle();
    switchPage("overview");
    setApiStatus(window.CYBER_I18N.t("api.status_idle"), false);
  });
})();
