/**
 * 操作台 · 仲裁者身份（自助申请页）。
 *
 * 顺序就是用户说的那样：**先认证，再抵押**，两样齐了才算仲裁员。
 *   * 认证 = 治理角色档案（class=arbitrator）——「谁在裁」；
 *   * 抵押 = 已锁仓 USDC 入池 ——「裁错了赔得起」。
 *
 * 两条路的开放状态都**现读后端**（GET /v1/console/economy-policy 的 arbitrator 段，
 * 它直接读 arbitration_rules / governance_stake 那两处闸门），页面不自己下结论：
 * 页面上写着「可以申请」而接口回 403，是这套口径发霉的开始。
 *
 * 入池只给自己入（后端 require_identity_binding 硬拦），所以这里的身份一律用
 * 会话里的主身份，不用「当前选中那张子身份卡」—— 仲裁员是自然人，不是 agent。
 */
(function () {
  "use strict";

  var POLICY_PATH = "/v1/console/economy-policy";
  var POOL_PATH = "/v1/arbitration/pool";
  var JOIN_PATH = "/v1/arbitration/pool/join";
  var PROFILES_PATH = "/v1/identity/role-profiles";
  var CAPACITY_PATH = "/v1/capacity/";

  var state = { policy: null, mine: null, cert: null, locked: null };

  function byId(id) { return document.getElementById(id); }
  function api() { return window.cyberKarmaApi || {}; }

  function authed() {
    try { return !!(window.KARMA_ACCESS_TOKEN || window.KARMA_IDENTITY_ID); } catch (_) { return false; }
  }

  /** 主身份：仲裁员是自然人，入池/建档都走它，不跟「当前选中的子身份卡」走。 */
  function identity() {
    try { return String(window.KARMA_IDENTITY_ID || "").trim(); } catch (_) { return ""; }
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

  function rowHtml(label, valueHtml, hint) {
    return (
      '<div class="rate-row"><span class="rate-k">' + esc(label) + '</span>' +
      '<b class="rate-v">' + valueHtml + '</b>' +
      (hint ? '<i class="rate-h">' + esc(hint) + "</i>" : "") +
      "</div>"
    );
  }

  // ---- 认证 -----------------------------------------------------------------

  function renderCert() {
    var host = byId("ai-cert-body");
    var st = byId("ai-cert-state");
    if (!host) return;
    var p = (state.policy || {}).arbitrator || {};
    var own = !!state.cert;
    var rows = [
      rowHtml(T("认证状态"), esc(own ? T("已开通仲裁资格") : T("还没开通")), ""),
      rowHtml(T("认证路径"), esc(p.self_serve_profile ? T("平台已开放自助申请：凭锁仓质押即可开通") : T("当前由平台点名发放")), ""),
      rowHtml(T("认证是什么"), esc(T("一份治理角色档案：它记的是「谁在裁」，不含任何资金权限")), ""),
    ];
    host.innerHTML = rows.join("");
    if (own) say(st, T("已开通"), true);
    else say(st, T("未开通"), null);
  }

  async function applyCert() {
    var st = byId("ai-cert-state");
    var who = identity();
    if (!who) { say(st, T("还没认证：请先用右上角「连接钱包」完成认证。"), false); return; }
    say(st, T("提交中…"), null);
    try {
      var row = await api().karmaFetch(PROFILES_PATH, {
        method: "POST",
        headers: api().headers(),
        body: JSON.stringify({ owner_identity_id: who, class: "arbitrator" }),
      });
      state.cert = row || true;
      renderCert();
      say(st, T("已开通仲裁资格"), true);
    } catch (e) {
      if (e && e.status === 403) {
        say(st, Tf("{0} 是治理角色，不能自助开通：请由运维把身份加入 GOVERNANCE_VERIFIER_IDS，或让服务端打开 GOVERNANCE_OPEN_JOIN 后凭锁仓质押开通", T("仲裁员")), false);
      } else if (e && e.status === 401) {
        say(st, T("还没认证：请先用右上角「连接钱包」完成认证。"), false);
      } else {
        say(st, Tf("申请失败：{0}", (e && e.message) || e), false);
      }
    }
  }

  // ---- 入池 -----------------------------------------------------------------

  function renderMine() {
    var host = byId("ai-mine");
    if (!host) return;
    var p = (state.policy || {}).arbitrator || {};
    var mine = state.mine;
    var locked = state.locked;
    var rows = [
      rowHtml(T("入池资格"), esc(p.open_join ? T("平台已开放自助入池") : T("当前仅限平台点名")), ""),
      rowHtml(
        T("入池状态"),
        esc(mine ? Tf("已入池，质押 {0} USDC", num(mine.stake_amount, 2)) : T("还没入池")),
        mine && mine.status ? String(mine.status) : ""
      ),
      rowHtml(T("已锁仓 USDC"), esc(locked == null ? "\u2014" : num(locked, 2)), T("质押必须由这笔钱背书")),
      rowHtml(T("质押下限"), esc(Number(p.min_stake_usdc) > 0 ? Tf("不低于 {0} USDC", num(p.min_stake_usdc, 2)) : T("只要大于 0")), ""),
      rowHtml(T("抵押要求"), esc(Tf("质押必须严格大于案值 × {0}", num(p.coverage_multiple, 2))), T("被处理的订单金额必须低于抵押")),
    ];
    host.innerHTML = rows.join("");
  }

  function renderPolicy() {
    var host = byId("ai-policy");
    var st = byId("ai-policy-state");
    if (!host) return;
    var p = state.policy;
    if (!p) {
      host.innerHTML = "";
      say(st, T("还没读到收益口径。"), false);
      return;
    }
    var a = p.arbitrator || {};
    var pre = p.preview || {};
    var rows = [
      rowHtml(T("立案费"), esc(Tf("案值 × {0} bp，夹在 {1} 到 {2} USDC 之间", num(a.fee_bps, 2), num(a.fee_min_usdc, 2), num(a.fee_max_usdc, 2))), ""),
      rowHtml(T("谁来承担"), esc(a.loser_pays ? T("败诉方承担，赢家不亏") : T("立案方承担")), ""),
      rowHtml(T("分庭人数"), esc(Tf("落在 {0} 到 {1} 席之间", num(a.panel_min, 0), num(a.panel_max, 0))), T("按案件声明的席数派庭")),
      rowHtml(T("样例"), esc(Tf("案值 {0} USDC：立案费 {1} USDC", num(p.sample_case_value_usdc, 2), num(pre.arbitrator_fee_usdc, 2))), ""),
      rowHtml(T("被推翻"), esc(Tf("按立案费的 {0} 倍从该庭抵押里罚", num(a.slash_multiple, 2))), ""),
      rowHtml(T("派庭与执行"), esc(T("需要仲裁员或管理员白名单")), T("表决只认被指派到本案、且抵押覆盖案值的仲裁员")),
      rowHtml(T("公布状态"), esc(p.status === "policy-preview" ? T("口径已定、结算侧还没接上：先按预告公示") : String(p.status || "\u2014")), ""),
    ];
    host.innerHTML = rows.join("");
    say(st, T("已同步"), true);
  }

  async function joinPool() {
    var st = byId("ai-stake-state");
    var who = identity();
    var field = byId("ai-stake");
    var stake = field ? String(field.value || "").trim() : "";
    if (!who) { say(st, T("还没认证：请先用右上角「连接钱包」完成认证。"), false); return; }
    if (!stake || Number(stake) <= 0) { say(st, T("请填质押额（要大于 0）。"), false); return; }
    say(st, T("提交中…"), null);
    try {
      await api().karmaFetch(JOIN_PATH, {
        method: "POST",
        headers: api().headers(),
        body: JSON.stringify({ arbitrator_identity_id: who, stake_amount: Number(stake) }),
      });
      say(st, T("入池成功。"), true);
      await load();
    } catch (e) {
      if (e && e.status === 409) say(st, T("质押没有被锁仓背书：先锁仓、或把质押下调到锁仓以内。"), false);
      else if (e && e.status === 403) say(st, T("这个身份现在不能入池：入池资格还没开放。"), false);
      else if (e && e.status === 422) say(st, T("质押额不合规：要大于 0，且不低于平台下限。"), false);
      else say(st, Tf("入池失败：{0}", (e && e.message) || e), false);
    }
  }

  // ---- 读取 -----------------------------------------------------------------

  async function load() {
    var st = byId("ai-state");
    if (!authed()) {
      say(st, T("还没认证：请先用右上角「连接钱包」完成认证。"), false);
      renderCert();
      renderMine();
      renderPolicy();
      return;
    }
    var who = identity();
    say(st, T("读取中…"), null);
    var jobs = [
      api().karmaFetch(POLICY_PATH, { method: "GET", headers: api().headers() }).catch(function (e) { return { __err: e }; }),
      api().karmaFetch(POOL_PATH, { method: "GET", headers: api().headers() }).catch(function (e) { return { __err: e }; }),
    ];
    if (who) {
      jobs.push(
        api().karmaFetch(PROFILES_PATH + "?owner_identity_id=" + encodeURIComponent(who), { method: "GET", headers: api().headers() }).catch(function (e) { return { __err: e }; })
      );
      jobs.push(
        api().karmaFetch(CAPACITY_PATH + encodeURIComponent(who), { method: "GET", headers: api().headers() }).catch(function (e) { return { __err: e }; })
      );
    }
    var out = await Promise.all(jobs);
    var policy = out[0];
    var pool = out[1];
    var profiles = out[2];
    var capacity = out[3];
    if (policy && !policy.__err) state.policy = policy;
    if (pool && !pool.__err) {
      var rows = pool || [];
      state.mine = null;
      for (var i = 0; i < rows.length; i += 1) {
        if (rows[i] && rows[i].arbitrator_identity_id === who) { state.mine = rows[i]; break; }
      }
    }
    if (profiles && !profiles.__err) {
      var list = (profiles && (profiles.items || profiles.profiles || profiles)) || [];
      state.cert = null;
      for (var j = 0; j < list.length; j += 1) {
        var p = list[j] || {};
        if (p["class"] === "arbitrator" && p.status === "active") { state.cert = p; break; }
      }
    }
    if (capacity && !capacity.__err && capacity) state.locked = Number(capacity.total_locked_usdc) || 0;

    renderCert();
    renderMine();
    renderPolicy();
    var err = (policy && policy.__err) || (pool && pool.__err);
    if (err) {
      if (err.status === 401) say(st, T("还没认证：请先用右上角「连接钱包」完成认证。"), false);
      else say(st, Tf("读取失败：{0}", (err && err.message) || err), false);
      return;
    }
    say(st, T("已同步"), true);
  }

  // ---- 绑定 -----------------------------------------------------------------

  function visible() {
    var sec = byId("arbiter-id");
    return !!(sec && sec.classList.contains("active"));
  }

  function bind() {
    var join = byId("ai-join");
    if (join) join.addEventListener("click", function () { joinPool().catch(function () {}); });
    var apply = byId("ai-cert-apply");
    if (apply) apply.addEventListener("click", function () { applyCert().catch(function () {}); });
    var rf = byId("ai-refresh");
    if (rf) rf.addEventListener("click", function () { load().catch(function () {}); });

    document.addEventListener("karma-page-shown", function (ev) {
      var detail = (ev && ev.detail) || {};
      if (detail.page !== "arbiter-id") return;
      load().catch(function () {});
    });
    ["karma-wallet-connected", "karma-session-restored", "karma-profile-switched", "karma-caps-ready"].forEach(
      function (name) {
        document.addEventListener(name, function () { if (visible()) load().catch(function () {}); });
      }
    );

    if (visible()) load().catch(function () {});
  }

  window.KarmaArbitratorIdentity = { refresh: load, state: state };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind);
  } else {
    bind();
  }
})();
