/**
 * Karma Console — 收付中心（总览 / 收入明细 / 支出明细 / 确认区 / 争议区）
 *
 * 数据只有一个来源：GET /v1/payments/ledger —— 后端把任务结算单、链上结算单、
 * 付款授权码、锁仓凭证归一成同一种「台账条目」。这里只负责排版与交互：
 *
 *   主身份视角：总览（已收 / 已付 / 在途 / 待收 / 锁仓 / 净额）+ 支出明细 + 收入明细
 *   子身份视角：该子身份的支出明细 + 收入明细（作用域跟着全局身份切换器走）
 *   每一行都能点开看详情：金额、对方、状态、时间、状态流转历史
 *   确认区：已交付 / 待确认的单；争议区：争议 / 仲裁中的单，按订单状态分色
 *
 * 只读慢查询，不写库、不碰私钥。
 */
(function (global) {
  "use strict";

  var PAGE = "center";

  var STATUS_LABELS = {
    settlement: {
      draft: "草稿",
      pending: "待锁定",
      accepted: "已接单",
      in_progress: "执行中",
      progress_submitted: "进度待确认",
      progress_confirmed: "进度已确认",
      delivered: "已交付待确认",
      disputed: "争议中",
      arbitrated: "已仲裁",
      settled: "已结算",
      refunded: "已退款",
      cancelled: "已取消",
    },
    binding: {
      none: "未开始",
      active: "执行中",
      finalizing: "待结算",
      settled: "已结算",
      slashed: "已罚没",
      cancelled: "已取消",
    },
    voucher: {
      created: "待接单",
      accepted: "已接单 · 额度锁定",
      used: "已核销",
      expired: "已过期",
      cancelled: "已取消",
      rejected: "已拒绝",
    },
    lock: { open: "锁仓中", revoked: "已撤回" },
  };

  var state = {
    scope: "",
    tab: "out",
    entries: [],
    confirmation: [],
    disputes: [],
    totals: { matched: 0, returned: 0, scoped: 0 },
    loading: false,
    error: "",
  };

  function $(sel) {
    return document.querySelector(sel);
  }

  function api() {
    return global.cyberKarmaApi;
  }

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function num(value) {
    var n = Number(value);
    return Number.isNaN(n) ? 0 : n;
  }

  function money(value) {
    return num(value).toFixed(2);
  }

  function shortId(id) {
    if (!id) return "—";
    var s = String(id);
    return s.length > 20 ? s.slice(0, 10) + "…" + s.slice(-4) : s;
  }

  function myDisplayId(id) {
    try {
      if (global.KarmaDisplayId && global.KarmaDisplayId.of) return global.KarmaDisplayId.of(id, 0);
    } catch (_) {}
    return shortId(id);
  }

  function fmtTime(value) {
    var s = String(value || "");
    return s ? s.slice(0, 16).replace("T", " ") : "—";
  }

  function identity() {
    var configured = $( "[data-cfg=identity_id]" );
    var stored = "";
    try {
      stored = sessionStorage.getItem("karma_console_identity") || "";
    } catch (_) {}
    return String(
      global.KARMA_IDENTITY_ID ||
        (configured && configured.value) ||
        stored ||
        ""
    ).trim();
  }

  function activeScope() {
    try {
      var sw = global.KarmaIdentitySwitcher;
      if (sw && sw.getActiveProfileId) return sw.getActiveProfileId() || "";
    } catch (_) {}
    return "";
  }

  function profileLabel(profileId) {
    try {
      var sw = global.KarmaIdentitySwitcher;
      var list = (sw && sw.getProfiles && sw.getProfiles()) || [];
      for (var i = 0; i < list.length; i++) {
        if (list[i] && list[i].profile_id === profileId) {
          var pos = i + 1;
          var tag = "";
          try {
            if (global.KarmaDisplayId && global.KarmaDisplayId.of) {
              tag = global.KarmaDisplayId.of(profileId, pos) + " · ";
            }
          } catch (_) {}
          return tag + (list[i].display_name || profileId);
        }
      }
    } catch (_) {}
    return shortId(profileId);
  }

  function statusLabel(entry) {
    var map = STATUS_LABELS[entry.kind] || {};
    return map[entry.status] || entry.status || "—";
  }

  function setBind(key, value) {
    var nodes = document.querySelectorAll('[data-bind="' + key + '"]');
    var text = value == null ? "—" : String(value);
    nodes.forEach(function (n) {
      n.textContent = text;
    });
  }

  function setSync(text) {
    var n = $("#pay-sync");
    if (n) n.textContent = text;
  }

  function rowsForTab(tab) {
    return state.entries.filter(function (e) {
      return e.direction === tab;
    });
  }

  /* ------------------------------------------------------------ 明细行 */

  function entryRow(entry) {
    var row = document.createElement("div");
    row.className = "pay-row pay-phase-" + entry.phase + " pay-dir-" + entry.direction;
    row.setAttribute("role", "button");
    row.setAttribute("tabindex", "0");
    row.setAttribute("data-pay-entry", entry.entry_id);
    row.innerHTML =
      '<span class="pay-role pay-role-' + esc(entry.direction) + '">' +
        (entry.direction === "out" ? "支出" : "收入") +
      "</span>" +
      '<span class="pay-main">' +
        "<b>" + esc(entry.title) + "</b>" +
        "<i>" + esc(entry.kind_label) +
          " · 对方 " + esc(shortId(entry.counterparty_identity_id)) +
          (entry.task_id ? " · 任务 " + esc(shortId(entry.task_id)) : "") +
        "</i>" +
      "</span>" +
      '<span class="pay-amount">' + money(entry.amount_usdc) + " <em>USDC</em></span>" +
      '<span class="pay-status pay-status-' + esc(entry.phase) + '">' + esc(statusLabel(entry)) + "</span>" +
      '<span class="pay-time">' + esc(fmtTime(entry.updated_at || entry.created_at)) + "</span>";
    row.addEventListener("click", function () {
      openDetail(entry);
    });
    row.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" || ev.key === " ") {
        ev.preventDefault();
        openDetail(entry);
      }
    });
    return row;
  }

  function emptyText() {
    if (state.error) return "读取失败：" + state.error;
    if (!identity()) return "请先连接钱包完成认证，这里会显示你的收付台账。";
    if (state.scope) {
      return (
        "子身份 " + profileLabel(state.scope) +
        " 名下还没有这一类的单。切回「主体（全部）」可以看整张身份卡的账。"
      );
    }
    return state.tab === "out"
      ? "还没有支出记录。发起付款授权或接单后，这里会按状态列出每一笔。"
      : "还没有收入记录。你作为卖方接单结算后，这里会按状态列出每一笔。";
  }

  function renderList() {
    var host = $("#pay-list");
    if (!host) return;
    var out = rowsForTab("out").length;
    var income = rowsForTab("in").length;
    var co = $("#pay-count-out");
    var ci = $("#pay-count-in");
    if (co) co.textContent = String(out);
    if (ci) ci.textContent = String(income);

    document.querySelectorAll("[data-pay-tab]").forEach(function (btn) {
      btn.classList.toggle("active", btn.getAttribute("data-pay-tab") === state.tab);
    });

    var rows = rowsForTab(state.tab);
    if (!rows.length) {
      host.innerHTML = '<p class="pay-empty">' + esc(emptyText()) + "</p>";
      return;
    }
    var frag = document.createDocumentFragment();
    rows.forEach(function (entry) {
      frag.appendChild(entryRow(entry));
    });
    host.innerHTML = "";
    host.appendChild(frag);
  }

  function renderStats(summary) {
    summary = summary || {};
    var master = !state.scope;
    var stats = $("#pay-stats");
    var sub = $("#pay-substats");
    if (stats) stats.hidden = !master;
    if (sub) sub.hidden = master;
    if (master) {
      setBind("pay_income", money(summary.income_usdc));
      setBind("pay_expense", money(summary.expense_usdc));
      setBind("pay_inflight", money(summary.in_flight_usdc));
      setBind("pay_pending_income", money(summary.pending_income_usdc));
      setBind("pay_locked", money(summary.locked_usdc));
      setBind("pay_net", money(summary.net_usdc));
    } else {
      setBind("pay_sub_income", money(summary.income_usdc));
      setBind("pay_sub_expense", money(summary.expense_usdc));
      setBind("pay_sub_inflight", money(summary.in_flight_usdc));
    }
  }

  function renderZone(hostId, countId, entries, emptyLabel) {
    var host = $("#" + hostId);
    var count = $("#" + countId);
    if (count) count.textContent = String(entries.length);
    if (!host) return;
    if (!entries.length) {
      host.innerHTML = '<p class="pay-empty">' + esc(emptyLabel) + "</p>";
      return;
    }
    var frag = document.createDocumentFragment();
    entries.forEach(function (entry) {
      frag.appendChild(entryRow(entry));
    });
    host.innerHTML = "";
    host.appendChild(frag);
  }

  function renderScopeNote() {
    var note = $("#pay-scope-note");
    if (!note) return;
    if (!identity()) {
      note.textContent = "连接钱包后，这里是你的收付台账。";
      return;
    }
    note.textContent = state.scope
      ? "子身份 " + profileLabel(state.scope) + " · 只显示这个身份的收付明细"
      : "主体身份卡 " + myDisplayId(identity()) + " · 全部子身份的收付都在这里汇总";
  }

  function renderAll(summary) {
    renderScopeNote();
    renderStats(summary);
    renderList();
    renderZone("pay-confirm-list", "pay-confirm-count", state.confirmation, "暂无待确认的单。");
    renderZone("pay-dispute-list", "pay-dispute-count", state.disputes, "暂无争议中的单。");
    var more = $("#pay-more");
    if (more) more.hidden = state.totals.matched <= state.totals.returned;
  }

  /* ------------------------------------------------------------ 单笔详情 */

  function detailRows(entry) {
    var d = entry.detail || {};
    var rows = [
      ["类型", entry.kind_label],
      ["金额", money(entry.amount_usdc) + " USDC"],
      ["已结算", money(entry.settled_usdc) + " USDC"],
      ["状态", statusLabel(entry)],
      ["我方角色", entry.direction === "out" ? "付款方（支出）" : "收款方（收入）"],
      ["对方身份", entry.counterparty_identity_id || "—"],
      ["任务", entry.task_id || "—"],
      ["子身份归属", entry.profile_id || entry.counterparty_profile_id || "主体身份"],
      ["创建时间", fmtTime(entry.created_at)],
      ["更新时间", fmtTime(entry.updated_at)],
    ];
    var extra = [
      ["退款", d.refund_amount != null ? money(d.refund_amount) + " USDC" : null],
      ["保证金", d.stake_usdc != null ? money(d.stake_usdc) + " USDC" : null],
      ["结算模式", d.settlement_mode || null],
      ["争议原因", d.dispute_reason || null],
      ["仲裁备注", d.arbitration_notes || null],
      ["钱包地址", d.wallet_address || null],
      ["锁仓已占用", d.reserved_usdc != null ? money(d.reserved_usdc) + " USDC" : null],
      ["锁仓可用", d.available_usdc != null ? money(d.available_usdc) + " USDC" : null],
      ["链上交易", d.tx_hash || d.bind_tx_hash || d.commit_tx_hash || null],
      ["有效期至", d.expiry_time ? fmtTime(d.expiry_time) : null],
      ["拒绝原因", d.rejection_reason || null],
    ];
    extra.forEach(function (pair) {
      if (pair[1]) rows.push(pair);
    });
    return rows
      .map(function (pair) {
        return (
          '<div class="pay-detail-row"><span>' + esc(pair[0]) +
          "</span><b>" + esc(pair[1]) + "</b></div>"
        );
      })
      .join("");
  }

  function detailHistory(history) {
    if (!history || !history.length) {
      return '<p class="pay-empty">这一单还没有状态流转记录。</p>';
    }
    return (
      '<div class="pay-history">' +
      history
        .map(function (item) {
          var head = item.to_status || item.event_type || "—";
          var from = item.from_status ? item.from_status + " → " : "";
          var note = item.reason || (item.payload && JSON.stringify(item.payload)) || "";
          return (
            '<div class="pay-history-row"><span class="pay-history-time">' +
            esc(fmtTime(item.at)) +
            "</span><b>" + esc(from + head) + "</b><i>" +
            esc(String(note).slice(0, 160)) +
            "</i></div>"
          );
        })
        .join("") +
      "</div>"
    );
  }

  function renderDetail(entry, history) {
    var host = $("#pay-detail");
    if (!host) return;
    host.hidden = false;
    host.innerHTML =
      '<div class="pay-detail-head">' +
        '<div><b>' + esc(entry.title) + "</b>" +
        '<span class="pay-detail-sub">' + esc(entry.entry_id) + "</span></div>" +
        '<button type="button" class="btn" id="pay-detail-close">关闭</button>' +
      "</div>" +
      '<div class="pay-detail-grid">' + detailRows(entry) + "</div>" +
      "<h4>状态流转 / 事件</h4>" +
      detailHistory(history);
    var close = $("#pay-detail-close");
    if (close) {
      close.addEventListener("click", function () {
        host.hidden = true;
        host.innerHTML = "";
      });
    }
  }

  async function openDetail(entry) {
    var host = $("#pay-detail");
    var a = api();
    if (!host || !a) return;
    host.hidden = false;
    host.innerHTML = '<p class="pay-empty">读取详情中…</p>';
    try {
      var body = await a.getPaymentEntry(entry.kind, entry.ref_id, identity());
      renderDetail(body.entry || entry, body.history || []);
    } catch (e) {
      renderDetail(entry, []);
    }
    try {
      host.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (_) {}
  }

  /* ------------------------------------------------------------ 取数 */

  async function load() {
    var a = api();
    state.scope = activeScope();
    state.error = "";
    var id = identity();

    if (!a || !a.getPaymentLedger) {
      var host0 = $("#pay-list");
      if (host0) host0.innerHTML = '<p class="pay-empty">API 客户端未加载（karma-public-api.js）。</p>';
      return;
    }
    if (!id) {
      state.entries = [];
      state.confirmation = [];
      state.disputes = [];
      state.totals = { matched: 0, returned: 0, scoped: 0 };
      setSync("未连接");
      renderAll({});
      return;
    }

    state.loading = true;
    setSync("读取中…");
    try {
      var body = await a.getPaymentLedger({
        identity_id: id,
        profile_id: state.scope,
        limit: 500,
      });
      state.entries = body.entries || [];
      state.confirmation = body.confirmation || [];
      state.disputes = body.disputes || [];
      state.totals = body.totals || { matched: state.entries.length, returned: state.entries.length, scoped: state.entries.length };
      renderAll(body.summary || {});
      setSync("已更新 " + new Date().toLocaleTimeString());
    } catch (e) {
      state.error = (e && (e.message || e.detail)) || String(e);
      setSync("读取失败");
      renderAll({});
    } finally {
      state.loading = false;
    }
  }

  function bind() {
    var refresh = $("#pay-refresh");
    if (refresh) refresh.addEventListener("click", function () { load(); });

    document.querySelectorAll("[data-pay-tab]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        state.tab = btn.getAttribute("data-pay-tab");
        renderList();
      });
    });

    var create = $("#pay-new");
    if (create) {
      create.addEventListener("click", function () {
        var panel = $("#pay-create");
        if (!panel) return;
        panel.hidden = !panel.hidden;
        create.setAttribute("aria-expanded", panel.hidden ? "false" : "true");
        if (!panel.hidden) {
          try {
            panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
          } catch (_) {}
        }
      });
    }
  }

  document.addEventListener("karma-page-shown", function (ev) {
    if (!ev || !ev.detail || ev.detail.page !== PAGE) return;
    load();
  });

  [
    "karma-wallet-connected",
    "karma-session-restored",
    "karma-profile-switched",
    "karma-alloc-changed",
    "karma-capacity-changed",
    "karma-console-sync-done",
  ].forEach(function (name) {
    document.addEventListener(name, function () {
      load();
    });
  });

  document.addEventListener("DOMContentLoaded", function () {
    if (!$("#pay-list")) return;
    bind();
    var section = $("#" + PAGE);
    if (section && section.classList.contains("active")) load();
  });

  global.KarmaPayments = { load: load, state: state, openDetail: openDetail };
})(window);
