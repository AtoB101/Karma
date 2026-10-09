/** 
 * Karma Console — 助理任务执行看板（任务执行页）
 *
 * 小爱这类助理身份切进来后，这一页要回答的是「它正在叫 agent 做什么」：
 * 只从收付台账读任务结算单 / 付款授权码，把订单号、任务内容、金额和进度
 * 摊成一张张卡片，不暴露后台字段和状态机英文这些实现细节。
 *
 * 数据来源和订单状态图、收付中心一致：GET /v1/payments/ledger（只读）。
 * 任务合同只在卡片需要「任务内容」时按 task_id 拉一次，读不到就退回
 * 服务类型 / 任务类型，不瞎编。
 */
(function (global) {
  "use strict";

  var PAGE = "tasks";
  var TASK_KINDS = { settlement: 1, voucher: 1 };
  var CONTRACT_FETCH_LIMIT = 40;

  var PHASE_LABEL = {
    active: "执行中",
    confirm: "待确认 / 待结算",
    dispute: "争议中",
    closed: "已完成",
  };

  var state = {
    entries: [],
    error: "",
    loading: false,
  };

  var contractCache = {};

  function $(sel, root) { return (root || document).querySelector(sel); }

  function api() { return global.cyberKarmaApi; }

  function T(zh) {
    var i18n = window.CYBER_I18N;
    return i18n && i18n.T ? i18n.T(zh) : zh;
  }

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function money(value) {
    var n = Number(value);
    return (Number.isNaN(n) ? 0 : n).toFixed(2);
  }

  function shortRef(id) {
    if (!id) return "—";
    var s = String(id);
    return s.length > 20 ? s.slice(0, 10) + "…" + s.slice(-4) : s;
  }

  function shortId(id) {
    if (!id) return "—";
    try {
      if (global.KarmaDisplayId && global.KarmaDisplayId.remote) {
        return global.KarmaDisplayId.remote(id) || "—";
      }
    } catch (_) {}
    return shortRef(id);
  }

  function fmtTime(value) {
    var s = String(value || "");
    if (!s) return "—";
    var d = new Date(s);
    if (!Number.isNaN(d.getTime())) {
      return d.toLocaleString([], { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
    }
    return s.slice(0, 16).replace("T", " ");
  }

  function identity() {
    var configured = $("[data-cfg=identity_id]");
    var stored = "";
    try { stored = sessionStorage.getItem("karma_console_identity") || ""; } catch (_) {}
    return String(global.KARMA_IDENTITY_ID || (configured && configured.value) || stored || "").trim();
  }

  function activeScope() {
    try {
      var sw = global.KarmaIdentitySwitcher;
      if (sw && sw.getActiveProfileId) return sw.getActiveProfileId() || "";
    } catch (_) {}
    return "";
  }

  function setSync(text) {
    var n = $("#assistant-task-status");
    if (n) n.textContent = text;
  }

  function statusLabel(entry) {
    try {
      var p = global.KarmaPayments;
      if (p && typeof p.statusLabel === "function") return p.statusLabel(entry);
    } catch (_) {}
    return entry.status || "—";
  }

  function phaseLabel(entry) {
    return PHASE_LABEL[entry.phase] || "进行中";
  }

  function sceneOf(entry) {
    try {
      var flow = global.KarmaOrderFlow;
      if (flow && typeof flow.sceneOf === "function") {
        var scene = flow.sceneOf(entry);
        if (scene && scene.def && scene.def.label) return scene.def;
      }
    } catch (_) {}
    return null;
  }

  function sceneLabel(entry) {
    var scene = sceneOf(entry);
    if (scene) return scene.label;
    var d = (entry && entry.detail) || {};
    return d.task_type || d.scene_id || "";
  }

  function isTaskEntry(entry) {
    return !!entry && !!TASK_KINDS[entry.kind];
  }

  function isOpenTask(entry) {
    return isTaskEntry(entry) && entry.phase !== "closed";
  }

  function taskTitle(entry) {
    var contract = entry._contract;
    if (contract && contract.title) return contract.title;
    if (entry.kind === "voucher") {
      var d = (entry && entry.detail) || {};
      if (d.task_type) return d.task_type;
    }
    if (entry.title && entry.title.indexOf("任务结算 · ") !== 0 && entry.title.indexOf("付款授权码 · ") !== 0) {
      return entry.title;
    }
    return "任务 " + shortRef(entry.task_id || entry.ref_id);
  }

  function taskContent(entry) {
    var contract = entry._contract;
    if (contract && contract.description) return contract.description;
    var scene = sceneOf(entry);
    if (scene) return "服务类型：" + scene.label;
    var d = (entry && entry.detail) || {};
    if (d.task_type) return "任务类型：" + d.task_type;
    return "任务内容以合同为准，点击「收付中心」可查看订单详情。";
  }

  function cardHtml(entry) {
    var dirLabel = entry.direction === "out" ? T("我买的") : T("我卖的");
    var scene = sceneOf(entry);
    var metaItems = [
      ["订单", shortRef(entry.task_id || entry.ref_id)],
      ["服务类型", scene ? scene.label : "—"],
      ["状态", statusLabel(entry)],
      ["更新时间", fmtTime(entry.updated_at || entry.created_at)],
    ];

    return (
      '<article class="task-card task-dir-' + esc(entry.direction) + ' task-phase-' + esc(entry.phase) + '">' +
        '<div class="task-card-head">' +
          '<span class="order-side-tag is-' + esc(entry.direction) + '">' + esc(T(dirLabel)) + "</span>" +
          '<span class="task-amount">' + money(entry.amount_usdc) + " <em>USDC</em></span>" +
        "</div>" +
        '<div class="task-title">' + esc(taskTitle(entry)) + "</div>" +
        '<div class="task-desc">' + esc(taskContent(entry)) + "</div>" +
        '<div class="task-meta">' +
          metaItems.map(function (pair) {
            return '<span><i>' + esc(pair[0]) + "</i><b>" + esc(pair[1]) + "</b></span>";
          }).join("") +
        "</div>" +
      "</article>"
    );
  }

  function render() {
    var host = $("#assistant-task-board");
    var empty = $("#assistant-task-empty");
    if (!host) return;

    var rows = state.entries.filter(isOpenTask).sort(function (a, b) {
      var av = String(a.updated_at || a.created_at || "");
      var bv = String(b.updated_at || b.created_at || "");
      return av < bv ? 1 : av > bv ? -1 : 0;
    });

    host.innerHTML = rows.map(cardHtml).join("");

    if (empty) {
      if (state.error) {
        empty.textContent = "读取失败：" + state.error;
        empty.hidden = false;
      } else if (!identity()) {
        empty.textContent = "连接钱包后，这里会显示小爱正在让 agent 执行的任务。";
        empty.hidden = false;
      } else if (!rows.length) {
        empty.textContent = "当前没有进行中的任务。让 agent 接单后，这里会自动出现订单、任务内容和金额。";
        empty.hidden = false;
      } else {
        empty.hidden = true;
      }
    }
  }

  async function hydrateContracts(entries) {
    var a = api();
    if (!a || !a.getContract) return;
    var pending = entries.filter(function (e) {
      return e.task_id && !Object.prototype.hasOwnProperty.call(contractCache, e.task_id);
    }).slice(0, CONTRACT_FETCH_LIMIT);

    await Promise.all(pending.map(function (entry) {
      var taskId = entry.task_id;
      return a.getContract(taskId).then(function (contract) {
        contractCache[taskId] = contract;
        entry._contract = contract;
      }).catch(function () {
        contractCache[taskId] = null;
        entry._contract = null;
      });
    }));

    entries.forEach(function (entry) {
      if (entry.task_id && Object.prototype.hasOwnProperty.call(contractCache, entry.task_id)) {
        entry._contract = contractCache[entry.task_id];
      }
    });
  }

  async function load() {
    var a = api();
    var host = $("#assistant-task-board");
    if (!a || !a.getPaymentLedger) {
      if (host) host.innerHTML = '<p class="task-empty">API 客户端未加载（karma-public-api.js）。</p>';
      return;
    }

    var id = identity();
    if (!id) {
      state.entries = [];
      state.error = "";
      setSync("未连接");
      render();
      return;
    }

    state.loading = true;
    setSync("读取中…");
    try {
      var body = await a.getPaymentLedger({ identity_id: id, profile_id: activeScope(), limit: 500 });
      state.entries = (body && body.entries) || [];
      state.error = "";
      await hydrateContracts(state.entries.filter(isOpenTask));
      setSync("已更新 " + new Date().toLocaleTimeString());
    } catch (e) {
      state.entries = [];
      state.error = (e && (e.message || e.detail)) || String(e);
      setSync("读取失败");
    } finally {
      state.loading = false;
      render();
    }
  }

  function bind() {
    var refresh = $("#assistant-task-refresh");
    if (refresh) refresh.addEventListener("click", function () { load(); });

    document.addEventListener("karma-page-shown", function (ev) {
      if (!ev || !ev.detail || ev.detail.page !== PAGE) return;
      load();
    });

    ["karma-wallet-connected", "karma-session-restored", "karma-profile-switched",
      "karma-capacity-changed", "karma-alloc-changed", "karma-agent-connected"].forEach(function (name) {
      document.addEventListener(name, function () { load(); });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { bind(); load(); });
  } else {
    bind();
    load();
  }

  global.KarmaAssistantTasks = { load: load, state: state };
})(window);
