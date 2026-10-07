/**
 * 操作台 · 验证者身份（自助申请页）。
 *
 * 这一页只回答两个问题：
 *   1. **怎么拿到节点资格** —— 一把节点自己的 key、登记节点、跑起来出证；
 *   2. **能拿多少** —— 收益标准与收益率，口径来自 GET /v1/console/economy-policy。
 *
 * 页面**不写死任何一个数字**：费率、夹逼上下限、门限席位全从后端读。
 * 前端写死 = 用户照着页面算出来的收益迟早和后端参数对不上，那就是在骗人。
 *
 * 这里是**自助**入口，任何登录身份都看得到 —— 和「验证者网络」那个只读看板不同，
 * 那个按 can_view_verifier_network 显隐、只给运维看。登记节点本身也没有白名单：
 * 真正的闸门在节点侧（出证要被接受，得先质押到位）。
 *
 * 文案一律整句走 T() / Tf()，不拼半句。
 */
(function () {
  "use strict";

  var POLICY_PATH = "/v1/console/economy-policy";
  var NODE_PATH = "/v1/verifiers";

  var state = { policy: null, mine: null, wallet: "" };

  function byId(id) { return document.getElementById(id); }
  function api() { return window.cyberKarmaApi || {}; }

  function authed() {
    try { return !!(window.KARMA_ACCESS_TOKEN || window.KARMA_IDENTITY_ID); } catch (_) { return false; }
  }

  function T(zh) {
    var i18n = window.CYBER_I18N;
    return i18n && i18n.T ? i18n.T(zh) : zh;
  }

  function Tf(zh) {
    var i18n = window.CYBER_I18N;
    if (i18n && i18n.Tf) return i18n.Tf.apply(i18n, arguments);
    var out = T(zh);
    for (var i = 1; i < arguments.length; i += 1) {
      out = out.split("{" + (i - 1) + "}").join(arguments[i] == null ? "" : String(arguments[i]));
    }
    return out;
  }

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"\']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "\'": "&#39;" }[c];
    });
  }

  function say(node, text, ok) {
    if (!node) return;
    node.textContent = text == null ? "\u2014" : String(text);
    node.classList.remove("ok", "err");
    if (ok === true) node.classList.add("ok");
    if (ok === false) node.classList.add("err");
    if (window.CYBER_I18N && window.CYBER_I18N.applyPhrase) window.CYBER_I18N.applyPhrase(node);
  }

  function num(value, digits) {
    var n = Number(value);
    if (!isFinite(n)) return "\u2014";
    return n.toFixed(digits == null ? 2 : digits);
  }

  function addr(value) {
    var s = String(value || "");
    if (!s) return "\u2014";
    if (s.length <= 14) return s;
    return s.slice(0, 8) + "\u2026" + s.slice(-4);
  }

  function rowHtml(label, valueHtml, hint) {
    return (
      '<div class="rate-row"><span class="rate-k">' + esc(label) + '</span>' +
      '<b class="rate-v">' + valueHtml + '</b>' +
      (hint ? '<i class="rate-h">' + esc(hint) + "</i>" : "") +
      "</div>"
    );
  }

  function currentWallet() {
    var input = byId("vi-wallet");
    if (input && input.value) return String(input.value).trim();
    try {
      var bound = document.querySelector("[data-wallet]");
      if (bound && bound.value) return String(bound.value).trim();
    } catch (_) {}
    return "";
  }

  // ---- 收益口径 -------------------------------------------------------------

  function renderPolicy() {
    var host = byId("vi-policy");
    var st = byId("vi-policy-state");
    if (!host) return;
    var p = state.policy;
    if (!p) {
      host.innerHTML = "";
      say(st, T("还没读到收益口径。"), false);
      return;
    }
    var v = p.verifier || {};
    var s = p.settlement || {};
    var pre = p.preview || {};
    var sample = num(p.sample_case_value_usdc, 2);
    var seats = num(v.quorum_required, 0);
    var rows = [
      rowHtml(T("出证资格"), esc(v.open_join ? T("任何登录身份都能登记节点") : T("平台点名")), ""),
      rowHtml(T("启动门槛"), esc(Tf("案值 ≥ {0} USDC 才走门限核验，小额单走平台单机核验", num(v.min_case_value_usdc, 2))), ""),
      rowHtml(T("每条出证"), esc(Tf("案值 × {0} bp，夹在 {1} 到 {2} USDC 之间", num(v.reward_bps, 2), num(v.reward_min_usdc, 4), num(v.reward_max_usdc, 4))), ""),
      rowHtml(T("计入门限"), esc(Tf("共 {0} 席，只有计入门限的那 {0} 席拿钱", seats)), ""),
      rowHtml(T("样例"), esc(Tf("案值 {0} USDC：每条出证 {1} USDC，全庭 {2} USDC", sample, num(pre.verifier_reward_per_attestation_usdc, 4), num(pre.verifier_reward_per_panel_usdc, 4))), ""),
      rowHtml(T("误判"), esc(v.slash_on_false_attestation ? T("不付奖励，并罚没质押") : T("不付奖励")), ""),
      rowHtml(T("收入来源"), esc(Tf("结算手续费，当前费率 {0} bp", num(s.fee_bps, 2))), ""),
      rowHtml(T("公布状态"), esc(p.status === "policy-preview" ? T("口径已定、结算侧还没接上：先按预告公示") : String(p.status || "\u2014")), ""),
    ];
    host.innerHTML = rows.join("");
    say(st, T("已同步"), true);
  }

  // ---- 我的节点 -------------------------------------------------------------

  function renderMine() {
    var host = byId("vi-mine");
    if (!host) return;
    var wallet = currentWallet();
    var node = state.mine;
    if (!wallet) {
      host.innerHTML = rowHtml(T("我的节点"), esc(T("先连接钱包：节点钱包地址会自动填进来")), "");
      return;
    }
    if (!node) {
      host.innerHTML = rowHtml(T("我的节点"), esc(T("这个钱包还没有登记过节点")), "");
      return;
    }
    var rate = node.total_attestations > 0
      ? Tf("{0} / {1}", node.successful_attestations || 0, node.total_attestations || 0)
      : "\u2014";
    host.innerHTML = [
      rowHtml(T("我的节点"), esc(addr(node.wallet_address)), addr(node.id)),
      rowHtml(T("质押"), esc(num(node.stake_amount, 2)) + " USDC", ""),
      rowHtml(T("声誉"), esc(num(node.reputation_score, 4)), ""),
      rowHtml(T("出证（成功 / 总计）"), esc(rate), ""),
      rowHtml(T("状态"), esc(node.is_active ? T("活跃") : T("停用")), ""),
    ].join("");
  }

  function findMine(list, wallet) {
    var target = String(wallet || "").toLowerCase();
    if (!target) return null;
    for (var i = 0; i < list.length; i += 1) {
      var w = String((list[i] || {}).wallet_address || "").toLowerCase();
      if (w && w === target) return list[i];
    }
    return null;
  }

  // ---- 读取 -----------------------------------------------------------------

  async function load() {
    var st = byId("vi-state");
    if (!authed()) {
      say(st, T("还没认证：请先用右上角「连接钱包」完成认证。"), false);
      renderPolicy();
      renderMine();
      return;
    }
    say(st, T("读取中…"), null);
    var results = await Promise.all([
      api().karmaFetch(POLICY_PATH, { method: "GET", headers: api().headers() }).catch(function (e) { return { __err: e }; }),
      api().karmaFetch(NODE_PATH + "?limit=200&offset=0", { method: "GET", headers: api().headers() }).catch(function (e) { return { __err: e }; }),
    ]);
    var policy = results[0];
    var nodes = results[1];
    if (policy && !policy.__err) state.policy = policy;
    if (nodes && !nodes.__err) {
      state.mine = findMine(nodes.verifiers || [], currentWallet());
    }
    renderPolicy();
    renderMine();
    var err = (policy && policy.__err) || (nodes && nodes.__err);
    if (err) {
      if (err.status === 401) say(st, T("还没认证：请先用右上角「连接钱包」完成认证。"), false);
      else say(st, Tf("读取失败：{0}", (err && err.message) || err), false);
      return;
    }
    say(st, T("已同步"), true);
  }

  async function registerNode() {
    var st = byId("vi-reg-state");
    var wallet = currentWallet();
    var stake = byId("vi-stake") ? String(byId("vi-stake").value || "").trim() : "";
    var endpoint = byId("vi-endpoint") ? String(byId("vi-endpoint").value || "").trim() : "";
    if (!wallet) { say(st, T("请填节点钱包地址。"), false); return; }
    if (!stake || Number(stake) <= 0) { say(st, T("请填质押额（要大于 0）。"), false); return; }
    say(st, T("提交中…"), null);
    try {
      await api().karmaFetch(NODE_PATH + "/register", {
        method: "POST",
        headers: api().headers(),
        body: JSON.stringify({
          wallet_address: wallet,
          stake_amount: Number(stake),
          endpoint_url: endpoint || null,
        }),
      });
      say(st, T("登记成功：节点已经进入网络。"), true);
      await load();
    } catch (e) {
      if (e && e.status === 409) say(st, T("这个钱包已经登记过节点了。"), false);
      else say(st, Tf("登记失败：{0}", (e && e.message) || e), false);
    }
  }

  // ---- 绑定 -----------------------------------------------------------------

  function visible() {
    var sec = byId("verifier-id");
    return !!(sec && sec.classList.contains("active"));
  }

  function bind() {
    var reg = byId("vi-register");
    if (reg) reg.addEventListener("click", function () { registerNode().catch(function () {}); });
    var wallet = byId("vi-wallet");
    if (wallet) wallet.addEventListener("change", function () { renderMine(); });

    document.addEventListener("karma-page-shown", function (ev) {
      var detail = (ev && ev.detail) || {};
      if (detail.page !== "verifier-id") return;
      load().catch(function () {});
    });
    ["karma-wallet-connected", "karma-session-restored", "karma-profile-switched", "karma-caps-ready"].forEach(
      function (name) {
        document.addEventListener(name, function () { if (visible()) load().catch(function () {}); });
      }
    );

    if (visible()) load().catch(function () {});
  }

  window.KarmaVerifierIdentity = { refresh: load, state: state };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind);
  } else {
    bind();
  }
})();
