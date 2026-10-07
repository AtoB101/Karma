/**
 * 操作台 · 验证者网络（只读看板）。
 *
 * 这里是**机器节点**网络：注册、质押、出证（attestation）、挑战（challenge）。
 * 它和「复核台」不是一回事 —— 复核台管的是**人**（治理发放方）的审批队列，
 * 这一页管的是机器节点当前的网络状态。
 *
 * 这一页是**只读**的，故意如此：
 *  - 质押、出证、开挑战都由节点程序（agent 侧）完成，操作台不代签、不代发；
 *  - 看板只把「谁在线、押了多少、声誉多少、出证成功多少」摊开。
 * 想在浏览器里点一下就把节点的钱挪走，这条路本来就不该存在。
 *
 * 显隐按 ``/v1/console/capabilities`` 的 ``can_view_verifier_network``：
 * 它只对管理员 / 治理发放方开放；真正的数据闸门仍在后端
 * （``_protected_dependencies`` + 运维白名单）。
 *
 * 文案一律走整句：T() / Tf()，不拼半句。
 */
(function () {
  "use strict";

  var PATH = "/v1/verifiers";

  // 侧栏子项 -> 只显示哪一张卡（"" = 全显示）。
  var SUB_MODE = {
    nodes: "vn-nodes",
    stats: "vn-stats-card",
  };

  var state = { list: [], total: 0, stats: null };

  function byId(id) {
    return document.getElementById(id);
  }

  function api() {
    return window.cyberKarmaApi || {};
  }

  /** 会话没建起来之前不发请求 —— 发出去只会得到一条裸 401。 */
  function authed() {
    try {
      return !!(window.KARMA_ACCESS_TOKEN || window.KARMA_IDENTITY_ID);
    } catch (_) {
      return false;
    }
  }

  /** 当前这个身份能不能看这张看板（未知 = 不能，宁可不画）。 */
  function permitted() {
    try {
      var caps = window.KarmaConsoleCaps;
      if (caps && caps.get && caps.get().can_view_verifier_network === true) return true;
    } catch (_) {}
    return false;
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
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function say(node, text, ok) {
    if (!node) return;
    node.textContent = text == null ? "\u2014" : String(text);
    node.classList.remove("ok", "err");
    if (ok === true) node.classList.add("ok");
    if (ok === false) node.classList.add("err");
  }

  function addr(value) {
    var s = String(value || "");
    if (s.length <= 12) return s || "\u2014";
    return s.slice(0, 6) + "\u2026" + s.slice(-4);
  }

  function num(value, digits) {
    var n = Number(value);
    if (!isFinite(n)) return "\u2014";
    return n.toFixed(digits == null ? 2 : digits);
  }

  // ---- 渲染 -----------------------------------------------------------------

  function statsHtml(stats) {
    var s = stats || {};
    var tiles = [
      ["验证者总数", String(s.total_verifiers == null ? 0 : s.total_verifiers)],
      ["活跃验证者", String(s.active_verifiers == null ? 0 : s.active_verifiers)],
      ["累计出证", String(s.total_attestations == null ? 0 : s.total_attestations)],
      ["累计挑战", String(s.total_challenges == null ? 0 : s.total_challenges)],
      ["未结挑战", String(s.open_challenges == null ? 0 : s.open_challenges)],
      ["平均声誉", num(s.average_reputation, 4)],
    ];
    return tiles
      .map(function (pair) {
        return (
          '<div class="vn-stat"><span class="vn-stat-k">' +
          esc(pair[0]) +
          '</span><b class="vn-stat-v">' +
          esc(pair[1]) +
          "</b></div>"
        );
      })
      .join("");
  }

  function rowHtml(v) {
    var active = v.is_active
      ? '<span class="vn-pill ok">' + esc(T("活跃")) + "</span>"
      : '<span class="vn-pill">' + esc(T("停用")) + "</span>";
    var rate =
      v.total_attestations > 0
        ? Tf("{0} / {1}", v.successful_attestations || 0, v.total_attestations || 0)
        : "\u2014";
    return (
      "<tr><td>" +
      esc(addr(v.id)) +
      "</td><td>" +
      esc(addr(v.wallet_address)) +
      "</td><td>" +
      esc(num(v.stake_amount, 2)) +
      "</td><td>" +
      esc(num(v.reputation_score, 4)) +
      "</td><td>" +
      esc(rate) +
      "</td><td>" +
      active +
      "</td><td>" +
      esc(addr(v.endpoint_url)) +
      "</td></tr>"
    );
  }

  function render() {
    byId("vn-stats").innerHTML = statsHtml(state.stats);
    var rows = state.list || [];
    if (!rows.length) {
      byId("vn-list").innerHTML = '<tr><td colspan="7" class="vn-empty">' + esc(T("还没有注册的验证者节点")) + "</td></tr>";
    } else {
      byId("vn-list").innerHTML = rows.map(rowHtml).join("");
    }
    say(byId("vn-count"), Tf("共 {0} 个节点", state.total || 0), null);
  }

  /** 只显示当前子项对应的那张卡（子项为空 = 全显示）。 */
  function applyMode(mode) {
    var only = SUB_MODE[mode] || "";
    ["vn-stats-card", "vn-nodes"].forEach(function (id) {
      var node = byId(id);
      if (node) node.hidden = !!only && id !== only;
    });
  }

  // ---- 读取 -----------------------------------------------------------------

  async function load() {
    var st = byId("vn-state");
    var deny = byId("vn-deny");
    if (deny) deny.hidden = true;

    if (!permitted()) {
      say(st, T("这个身份不在管理员 / 治理发放方白名单里。"), false);
      if (deny) {
        deny.hidden = false;
        deny.textContent = T(
          "这个身份打不开验证者网络：它只对管理员或治理发放方开放。名单在服务器上，需要平台点名开通。"
        );
        if (window.CYBER_I18N && window.CYBER_I18N.applyPhrase) window.CYBER_I18N.applyPhrase(deny);
      }
      return;
    }
    if (!authed()) {
      say(st, T("还没认证：请先用右上角「连接钱包」完成认证。"), false);
      return;
    }

    var activeOnly = !!(byId("vn-active-only") || {}).checked;
    var qs = "?active_only=" + (activeOnly ? "true" : "false") + "&limit=200&offset=0";
    say(st, T("读取中…"), null);
    try {
      var results = await Promise.all([
        api().karmaFetch(PATH + qs, { method: "GET", headers: api().headers() }),
        api().karmaFetch(PATH + "/network/stats", { method: "GET", headers: api().headers() }),
      ]);
      var body = results[0] || {};
      state.list = body.verifiers || [];
      state.total = body.total == null ? state.list.length : body.total;
      state.stats = results[1] || {};
      render();
      say(st, T("已同步"), true);
    } catch (e) {
      var status = e && e.status;
      if (status === 401) say(st, T("还没认证：请先用右上角「连接钱包」完成认证。"), false);
      else if (status === 403) say(st, T("没有权限：这个身份看不到验证者网络。"), false);
      else say(st, Tf("读取失败：{0}", (e && e.message) || e), false);
      if (window.CYBER_I18N && window.CYBER_I18N.applyPhrase) window.CYBER_I18N.applyPhrase(byId("vn-state"));
    }
  }

  // ---- 绑定 -----------------------------------------------------------------

  function visible() {
    var sec = byId("verifiers");
    return !!(sec && sec.classList.contains("active"));
  }

  function bind() {
    var rf = byId("vn-refresh");
    if (rf) rf.addEventListener("click", load);
    var ao = byId("vn-active-only");
    if (ao) ao.addEventListener("change", load);

    document.addEventListener("karma-page-shown", function (ev) {
      var detail = (ev && ev.detail) || {};
      if (detail.page !== "verifiers") return;
      applyMode(detail.sub);
      load();
    });
    document.addEventListener("karma-caps-ready", function () {
      if (visible()) load();
    });
    document.addEventListener("karma-wallet-connected", function () {
      if (visible()) load();
    });
    document.addEventListener("karma-session-restored", function () {
      if (visible()) load();
    });

    applyMode("");
    if (visible()) load();
  }

  window.KarmaVerifierNetworkConsole = { refresh: load, state: state, applyMode: applyMode };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind);
  } else {
    bind();
  }
})();