/**
 * 操作台 · 主身份页（主体账户）。
 *
 * 主身份 = 账房，只做四件事：① 连接钱包 ② 刷脸认证（决定「激活」）③ 锁仓 USDC ④ 授权给身份。
 * 这一页就是这本账：总账单 + 每个身份的「授权 / 已用 / 可用」+ 加额 / 减额 / 取消授权。
 * 订单、收付、任务、市场都是子身份干活的地方，切到那个身份才有。
 *
 *   GET  /v1/identity/{id}/activation           激活态（= 本人实名认证是否通过）
 *   GET  /v1/capacity/{id}/allocations          每个身份的额度 + 已用 + 总账
 *   PUT  /v1/capacity/{id}/allocations          改额度（加 / 减 / 取消授权）
 *
 * 安全边界：只用 SIWE 会话读写自己的账；不碰私钥 / 助记词。金额一律走服务端口径，
 * 前端不自己算总额（免得两处对不上）。
 */
(function (global) {
  "use strict";

  var ZERO = {
    allocations: {},
    locked: 0,
    allocated: 0,
    inUse: 0,
    available: 0,
    capacity: null,
    activation: null,
    wallet: "",
    busy: false,
  };
  var state = Object.assign({}, ZERO);

  /** 原地清空：KarmaMasterPage 暴露的就是这个对象，整体替换会让外部引用变旧。 */
  function resetState() {
    state.allocations = {};
    state.locked = 0;
    state.allocated = 0;
    state.inUse = 0;
    state.available = 0;
    state.capacity = null;
    state.activation = null;
    state.ceiling = null;
    state.busy = false;
  }

  function el(id) { return document.getElementById(id); }
  function api() { return global.cyberKarmaApi; }
  function identity() { return String(global.KARMA_IDENTITY_ID || "").trim(); }
  function esc(v) {
    return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function num(v) {
    var n = Number(v || 0);
    return Math.round(n * 100) / 100;
  }
  function money(v) { return num(v).toFixed(2); }
  function say(node, msg, isErr) {
    if (!node) return;
    node.textContent = msg;
    node.classList.toggle("err", !!isErr);
  }

  /** 身份号一律走对外写法（kid1… / kid02…），别把 kid_ 原文写进界面。 */
  function label(profileId, index) {
    var did = global.KarmaDisplayId;
    if (did && did.of) return did.of(profileId, index);
    return profileId;
  }
  function short(addr) {
    var s = String(addr || "").trim();
    return s.length > 12 ? s.slice(0, 6) + "\u2026" + s.slice(-4) : s;
  }
  function sessionWallet() {
    try {
      var a = global.KarmaWalletAuth;
      return a && a.readSession ? a.readSession() || {} : {};
    } catch (_) {
      return {};
    }
  }
  function profiles() {
    var sw = global.KarmaIdentitySwitcher;
    var list = (sw && sw.getProfiles ? sw.getProfiles() : []) || [];
    return list.filter(function (p) { return p && p.profile_id; });
  }
  /** 编号在前、名称在后 —— 全站同一个「编号 · 名称」口径，别一处一个样。 */
  function titleOf(p, i) {
    var sw = global.KarmaIdentitySwitcher;
    var t = (sw && sw.identityTitle ? sw.identityTitle(p) : "") || p.display_name || "子身份";
    return label(p.profile_id, i + 1) + " · " + t;
  }

  /** 激活态只说人话：未提交 / 审核中 / 已激活 / 已驳回。 */
  function activationLabel(activation) {
    var status = (activation && activation.status) || "none";
    if (status === "verified") return "已激活";
    if (status === "pending") return "审核中";
    if (status === "rejected") return "已驳回";
    return "未激活";
  }

  function renderActivation() {
    var a = state.activation || {};
    var activated = !!a.activated;
    var step = el("mst-step-activate");
    var gate = el("mst-activate-gate");
    var title = el("mst-activate-title");
    var note = el("mst-activate-note");
    var go = el("mst-activate-go");
    var stateEl = el("mst-activate-state");

    if (step) step.classList.toggle("on", activated);
    if (gate) gate.classList.toggle("on", activated);
    if (stateEl) stateEl.textContent = activationLabel(a);

    if (!identity()) {
      if (title) title.textContent = "先连接钱包";
      if (note) note.textContent = "连上钱包拿到主身份号之后，再做一次本人刷脸认证就能激活。";
      if (go) { go.hidden = false; go.textContent = "去连接钱包 →"; }
      return;
    }
    if (go) go.textContent = "去刷脸认证 →";
    if (activated) {
      var when = a.verified_at ? String(a.verified_at).slice(0, 10) : "";
      if (title) title.textContent = "主身份已激活";
      if (note) note.textContent = when
        ? "认证于 " + when + " 通过。可以接单、可以被撮合，信誉记录从现在开始记。"
        : "认证已通过。可以接单、可以被撮合，信誉记录从现在开始记。";
      if (go) go.hidden = true;
    } else {
      if (title) title.textContent = "主身份尚未激活";
      if (note) note.textContent =
        "完成一次主身份本人的实名认证（证件 + 刷脸，与这个钱包地址绑定）即自动激活。";
      if (go) go.hidden = false;
    }
  }

  function renderTotals() {
    var host = el("mst-total-metrics");
    if (!host) return;
    if (!identity()) {
      host.innerHTML = '<p class="mst-empty">连接钱包后显示总账单。</p>';
      return;
    }
    var cap = state.capacity || {};
    // 责任上限有两个来源：v1 台账锁仓、v2 钱包给托管合约的链上授权承诺，取高的那个。
    var bd = state.ceiling || {};
    var split = Number(bd.committed_usdc || 0) > Number(bd.ledger_locked_usdc || 0);
    var cells = [
      [
        "已锁仓",
        state.locked,
        split
          ? "链上授权承诺 " + money(bd.committed_usdc) + "；台账锁仓 " + money(bd.ledger_locked_usdc) + "，上限取高的那个"
          : "主身份真押在这张卡上的钱",
      ],
      ["已授权", state.allocated, "已划给各身份的额度上限"],
      ["已用", state.inUse, "执行中 + 待结算 + 争议冻结"],
      ["可用", state.available, "已授权里还能动用的部分"],
      ["待结算", num(cap.pending_settlement_credits), "已完成、等结算划转"],
      ["争议冻结", num(cap.disputed_credits), "争议未决，谁都动不了"],
    ];
    host.innerHTML = cells
      .map(function (c) {
        return (
          '<div class="mst-metric"><span class="mst-metric-k">' + esc(c[0]) + "</span>" +
          '<b class="mst-metric-v">' + money(c[1]) + "</b>" +
          '<span class="mst-metric-u">USDC</span>' +
          '<span class="mst-metric-h">' + esc(c[2]) + "</span></div>"
        );
      })
      .join("");
  }

  function renderAllocTable() {
    var host = el("mst-alloc-table");
    if (!host) return;
    if (!identity()) {
      host.innerHTML = '<p class="mst-empty">连接钱包后显示每个身份的额度。</p>';
      return;
    }
    var list = profiles();
    if (!list.length) {
      host.innerHTML =
        '<p class="mst-empty">还没有子身份可分额度。先建一个（生活助理 / 个体助理 / 企业主体），' +
        '再回来这里划额度。</p>' +
        '<div class="mst-alloc-actions"><button type="button" class="btn primary" id="mst-goto-subs">去建子身份 →</button></div>';
      var go = el("mst-goto-subs");
      if (go) {
        go.addEventListener("click", function () {
          if (global.cyberSwitchPage) global.cyberSwitchPage("identity", "life");
        });
      }
      return;
    }
    host.innerHTML = list
      .map(function (p, i) {
        var pid = String(p.profile_id);
        var row = state.allocations[pid] || {};
        var allocated = num(row.allocated_credits);
        var used =
          num(row.in_progress_credits) +
          num(row.pending_settlement_credits) +
          num(row.disputed_credits);
        var available = num(row.available_credits);
        var none = allocated <= 0;
        return (
          '<div class="mst-alloc-row' + (none ? " is-idle" : "") + '" data-pid="' + esc(pid) + '">' +
          '<div class="mst-alloc-name"><b>' + esc(titleOf(p, i)) + "</b>" +
          '<span class="mst-alloc-sub">' + (none ? "未授权" : "额度内可自主执行") + "</span></div>" +
          '<div class="mst-alloc-nums">' +
          '<span>授权 <b>' + money(allocated) + "</b></span>" +
          '<span>已用 <b>' + money(used) + "</b></span>" +
          '<span>可用 <b>' + money(available) + "</b></span>" +
          "</div>" +
          '<div class="mst-alloc-actions">' +
          '<input type="number" min="0" step="0.01" placeholder="调整金额" aria-label="调整金额" />' +
          '<button type="button" class="btn" data-alloc="up">＋ 加额</button>' +
          '<button type="button" class="btn" data-alloc="down">－ 减额</button>' +
          '<button type="button" class="btn red" data-alloc="cancel"' + (none ? " disabled" : "") + ">取消授权</button>" +
          "</div>" +
          "</div>"
        );
      })
      .join("");

    host.querySelectorAll(".mst-alloc-row").forEach(function (rowEl) {
      rowEl.querySelectorAll("[data-alloc]").forEach(function (btn) {
        btn.addEventListener("click", function () {
          onAllocAction(rowEl.getAttribute("data-pid"), btn.getAttribute("data-alloc"), rowEl);
        });
      });
    });
  }

  function renderSteps() {
    var s = sessionWallet();
    state.wallet = s.wallet || "";
    var w = el("mst-wallet-state");
    if (w) w.textContent = state.wallet ? "已连接 · " + short(state.wallet) : "未连接";
    var l = el("mst-lock-state");
    if (l) {
      var bd = state.ceiling || {};
      var split = Number(bd.committed_usdc || 0) > Number(bd.ledger_locked_usdc || 0);
      l.textContent =
        state.locked <= 0
          ? "未锁仓"
          : split
            ? "链上授权承诺 " + money(bd.committed_usdc) + " USDC（台账 " + money(bd.ledger_locked_usdc) + "）"
            : "已锁仓 " + money(state.locked) + " USDC";
    }
  }

  function renderHead() {
    var id = identity();
    var badge = el("idv-master-badge");
    var a = state.activation || {};
    if (badge) {
      badge.classList.remove("on", "bad");
      if (!id) {
        badge.textContent = "未连接钱包";
      } else if (a.activated) {
        badge.textContent = "已激活";
        badge.classList.add("on");
      } else {
        badge.textContent = activationLabel(a);
        if ((a.status || "none") === "rejected") badge.classList.add("bad");
      }
    }
    var idEl = el("idv-master-id");
    if (idEl) idEl.textContent = id ? label(id, 0) : "—";
    var wEl = el("idv-master-wallet");
    if (wEl) wEl.textContent = state.wallet ? short(state.wallet) : "—";
    var vEl = el("idv-master-verify");
    if (vEl) {
      vEl.textContent = id ? activationLabel(a) : "未激活";
      vEl.classList.toggle("ok", !!a.activated);
    }
    var mEl = el("idv-master-money");
    if (mEl) {
      mEl.textContent = id
        ? money(state.locked) + " / " + money(state.allocated) + " / " + money(state.available) + " USDC"
        : "—";
    }
    var st = el("mst-auth-state");
    if (st) st.textContent = state.allocated > 0 ? "已授权 " + money(state.allocated) + " USDC" : "未授权";
    var note = el("mst-auth-note");
    if (note) {
      note.textContent =
        "授权 = 告诉 Karma「这个身份最多能动用多少」。钱始终留在你自己的钱包里，验证通过才划转。" +
        (state.locked > 0
          ? " 主身份已锁仓 " + money(state.locked) + " USDC，已授权 " + money(state.allocated) + " USDC。"
          : " 先在第三步锁仓，这里才有额度可分。");
    }
  }

  function render() {
    renderHead();
    renderSteps();
    renderActivation();
    renderTotals();
    renderAllocTable();
  }

  async function load() {
    var status = el("mst-auth-status");
    var id = identity();
    if (!id || !api()) {
      resetState();
      state.wallet = sessionWallet().wallet || "";
      render();
      say(status, "未连接钱包");
      return;
    }
    try {
      var body = await api().getAllocations(id);
      var rows = (body && body.allocations) || [];
      var next = {};
      rows.forEach(function (r) {
        if (r && r.profile_id) next[r.profile_id] = r;
      });
      state.allocations = next;
      state.locked = num((body && body.locked_usdc) || 0);
      state.allocated = num((body && body.allocated_usdc) || 0);
      state.inUse = num((body && body.in_use_usdc) || 0);
      state.available = num((body && body.available_usdc) || 0);
      state.capacity = (body && body.capacity) || null;
      state.ceiling = (body && body.ceiling) || null;
      state.activation =
        (body && body.activation) ||
        { activated: !!(body && body.activated), status: body && body.activated ? "verified" : "none" };
      say(status, "已同步");
    } catch (e) {
      /* 读不到就按 0 显示，别把整页卡住；用户点授权时还会再报一次错。 */
      say(status, "读取失败：" + (e && (e.message || e.detail) || e), true);
    }
    render();
  }

  /** 写额度：全量 PUT（服务端按 profile_id 覆盖），所以每次都带上其它身份的现值。 */
  async function pushAllocations(pid, amount, okMsg) {
    var status = el("mst-auth-status");
    var id = identity();
    if (!id) { say(status, "请先连接钱包", true); return; }
    if (state.busy) return;
    var other = 0;
    Object.keys(state.allocations).forEach(function (k) {
      if (k !== pid) other += num(state.allocations[k].allocated_credits);
    });
    if (state.locked > 0 && other + amount > state.locked + 1e-6) {
      say(
        status,
        "超了：主身份只锁了 " + money(state.locked) + " USDC，其它身份已分走 " + money(other) +
          " USDC。先多锁一点，或先减掉别的身份的额度。",
        true
      );
      return;
    }
    state.busy = true;
    say(status, "正在写额度…");
    try {
      var next = {};
      Object.keys(state.allocations).forEach(function (k) {
        next[k] = num(state.allocations[k].allocated_credits);
      });
      next[pid] = num(amount);
      var body = await api().setAllocations(id, next);
      var rows = (body && body.allocations) || [];
      var map = {};
      rows.forEach(function (r) { if (r && r.profile_id) map[r.profile_id] = r; });
      if (rows.length) state.allocations = map;
      say(status, okMsg);
      try { document.dispatchEvent(new CustomEvent("karma-capacity-changed")); } catch (_) {}
      await load();
    } catch (e) {
      say(status, "授权失败：" + (e && (e.message || e.detail) || e), true);
    } finally {
      state.busy = false;
    }
  }

  function currentOf(pid) {
    var row = state.allocations[pid];
    return num(row && row.allocated_credits);
  }

  function onAllocAction(pid, action, rowEl) {
    if (!pid) return;
    var input = rowEl ? rowEl.querySelector("input") : null;
    var current = currentOf(pid);
    if (action === "cancel") {
      if (current <= 0) return;
      pushAllocations(pid, 0, "已取消授权");
      return;
    }
    var raw = input ? input.value : "";
    var delta = Number(raw);
    if (!isFinite(delta) || delta <= 0) {
      say(el("mst-auth-status"), "先填一个大于 0 的调整金额", true);
      if (input) input.focus();
      return;
    }
    var next = action === "up" ? current + delta : Math.max(0, current - delta);
    if (action === "down" && delta > current + 1e-9) {
      say(el("mst-auth-status"), "减不了这么多：这个身份现在只有 " + money(current) + " USDC 额度", true);
      return;
    }
    pushAllocations(pid, next, "已" + (action === "up" ? "加额到 " : "减额到 ") + money(next) + " USDC");
  }

  function bind() {
    if (!el("mst-alloc-table")) return false;
    var go = el("mst-activate-go");
    if (go) {
      go.addEventListener("click", function () {
        // 主身份本人的实名认证就在「个人助理认证」那一页（证件 + 刷脸）。
        if (global.cyberSwitchPage) global.cyberSwitchPage("identity", "personal");
      });
    }
    ["karma-wallet-connected", "karma-session-restored", "karma-capacity-changed", "karma-alloc-changed"].forEach(
      function (name) { document.addEventListener(name, function () { load(); }); }
    );
    document.addEventListener("karma-profile-switched", function () { render(); });
    document.addEventListener("karma-page-shown", function (ev) {
      var page = ev && ev.detail && ev.detail.page;
      if (page === "identity" || page === "overview") load();
    });
    return true;
  }

  function boot() {
    if (!bind()) return;
    load();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();

  global.KarmaMasterPage = { reload: load, state: state };
})(window);