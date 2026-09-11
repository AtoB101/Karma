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
    auth: ["page.auth.title", "page.auth.sub"],
    agents: ["page.agents.title", "page.agents.sub"],
    settings: ["page.settings.title", "page.settings.sub"],
  };

  function el(sel) {
    return document.querySelector(sel);
  }

  function isLocalPage() {
    const h = window.location.hostname;
    return h === "localhost" || h === "127.0.0.1" || h === "::1" || h === "";
  }

  /** A base saved during local development must not follow us onto a real host. */
  function isForeignLocalhost(base) {
    if (isLocalPage()) return false;
    try {
      const host = new URL(base, window.location.href).hostname;
      return host === "localhost" || host === "127.0.0.1" || host === "::1" || host === "0.0.0.0";
    } catch (_) {
      return false;
    }
  }

  /**
   * Effective API base for this page: a saved override, else window.KARMA_API_BASE
   * ("" = same-origin), else the local dev API on localhost and this origin in production.
   */
  function displayBase() {
    let stored = "";
    try {
      stored = localStorage.getItem(LS_BASE) || "";
    } catch (_) {}
    if (stored && !isForeignLocalhost(stored)) return stored;
    const raw = window.KARMA_API_BASE;
    if (raw === undefined || raw === null || String(raw).trim() === "") {
      return isLocalPage() ? "http://127.0.0.1:8000" : window.location.origin;
    }
    return String(raw).trim();
  }

  function loadCfgIntoInputs() {
    try {
      if (el("[data-cfg=api_base]")) el("[data-cfg=api_base]").value = displayBase();
      if (el("[data-cfg=api_key]"))
        el("[data-cfg=api_key]").value =
          sessionStorage.getItem(LS_KEY) || localStorage.getItem(LS_KEY) || window.KARMA_API_KEY || "";
      if (el("[data-cfg=identity_id]"))
        el("[data-cfg=identity_id]").value =
          sessionStorage.getItem(LS_ID) || localStorage.getItem(LS_ID) || window.KARMA_IDENTITY_ID || "";
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
      // Security: API key / identity are session-only, never persisted long-term.
      sessionStorage.setItem(LS_KEY, key);
      sessionStorage.setItem(LS_ID, id);
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

  async function lockCapacityAction() {
    const id = (el("[data-cfg=identity_id]")?.value || "").trim() || window.KARMA_IDENTITY_ID || "";
    const amount = Number(el("#lock-amount")?.value || 0);
    if (!id) { setApiStatus("请先连接钱包或填写 Identity ID", true); return; }
    if (!amount || amount <= 0) { setApiStatus("请填写锁仓金额", true); return; }
    setApiStatus("锁仓中…", false);
    try {
      const r = await window.cyberKarmaApi.lockCapacity(id, amount);
      setApiStatus("锁仓成功 · " + amount + " USDC", false);
      refreshCapacity();
      return r;
    } catch (e) {
      setApiStatus(String(e.message || e), true);
    }
  }

  async function releaseCapacityAction() {
    const id = (el("[data-cfg=identity_id]")?.value || "").trim() || window.KARMA_IDENTITY_ID || "";
    const amount = Number(el("#release-amount")?.value || 0);
    const note = el("#release-status");
    const say = function (msg, isErr) {
      if (note) {
        note.textContent = msg;
        note.classList.toggle("err", !!isErr);
      }
      setApiStatus(msg, isErr);
    };
    if (!id) { say("请先连接钱包或填写 Identity ID", true); return; }
    if (!amount || amount <= 0) { say("请填写释放金额", true); return; }
    const activePid =
      window.cyberKarmaApi && window.cyberKarmaApi.activeProfileId
        ? window.cyberKarmaApi.activeProfileId()
        : "";
    if (activePid) {
      say(
        "当前视角是子身份 " + String(activePid).slice(0, 12) + "…：释放额度属于主体身份卡的操作，" +
          "请先在顶部「切换子身份」里选「主体（全部）」；子身份的额度请到「身份」页 →「额度分配」下调。",
        true
      );
      return;
    }
    say("释放中…", false);
    try {
      await window.cyberKarmaApi.releaseCapacity(id, amount);
      say("已释放 " + amount + " USDC", false);
      refreshCapacity();
      // The bills ledger (released_credits) is rendered by cyber-actions.js.
      const bills = document.getElementById("btn-refresh-bills");
      if (bills) bills.click();
    } catch (e) {
      say(String(e.message || e), true);
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
    // Panels that only matter on one page (账单明细, 子身份过滤) refresh here.
    try {
      document.dispatchEvent(new CustomEvent("karma-page-shown", { detail: { page: page } }));
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

  /** Fallbacks for a cached i18n script that predates SHIPPED_LANGS. */
  const LANG_LABELS = { "zh-CN": "\u4e2d\u6587", en: "English" };
  const LANG_ORDER = ["zh-CN", "en"];

  /**
   * Offer the shipped languages, and only those.
   *
   * ja/ko/es/fr/de/pt-BR do have packs, but each covers 32 of the 224 keys, so
   * picking one leaves the page mostly English behind a localized label. The list
   * is read from i18n-cyber.js rather than hard-coded here so it cannot drift
   * away from the packs the page can actually render.
   */
  function syncLangOptions(sel) {
    const i18n = window.CYBER_I18N || {};
    const packs = Object.keys(i18n.PACKS || {});
    const labels = i18n.LANG_LABELS || LANG_LABELS;
    const shipped = (i18n.SHIPPED_LANGS || LANG_ORDER).filter(function (c) {
      return packs.indexOf(c) >= 0;
    });
    if (!shipped.length) return;
    sel.innerHTML = "";
    shipped.forEach(function (code) {
      const opt = document.createElement("option");
      opt.value = code;
      opt.textContent = labels[code] || code;
      sel.appendChild(opt);
    });
  }

  function bindLang() {
    const sel = el("#cyberLang");
    if (!sel) return;
    syncLangOptions(sel);
    sel.value = window.CYBER_I18N.getLang();
    sel.addEventListener("change", function () {
      window.CYBER_I18N.setLang(sel.value);
      window.CYBER_I18N.applyCyberI18n();
      if (window.KarmaIdentitySwitcher && window.KarmaIdentitySwitcher.render) {
        window.KarmaIdentitySwitcher.render();
      }
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
    el("[data-action=lock-capacity]")?.addEventListener("click", function () {
      saveCfg();
      lockCapacityAction();
    });
    el("[data-action=release-capacity]")?.addEventListener("click", function () {
      saveCfg();
      releaseCapacityAction();
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
    const baseVal = el("[data-cfg=api_base]")?.value?.trim();
    if (baseVal) window.KARMA_API_BASE = baseVal;
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
