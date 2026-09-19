/**
 * Karma Console — 订单状态图（首页）
 *
 * 一笔单从「待接单」走到「已结算 / 争议」，用泳道一眼看完，不用在表格里找。
 * 数据只有一个来源：GET /v1/payments/ledger（和收付中心同一份台账，只读）。
 *
 * 两条规矩：
 *   1. 只认真正是「一笔订单」的三类：settlement / binding / voucher。
 *      锁仓凭证是资金动作，不是订单，不进这张图。
 *   2. 已完成（已结算 / 已退款 / 已取消）的单只在「可争议期」内留在图上，
 *      窗口一过自动退场 —— 历史去「收付中心」和「账单」查，图上只留还要处理的。
 *
 * 不写库、不碰私钥、不需要额外签名。
 */
(function (global) {
  "use strict";

  var PAGE = "overview";
  var ORDER_KINDS = { settlement: 1, binding: 1, voucher: 1 };
  /** 后端 /v1/info 会给真实窗口；拿不到时用这个兜底（settings.dispute_window_hours 的默认值）。 */
  var FALLBACK_DISPUTE_WINDOW_HOURS = 72;

  var LANES = [
    { key: "todo", label: "待接单 / 待开工", hint: "还没接或还没开工" },
    { key: "running", label: "执行中", hint: "已经在干活" },
    { key: "confirm", label: "待确认 / 待结算", hint: "等你点头才划钱" },
    { key: "dispute", label: "争议中", hint: "资金冻结，等仲裁" },
    { key: "done", label: "已完成 · 可争议期内", hint: "过了可争议期自动退场" },
  ];

  var TODO_STATUS = { draft: 1, pending: 1, created: 1 };
  var RUNNING_STATUS = { accepted: 1, in_progress: 1, progress_confirmed: 1, active: 1, none: 1 };

  /** 台账文案的作者是收付中心（cyber-payments.js）；拿不到时用这份兜底，别把英文状态名暴露给用户。 */
  var FALLBACK_LABELS = {
    settlement: {
      draft: "草稿", pending: "待锁定", accepted: "已接单", in_progress: "执行中",
      progress_submitted: "进度待确认", progress_confirmed: "进度已确认",
      delivered: "已交付待确认", disputed: "争议中", arbitrated: "已仲裁",
      settled: "已结算", refunded: "已退款", cancelled: "已取消",
    },
    binding: { none: "未开始", active: "执行中", finalizing: "待结算", breaching: "罚没中", settled: "已结算", slashed: "已罚没", cancelled: "已取消" },
    voucher: { created: "待接单", accepted: "已接单 · 额度锁定", used: "已核销", expired: "已过期", cancelled: "已取消", rejected: "已拒绝" },
  };

  var state = {
    side: "all",
    entries: [],
    loading: false,
    error: "",
    windowHours: FALLBACK_DISPUTE_WINDOW_HOURS,
    windowLoaded: false,
  };

  function $(sel, root) { return (root || document).querySelector(sel); }

  function api() { return global.cyberKarmaApi; }

  /** 译文（没接 i18n 或没这条译文时原样返回中文）。 */
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

  /** 任务号这类普通短引用：直接截断，和身份编号不是一回事。 */
  function shortRef(id) {
    if (!id) return "—";
    var s = String(id);
    return s.length > 20 ? s.slice(0, 10) + "…" + s.slice(-4) : s;
  }

  /** 身份编号（多数是交易对方的，拿不到排位）：全站统一走 KarmaDisplayId.remote。 */
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
    return s ? s.slice(0, 16).replace("T", " ") : "—";
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

  function statusLabel(entry) {
    try {
      var p = global.KarmaPayments;
      if (p && typeof p.statusLabel === "function") return p.statusLabel(entry);
    } catch (_) {}
    var map = FALLBACK_LABELS[entry.kind] || {};
    return map[entry.status] || entry.status || "—";
  }

  function setSync(text) {
    var n = $("#order-sync");
    if (n) n.textContent = text;
  }

  function disputeWindowMs(entry) {
    var h = Number((entry && entry.detail && entry.detail.dispute_window_hours) || state.windowHours || 0);
    if (!(h > 0)) h = FALLBACK_DISPUTE_WINDOW_HOURS;
    return h * 3600e3;
  }

  /** 一笔单落在哪条泳道；返回 null = 已经退场（不显示）。 */
  function laneOf(entry) {
    var phase = String(entry.phase || "");
    var status = String(entry.status || "");
    if (phase === "dispute") return "dispute";
    if (phase === "confirm") return "confirm";
    if (phase === "closed") {
      var ts = Date.parse(entry.updated_at || entry.created_at || "");
      // 没有时间戳就别猜：留在图上，让人自己去收付中心看。
      if (Number.isNaN(ts)) return "done";
      return Date.now() - ts <= disputeWindowMs(entry) ? "done" : null;
    }
    if (TODO_STATUS[status]) return "todo";
    if (RUNNING_STATUS[status]) return "running";
    return "running";
  }

  function entryById(entryId) {
    for (var i = 0; i < state.entries.length; i++) {
      if (String(state.entries[i].entry_id) === String(entryId)) return state.entries[i];
    }
    return null;
  }

  function visibleEntries() {
    return state.entries.filter(function (e) {
      if (!ORDER_KINDS[e.kind]) return false;
      if (state.side !== "all" && e.direction !== state.side) return false;
      return !!laneOf(e);
    });
  }

  function cardHtml(entry) {
    var mine = entry.direction === "out" ? "我买的" : "我卖的";
    return (
      '<button type="button" class="order-card" data-order-entry="' + esc(entry.entry_id) + '"' +
      ' data-order-dir="' + esc(entry.direction) + '">' +
      '<span class="order-card-top">' +
      '<span class="order-side-tag is-' + esc(entry.direction) + '">' + esc(mine) + "</span>" +
      '<span class="order-card-amount">' + money(entry.amount_usdc) + " <em>USDC</em></span>" +
      "</span>" +
      '<span class="order-card-title">' + esc(entry.title || entry.kind_label || "订单") + "</span>" +
      '<span class="order-card-meta"><span>' + esc(T(entry.kind_label || entry.kind) + " · " + T(statusLabel(entry))) + "</span></span>" +
      '<span class="order-card-meta"><span>对方 ' + esc(shortId(entry.counterparty_identity_id)) + "</span><span>" +
      esc(fmtTime(entry.updated_at || entry.created_at)) + "</span></span>" +
      (entry.task_id ? '<span class="order-card-meta"><span>任务 ' + esc(shortRef(entry.task_id)) + "</span></span>" : "") +
      "</button>"
    );
  }

  function render() {
    var host = $("#order-board");
    if (!host) return;
    var rows = visibleEntries();
    // 图看的那张单要是已经不在图上了（结算完 + 过了可争议期），把状态图一起收起来。
    var flow = global.KarmaOrderFlow;
    if (flow && flow.state && flow.state.open) {
      var still = rows.filter(function (e) {
        return String(e.entry_id) === String(flow.state.entry && flow.state.entry.entry_id);
      }).length;
      if (!still && flow.close) flow.close();
    }
    var byLane = {};
    LANES.forEach(function (lane) { byLane[lane.key] = []; });
    rows.forEach(function (entry) {
      var key = laneOf(entry);
      if (key && byLane[key]) byLane[key].push(entry);
    });

    host.innerHTML = LANES.map(function (lane) {
      var list = byLane[lane.key];
      var body = list.length
        ? list.map(cardHtml).join("")
        : '<span class="order-lane-empty">' + esc(lane.hint) + "</span>";
      return (
        '<div class="order-lane" data-lane="' + esc(lane.key) + '">' +
        '<div class="order-lane-head"><b>' + esc(lane.label) + "</b>" +
        '<span class="order-lane-count">' + list.length + "</span></div>" +
        '<div class="order-lane-body">' + body + "</div>" +
        "</div>"
      );
    }).join("");

    var totals = $("#order-totals");
    if (totals) {
      var hidden = state.entries.filter(function (e) {
        return ORDER_KINDS[e.kind] && (state.side === "all" || e.direction === state.side) && !laneOf(e);
      }).length;
      totals.innerHTML =
        "<span>" + esc(T("图上 {0} 单")).replace("{0}", "<b>" + rows.length + "</b>") + "</span>" +
        LANES.map(function (lane) {
          return "<span>" + esc(lane.label) + " <b>" + byLane[lane.key].length + "</b></span>";
        }).join("") +
        (hidden ? "<span>" + esc(T("已过可争议期、已退场 {0} 单")).replace("{0}", "<b>" + hidden + "</b>") + "</span>" : "");
    }

    var empty = $("#order-empty");
    if (empty) {
      if (state.error) {
        empty.textContent = "读取失败：" + state.error;
        empty.hidden = false;
      } else if (!identity()) {
        empty.textContent = "连接钱包后，这里会显示你的订单走到哪一步。";
        empty.hidden = false;
      } else if (!rows.length) {
        empty.textContent =
          "现在没有需要盯的订单。开一单去「收付中心 → 发起收付」；已经有 agent 的话，让它接单后这里会自动出现。";
        empty.hidden = false;
      } else {
        empty.hidden = true;
      }
    }
  }

  async function loadWindowHours() {
    if (state.windowLoaded) return;
    var a = api();
    if (!a || !a.getV1Info) return;
    try {
      var info = await a.getV1Info();
      var guards = (info && info.settlement_guards) || {};
      var h = Number(guards.dispute_window_hours || 0);
      if (h > 0) state.windowHours = h;
      state.windowLoaded = true;
    } catch (_) {
      // 读不到就用兜底窗口：图照常显示，只是退场时间按默认值算。
    }
  }

  async function load() {
    var a = api();
    var host = $("#order-board");
    if (!a || !a.getPaymentLedger) {
      if (host) host.innerHTML = '<p class="order-lane-empty">API 客户端未加载（karma-public-api.js）。</p>';
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
      await loadWindowHours();
      var body = await a.getPaymentLedger({ identity_id: id, profile_id: activeScope(), limit: 500 });
      state.entries = (body && body.entries) || [];
      state.error = "";
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

  /** 泳道视角：all / out（我买的）/ in（我卖的）。nav 子项和高亮由 switchPage 管。 */
  function setSide(side) {
    var next = side === "out" || side === "in" ? side : "all";
    if (state.side === next) return;
    state.side = next;
    render();
  }

  function paintSides() {
    document.querySelectorAll("[data-order-side]").forEach(function (btn) {
      btn.classList.toggle("active", btn.getAttribute("data-order-side") === state.side);
    });
  }

  function bind() {
    var refresh = $("#order-refresh");
    if (refresh) refresh.addEventListener("click", function () { load(); });

    document.querySelectorAll("[data-order-side]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var side = btn.getAttribute("data-order-side");
        // 走 switchPage：侧栏子项、高亮、泳道视角三处一起对齐，不会各说各话。
        if (global.cyberSwitchPage) {
          global.cyberSwitchPage(PAGE, side === "out" ? "buy" : side === "in" ? "sell" : undefined);
        } else {
          setSide(side);
          paintSides();
        }
      });
    });

    var host = $("#order-board");
    if (host) {
      host.addEventListener("click", function (ev) {
        var card = ev.target && ev.target.closest ? ev.target.closest("[data-order-entry]") : null;
        if (!card) return;
        // 点一张单 -> 就地展开这一单的状态图（订单号 / 对方 / 时间 / 合同 / 阶段线）。
        var entry = entryById(card.getAttribute("data-order-entry"));
        if (entry && global.KarmaOrderFlow && global.KarmaOrderFlow.open) {
          global.KarmaOrderFlow.open(entry);
          return;
        }
        // 状态图模块没加载时退回老路径：去收付中心看明细。
        var dir = card.getAttribute("data-order-dir");
        if (global.cyberSwitchPage) global.cyberSwitchPage("center", dir === "in" ? "in" : "out");
      });
    }

    document.addEventListener("karma-page-shown", function (ev) {
      if (!ev || !ev.detail || ev.detail.page !== PAGE) return;
      paintSides();
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

  global.KarmaOrders = { load: load, setSide: setSide, paintSides: paintSides, state: state };
})(window);