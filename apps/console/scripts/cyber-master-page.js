/**
 * 操作台 · 主身份页的第 ③ 步「授权给身份」。
 *
 * 主身份只做三件事：连接钱包 → 锁仓 USDC → 授权给身份。这里就是第三步：
 * 选一个子身份，划给它一个额度上限（读写同一份 capacity 账本）。
 *
 *   GET  /v1/capacity/{identity}/allocations   看现在各身份分到多少
 *   PUT  /v1/capacity/{identity}/allocations   改额度
 *
 * 权限、边界、单笔/日上限和 Karma 授权 SDK 仍在「Agent 接入 › 授权向导」里一次配完，
 * 两边读写同一份数据 —— 在这里改完，向导那边刷新就是新数字。
 * 安全边界：只用 SIWE 会话，不碰私钥 / 助记词。
 */
(function (global) {
  "use strict";

  var state = { allocations: {}, locked: 0, busy: false };

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
  function say(node, msg, isErr) {
    if (!node) return;
    node.textContent = msg;
    node.classList.toggle("err", !!isErr);
  }

  /** 身份号一律走对外写法（Kid1… / kid02…），别把 kid_ 原文写进界面。 */
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

  /** ① 连接钱包 / ② 锁仓 的状态角标：跟着会话和账本走，别写死。 */
  function renderStepStates() {
    var s = sessionWallet();
    var w = el("mst-wallet-state");
    if (w) w.textContent = s.wallet ? "已连接 · " + short(s.wallet) : "未连接";
    var l = el("mst-lock-state");
    if (l) l.textContent = state.locked > 0 ? "已锁仓 " + num(state.locked) + " USDC" : "未锁仓";
  }

  function profiles() {
    var sw = global.KarmaIdentitySwitcher;
    var list = (sw && sw.getProfiles ? sw.getProfiles() : []) || [];
    return list.filter(function (p) { return p && p.profile_id; });
  }

  function render() {
    var sel = el("mst-auth-identity");
    if (!sel) return;
    var sw = global.KarmaIdentitySwitcher;
    var list = profiles();
    var keep = sel.value;
    if (!list.length) {
      sel.innerHTML = '<option value="">还没有子身份 —— 先去「身份 · 认证 › 个人助理认证」建一个</option>';
    } else {
      sel.innerHTML = list
        .map(function (p, i) {
          var title = (sw && sw.identityTitle ? sw.identityTitle(p) : "") || p.display_name || "子身份";
          var amt = num(state.allocations[p.profile_id]);
          var tail = amt > 0 ? "（已授权 " + amt + "）" : "";
          return (
            '<option value="' + esc(p.profile_id) + '">' +
            esc(title + " · " + label(p.profile_id, i + 1) + tail) +
            "</option>"
          );
        })
        .join("");
    }
    if (keep && list.some(function (p) { return p.profile_id === keep; })) sel.value = keep;

    var current = sel.value ? num(state.allocations[sel.value]) : 0;
    var amountEl = el("mst-auth-amount");
    if (amountEl && !amountEl.value) amountEl.value = current ? String(current) : "";

    var allocated = 0;
    Object.keys(state.allocations).forEach(function (k) { allocated += num(state.allocations[k]); });
    var st = el("mst-auth-state");
    if (st) st.textContent = allocated > 0 ? "已授权 " + num(allocated) + " USDC" : "未授权";
    renderStepStates();
    var note = el("mst-auth-note");
    if (note) {
      note.textContent =
        "授权 = 告诉 Karma「这个身份最多能动用多少」。钱始终留在你自己的钱包里，验证通过才划转。" +
        (state.locked > 0
          ? " 主身份已锁仓 " + num(state.locked) + " USDC，已分配给子身份 " + num(allocated) + " USDC。"
          : " 先在第二步锁仓，这里才有额度可分。");
    }
  }

  async function load() {
    var status = el("mst-auth-status");
    if (!identity() || !api()) {
      state.allocations = {};
      state.locked = 0;
      renderStepStates();
      render();
      say(status, "未连接钱包");
      return;
    }
    try {
      var body = await api().getAllocations(identity());
      var rows = (body && body.allocations) || [];
      var next = {};
      rows.forEach(function (r) {
        if (r && r.profile_id) next[r.profile_id] = num(r.allocated_credits);
      });
      state.allocations = next;
      state.locked = num((body && body.locked_usdc) || 0);
    } catch (_) {
      /* 读不到就按 0 显示，别把整页卡住；用户点授权时还会再报一次错。 */
    }
    render();
    say(status, "已同步");
  }

  async function save() {
    var status = el("mst-auth-status");
    var id = identity();
    if (!id) { say(status, "请先连接钱包", true); return; }
    if (state.busy) return;
    var sel = el("mst-auth-identity");
    var pid = sel ? sel.value : "";
    if (!pid) { say(status, "还没有子身份可分额度", true); return; }
    var amount = Number((el("mst-auth-amount") || {}).value || 0);
    if (!isFinite(amount) || amount < 0) { say(status, "请填一个不小于 0 的额度", true); return; }
    var other = 0;
    Object.keys(state.allocations).forEach(function (k) {
      if (k !== pid) other += num(state.allocations[k]);
    });
    if (state.locked > 0 && other + amount > state.locked + 1e-6) {
      say(status, "超了：主身份只锁了 " + num(state.locked) + " USDC，别的身份已分走 " + num(other) + " USDC。先多锁一点。", true);
      return;
    }
    state.busy = true;
    say(status, "正在写额度…");
    try {
      var next = {};
      Object.keys(state.allocations).forEach(function (k) { next[k] = num(state.allocations[k]); });
      next[pid] = amount;
      await api().setAllocations(id, next);
      state.allocations = next;
      render();
      say(status, "已授权 " + num(amount) + " USDC");
      try { document.dispatchEvent(new CustomEvent("karma-capacity-changed")); } catch (_) {}
    } catch (e) {
      say(status, "授权失败：" + (e && (e.message || e.detail) || e), true);
    } finally {
      state.busy = false;
    }
  }

  function bind() {
    if (!el("mst-auth-save")) return true;
    el("mst-auth-save").addEventListener("click", function () { save(); });
    var sel = el("mst-auth-identity");
    if (sel) {
      sel.addEventListener("change", function () {
        var amountEl = el("mst-auth-amount");
        if (amountEl) amountEl.value = sel.value ? String(num(state.allocations[sel.value]) || "") : "";
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