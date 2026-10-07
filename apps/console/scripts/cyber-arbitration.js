/**
 * 操作台 · 仲裁台（运营侧工作面）。
 *
 * 只有仲裁员 / 管理员白名单里的人看得到这个入口。前端按
 * ``/v1/console/capabilities`` 的 ``can_operate_arbitration`` 显隐，
 * **真正的闸门**是后端那三道 ``require_arbitration_operator`` /
 * ``require_admin_actor``（services/actor_guards.py）—— 这里少画一个按钮
 * 不算安全，多画一个按钮也过不去。
 *
 * 三条不能破的线：
 *  1. 裁决直接决定钱去哪，所以「执行裁决」必须先确认一次，而且它只对
 *     ``decided`` 状态的案子可用（后端也拦）；
 *  2. 投票必须指名**被指派到本案**的仲裁员身份 —— 身份不是手打，是
 *     从 ``/cases/{id}/assignments`` 拉出来给人选（后端还会再校验抵押覆盖）；
 *  3. 所有数字都摊开给人看，但结论是人按的：告警只提示，不替人裁决。
 *
 * 文案一律走整句：译表按「中文整句 -> 译文」查，拼出来的半句查不到，
 * 所以在 JS 里一律用 T() / Tf() 包整句，不做字符串相加。
 */
(function () {
  "use strict";

  var PATH = "/v1/arbitration";

  var STATUS_LABEL = {
    open: "待派庭",
    voting: "投票中",
    decided: "已裁决",
    executed: "已执行",
    cancelled: "已取消",
  };

  var DECISION_LABEL = {
    buyer_wins: "买方胜",
    seller_wins: "卖方胜",
    partial: "部分赔付",
  };

  var STAGE_LABEL = {
    open: "待派庭",
    voting: "待投票",
    decided_pending_execution: "已裁决待执行",
  };

  var ALERT_LABEL = {
    open_case_backlog: "待派庭积压",
    voting_case_backlog: "投票积压",
    decision_timeout_risk: "裁决超期风险",
    decision_partial_spike: "部分裁决激增",
  };

  var EVENT_LABEL = {
    case_created: "建案",
    arbitrators_assigned: "派庭",
    material_submitted: "提交材料",
    vote_cast: "投票",
    case_decided: "裁决",
    case_executed: "执行",
  };

  var SEVERITY_LABEL = { info: "提示", medium: "中等", high: "高" };
  var SEVERITY_TONE = { info: "warn", medium: "warn", high: "err" };

  // 侧栏子项 -> 只显示哪一张卡（"" = 全显示）。
  var SUB_MODE = {
    overview: "arb-overview",
    alerts: "arb-alerts",
    overdue: "arb-overdue",
    arbitrators: "arb-arbitrators",
    actions: "arb-actions",
  };

  var state = { report: null, alerts: [], overdue: [], arbitrators: [] };

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

  /** 当前这个身份有没有仲裁工作面（未知 = 没有，宁可不画）。 */
  function permitted() {
    try {
      var caps = window.KarmaConsoleCaps;
      if (caps && caps.get && caps.get().can_operate_arbitration === true) return true;
    } catch (_) {}
    return false;
  }

  function T(zh) {
    var i18n = window.CYBER_I18N;
    return i18n && i18n.T ? i18n.T(zh) : zh;
  }

  /** 带变量的整句：整句查表（含 {0} 的模式），查到再填值。 */
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

  function shortId(value) {
    var s = String(value || "");
    try {
      if (s && window.KarmaDisplayId && window.KarmaDisplayId.remote) {
        return window.KarmaDisplayId.remote(s) || "\u2014";
      }
    } catch (_) {}
    return s.length > 14 ? s.slice(0, 12) + "\u2026" : s || "\u2014";
  }

  function label(map, key) {
    if (key == null || key === "") return "\u2014";
    return T(map[key] || String(key));
  }

  function when(value) {
    if (!value) return "\u2014";
    var d = new Date(value);
    if (isNaN(d.getTime())) return String(value);
    return d.toLocaleString();
  }

  // ---- 渲染 -----------------------------------------------------------------

  function statsHtml(report) {
    var tiles = [
      ["案件总数", String(report.total_cases || 0)],
      ["窗口（小时）", String(report.window_hours == null ? "\u2014" : report.window_hours)],
    ];
    var counts = report.status_counts || {};
    Object.keys(counts).forEach(function (k) {
      tiles.push([label(STATUS_LABEL, k), String(counts[k])]);
    });
    var decisions = report.decision_counts || {};
    Object.keys(decisions).forEach(function (k) {
      tiles.push([label(DECISION_LABEL, k), String(decisions[k])]);
    });
    return tiles
      .map(function (pair) {
        return (
          '<div class="arb-stat"><span class="arb-stat-k">' +
          esc(pair[0]) +
          '</span><b class="arb-stat-v">' +
          esc(pair[1]) +
          "</b></div>"
        );
      })
      .join("");
  }

  function eventsHtml(report) {
    var rows = report.recent_events || [];
    if (!rows.length) return '<li class="arb-empty">' + esc(T("窗口内还没有事件")) + "</li>";
    return rows
      .map(function (ev) {
        return (
          '<li class="arb-line"><b>' +
          esc(label(EVENT_LABEL, ev.event_type)) +
          '</b><span class="arb-dim">' +
          esc(shortId(ev.case_id)) +
          '</span><span class="arb-dim">' +
          esc(when(ev.created_at)) +
          '</span><span class="arb-note">' +
          esc(ev.detail || "") +
          "</span></li>"
        );
      })
      .join("");
  }

  function alertsHtml() {
    var rows = state.alerts || [];
    if (!rows.length) return '<li class="arb-empty">' + esc(T("没有告警")) + "</li>";
    return rows
      .map(function (a) {
        var tone = SEVERITY_TONE[a.severity] || "warn";
        return (
          '<li class="arb-line ' +
          tone +
          '"><b>' +
          esc(label(ALERT_LABEL, a.alert_type)) +
          '</b><span class="arb-pill">' +
          esc(label(SEVERITY_LABEL, a.severity)) +
          '</span><span class="arb-note">' +
          esc(a.message || "") +
          '</span><span class="arb-dim">' +
          esc(when(a.generated_at)) +
          "</span></li>"
        );
      })
      .join("");
  }

  function overdueHtml() {
    var rows = state.overdue || [];
    if (!rows.length) return '<li class="arb-empty">' + esc(T("没有超期案件")) + "</li>";
    return rows
      .map(function (o) {
        return (
          '<li class="arb-line err"><b>' +
          esc(shortId(o.case_id)) +
          '</b><span class="arb-pill">' +
          esc(label(STAGE_LABEL, o.overdue_stage)) +
          '</span><span class="arb-dim">' +
          esc(label(STATUS_LABEL, o.status)) +
          '</span><span class="arb-dim">' +
          esc(Tf("已等 {0} 小时 / 阈值 {1} 小时", Math.round(o.age_hours || 0), o.threshold_hours || 0)) +
          '</span><span class="arb-dim">' +
          esc(when(o.updated_at)) +
          "</span></li>"
        );
      })
      .join("");
  }

  function arbitratorsHtml() {
    var rows = state.arbitrators || [];
    if (!rows.length) return '<li class="arb-empty">' + esc(T("窗口内还没有仲裁员活动")) + "</li>";
    return rows
      .map(function (a) {
        return (
          '<li class="arb-line"><b>' +
          esc(shortId(a.arbitrator_identity_id)) +
          '</b><span class="arb-pill">' +
          esc(Tf("派庭 {0}", a.assigned_count || 0)) +
          '</span><span class="arb-pill">' +
          esc(Tf("投票 {0}", a.vote_count || 0)) +
          '</span><span class="arb-dim">' +
          esc(Tf("最近活动 {0}", when(a.last_activity_at))) +
          "</span></li>"
        );
      })
      .join("");
  }

  function render() {
    var report = state.report || {};
    byId("arb-stats").innerHTML = statsHtml(report);
    byId("arb-events").innerHTML = eventsHtml(report);
    byId("arb-alerts-list").innerHTML = alertsHtml();
    byId("arb-overdue-list").innerHTML = overdueHtml();
    byId("arb-arbitrators-list").innerHTML = arbitratorsHtml();
    say(byId("arb-generated"), Tf("已生成 {0}", when(report.generated_at)), null);
  }

  /** 只显示当前子项对应的那张卡（子项为空 = 全显示）。 */
  function applyMode(mode) {
    var only = SUB_MODE[mode] || "";
    ["arb-overview", "arb-alerts", "arb-overdue", "arb-arbitrators", "arb-actions"].forEach(function (id) {
      var node = byId(id);
      if (node) node.hidden = !!only && id !== only;
    });
  }

  // ---- 读取 -----------------------------------------------------------------

  async function load() {
    var st = byId("arb-state");
    var deny = byId("arb-deny");
    if (deny) deny.hidden = true;

    if (!permitted()) {
      say(st, T("这个身份不在仲裁员 / 管理员白名单里。"), false);
      if (deny) {
        deny.hidden = false;
        deny.textContent = T(
          "这个身份打不开仲裁台：仲裁台只对仲裁员或管理员开放。名单在服务器上，需要平台点名开通。"
        );
        if (window.CYBER_I18N && window.CYBER_I18N.applyPhrase) window.CYBER_I18N.applyPhrase(deny);
      }
      return;
    }
    if (!authed()) {
      say(st, T("还没认证：请先用右上角「连接钱包」完成认证。"), false);
      return;
    }

    var hours = String((byId("arb-window") || {}).value || "24");
    var qs = "?window_hours=" + encodeURIComponent(hours);
    say(st, T("读取中…"), null);
    try {
      var results = await Promise.all([
        api().karmaFetch(PATH + "/cases/ops/report" + qs, { method: "GET", headers: api().headers() }),
        api().karmaFetch(PATH + "/cases/ops/alerts" + qs, { method: "GET", headers: api().headers() }),
        api().karmaFetch(PATH + "/cases/ops/overdue" + qs, { method: "GET", headers: api().headers() }),
        api().karmaFetch(PATH + "/cases/ops/arbitrators" + qs, { method: "GET", headers: api().headers() }),
      ]);
      state.report = results[0] || {};
      state.alerts = results[1] || [];
      state.overdue = results[2] || [];
      state.arbitrators = results[3] || [];
      render();
      say(st, T("已同步"), true);
    } catch (e) {
      var status = e && e.status;
      if (status === 401) say(st, T("还没认证：请先用右上角「连接钱包」完成认证。"), false);
      else if (status === 403) say(st, T("没有权限：运维报表只对管理员开放。"), false);
      else say(st, Tf("读取失败：{0}", (e && e.message) || e), false);
      if (window.CYBER_I18N && window.CYBER_I18N.applyPhrase) window.CYBER_I18N.applyPhrase(byId("arb-state"));
    }
  }

  // ---- 派庭 / 投票 / 执行 -----------------------------------------------------

  function caseId() {
    return String((byId("arb-case") || {}).value || "").trim();
  }

  async function assignAuto() {
    var st = byId("arb-action-state");
    var id = caseId();
    if (!id) return say(st, T("先填案件编号"), false);
    var count = parseInt(String((byId("arb-count") || {}).value || "3"), 10) || 3;
    say(st, T("派庭中…"), null);
    try {
      var rows = await api().jsonPost(PATH + "/cases/" + encodeURIComponent(id) + "/assign-auto", { count: count });
      say(st, Tf("已派庭 {0} 名仲裁员", (rows && rows.length) || 0), true);
      loadAssignments().catch(function () {});
      load().catch(function () {});
    } catch (e) {
      say(st, Tf("派庭失败：{0}", (e && e.message) || e), false);
    }
  }

  async function loadAssignments() {
    var st = byId("arb-action-state");
    var id = caseId();
    var sel = byId("arb-arbitrator");
    if (!id) return say(st, T("先填案件编号"), false);
    if (!sel) return;
    try {
      var rows = await api().karmaFetch(PATH + "/cases/" + encodeURIComponent(id) + "/assignments", {
        method: "GET",
        headers: api().headers(),
      });
      var list = rows || [];
      sel.innerHTML = list
        .map(function (a) {
          return (
            '<option value="' +
            esc(a.arbitrator_identity_id) +
            '">' +
            esc(shortId(a.arbitrator_identity_id)) +
            " · " +
            esc(a.status || "") +
            "</option>"
          );
        })
        .join("");
      if (!list.length) sel.innerHTML = '<option value="">' + esc(T("本案还没有指派")) + "</option>";
      say(st, Tf("已读取指派：{0} 名", list.length), true);
    } catch (e) {
      say(st, Tf("读取指派失败：{0}", (e && e.message) || e), false);
    }
  }

  async function castVote() {
    var st = byId("arb-action-state");
    var id = caseId();
    if (!id) return say(st, T("先填案件编号"), false);
    var who = String((byId("arb-arbitrator") || {}).value || "").trim();
    if (!who) return say(st, T("先读取指派并选中仲裁员身份"), false);
    var decision = String((byId("arb-decision") || {}).value || "");
    var body = {
      arbitrator_identity_id: who,
      decision: decision,
      rationale: String((byId("arb-rationale") || {}).value || "").trim() || null,
    };
    if (decision === "partial") {
      var pct = String((byId("arb-percent") || {}).value || "").trim();
      if (!pct) return say(st, T("选「部分赔付」必须填比例"), false);
      body.partial_percent = Number(pct);
    }
    say(st, T("投票中…"), null);
    try {
      var row = await api().jsonPost(PATH + "/cases/" + encodeURIComponent(id) + "/vote", body);
      say(st, Tf("已投票，本案状态：{0}", label(STATUS_LABEL, row && row.status)), true);
      load().catch(function () {});
    } catch (e) {
      say(st, Tf("投票失败：{0}", (e && e.message) || e), false);
    }
  }

  async function executeCase() {
    var st = byId("arb-action-state");
    var id = caseId();
    if (!id) return say(st, T("先填案件编号"), false);
    if (!window.confirm(Tf("执行裁决会直接把裁决写回结算、真的动钱。确认执行 {0} ？", id))) {
      return say(st, T("已取消，没有执行"), false);
    }
    say(st, T("执行中…"), null);
    try {
      var row = await api().jsonPost(PATH + "/cases/" + encodeURIComponent(id) + "/execute", {});
      say(st, Tf("已执行，结算状态：{0}", String((row && row.status) || "")), true);
      load().catch(function () {});
    } catch (e) {
      say(st, Tf("执行失败：{0}", (e && e.message) || e), false);
    }
  }

  // ---- 绑定 -----------------------------------------------------------------

  function visible() {
    var sec = byId("arbitration");
    return !!(sec && sec.classList.contains("active"));
  }

  function bind() {
    var rf = byId("arb-refresh");
    if (rf) rf.addEventListener("click", load);
    var w = byId("arb-window");
    if (w) w.addEventListener("change", load);

    var pa = byId("arb-assign");
    if (pa) pa.addEventListener("click", assignAuto);
    var pl = byId("arb-load-assignments");
    if (pl) pl.addEventListener("click", loadAssignments);
    var pv = byId("arb-vote");
    if (pv) pv.addEventListener("click", castVote);
    var pe = byId("arb-execute");
    if (pe) pe.addEventListener("click", executeCase);

    document.addEventListener("karma-page-shown", function (ev) {
      var detail = (ev && ev.detail) || {};
      if (detail.page !== "arbitration") return;
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

  window.KarmaArbitrationConsole = { refresh: load, state: state, applyMode: applyMode };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind);
  } else {
    bind();
  }
})();