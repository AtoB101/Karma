/**
 * 操作台 · 复核台（运营侧入口）。
 *
 * 这个页面只对**持 verifier（复核岗）类身份档案**的人有用。它把四类待办拉到一处：
 *   主身份认证（identity_verification）/ 主体认证（entity_verification）/
 *   开发者实名（developer）/ 子身份 KYC（role_profile_kyc）
 * 每条待办都把**机器已经算过的结论**摊开给人看，人只看机器判不了的那部分。
 *
 * 三条不能破的线（后端各有一道，这里是前端的体面版本）：
 *  1. 自己提交的东西不会出现在自己的队列里 —— 后端已按 actor 过滤，`skipped_own` 会报条数；
 *  2. 机器判不了（manual / unavailable）**只标注、不代替人下结论**；
 *  3. 机器已经判为阻断性不通过（如信用代码抄错一位）的，放行前必须再确认一次 ——
 *     自动核验不是橡皮图章，也不是摆设。
 */
(function () {
  "use strict";

  var PATH = "/v1/reviews";

  var KIND_LABEL = {
    identity_verification: "主身份认证",
    entity_verification: "主体认证",
    developer: "开发者实名",
    role_profile_kyc: "子身份 KYC",
  };

  // 侧栏子项 -> 队列里的分类（"" = 全部）。
  var SUB_KIND = {
    all: "",
    identity: "identity_verification",
    entity: "entity_verification",
    developer: "developer",
    kyc: "role_profile_kyc",
  };

  var CHECK_TONE = { pass: "ok", fail: "err", manual: "warn", unavailable: "warn" };
  var CHECK_LABEL = {
    pass: "已自动通过",
    fail: "自动不通过",
    manual: "机器判不了，需人工",
    unavailable: "查不动 / 未接入数据源",
  };

  var state = { items: [], counts: {}, kind: "", verifier: "" };

  function byId(id) {
    return document.getElementById(id);
  }

  function api() {
    return window.cyberKarmaApi || {};
  }

  /**
   * 连没连钱包。会话没建起来之前不许发请求 —— 发出去只会得到一条裸 401，
   * 页面上就挂一句「HTTP 401: Authentication required」：既不是译文，也没告诉人下一步做什么。
   * 隔壁「接入确认」「已绑定钥匙」两张卡片用的就是这个判据，这里跟它们对齐。
   */
  function authed() {
    try {
      return !!(window.KARMA_ACCESS_TOKEN || window.KARMA_IDENTITY_ID);
    } catch (_) {
      return false;
    }
  }

  /** 译文（没接 i18n 或没这条译文时原样返回中文）。 */
  function T(zh) {
    var i18n = window.CYBER_I18N;
    return i18n && i18n.T ? i18n.T(zh) : zh;
  }

  /**
   * 后端拼出来的副标题（「证件类型 · 号码 · 级别」）逐段翻。
   * 整句查表查不到 —— 只有按分隔符拆开，每一段才在译表里。
   */
  function trJoined(text) {
    return String(text == null ? "" : text)
      .split(" · ")
      .map(function (part) {
        return T(part.trim());
      })
      .join(" · ");
  }

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function say(node, text, ok) {
    if (!node) return;
    node.textContent = text == null ? "—" : String(text);
    node.classList.remove("ok", "err");
    if (ok === true) node.classList.add("ok");
    if (ok === false) node.classList.add("err");
  }

  /** 身份编号：全站统一走 KarmaDisplayId.remote（kid…+ 后 4 位）。 */
  function shortId(value) {
    var s = String(value || "");
    try {
      if (s && global.KarmaDisplayId && global.KarmaDisplayId.remote) {
        return global.KarmaDisplayId.remote(s) || "—";
      }
    } catch (_) {}
    return s.length > 14 ? s.slice(0, 12) + "…" : s || "—";
  }

  function attr(value) {
    return esc(value);
  }

  // ---- 渲染 -----------------------------------------------------------------

  function checkRow(check) {
    var tone = CHECK_TONE[check.status] || "warn";
    var blocking = check.blocking && check.status === "fail";
    var bits = [
      '<span class="rv-dot"></span>',
      "<b>" + esc(check.label || check.key) + "</b>",
      '<span class="rv-state">' + esc(CHECK_LABEL[check.status] || check.status) + "</span>",
    ];
    if (blocking) bits.push('<span class="rv-pill err">阻断：先改再提交</span>');
    var note = check.note ? '<div class="rv-note">' + esc(check.note) + "</div>" : "";
    return '<li class="rv-check ' + tone + '">' + bits.join("") + note + "</li>";
  }

  function materialsText(item) {
    var list = item.materials || [];
    if (list.length) {
      return list
        .map(function (m) {
          return T(String((m && (m.name || m.kind)) || ""));
        })
        .filter(Boolean)
        .join(T("、"));
    }
    return item.has_package
      ? T("无材料清单（密文包已随附，复核岗看密文）")
      : T("无材料清单（密文包未随附）");
  }

  function itemHtml(item) {
    var ac = item.auto_checks || {};
    var checks = ac.checks || [];
    var blocking = ac.blocking_failures || [];
    var humans = ac.needs_human || [];
    var id = String(item.item_id || "");
    var pills = [
      ac.ok
        ? '<span class="rv-pill ok">机器已确认</span>'
        : '<span class="rv-pill err">机器判不通过</span>',
    ];
    if (humans.length) pills.push('<span class="rv-pill warn">' + humans.length + " 项待人工</span>");

    return (
      '<li class="rv-item" data-rv-item="' + attr(id) + '">' +
        '<div class="rv-head">' +
          "<b>" + esc(item.title || id) + "</b>" +
          '<span class="rv-kind">' + esc(KIND_LABEL[item.kind] || item.kind) + "</span>" +
          pills.join("") +
        "</div>" +
        '<div class="rv-sub">' + esc(trJoined(item.subtitle) || "—") + "</div>" +
        '<div class="rv-meta">' +
          "<span>编号 <code>" + esc(id) + "</code></span>" +
          "<span>提交 " + esc(item.submitted_at || "—") + "</span>" +
          "<span>材料：" + esc(materialsText(item)) + "</span>" +
        "</div>" +
        '<ul class="rv-checks">' + checks.map(checkRow).join("") + "</ul>" +
        '<div class="rv-actions">' +
          '<input class="rv-reason" type="text" data-rv-reason="' + attr(id) + '" ' +
            'placeholder="复核意见（驳回必填，提交人看得到）" />' +
          '<button type="button" class="btn primary" data-rv-decide="verified" data-rv-target="' + attr(id) + '">通过</button>' +
          '<button type="button" class="btn" data-rv-decide="rejected" data-rv-target="' + attr(id) + '">驳回</button>' +
          '<span class="api-status" data-rv-status="' + attr(id) + '">—</span>' +
        "</div>" +
      "</li>"
    );
  }

  function render() {
    var host = byId("rv-list");
    var counts = byId("rv-counts");
    if (!host) return;
    var c = state.counts || {};
    if (counts) {
      counts.textContent =
        "待办 " + state.items.length + " 条（主身份 " + (c.identity_verification || 0) +
        " · 主体 " + (c.entity_verification || 0) +
        " · 开发者 " + (c.developer || 0) +
        " · 子身份 KYC " + (c.role_profile_kyc || 0) + "）" +
        (c.skipped_own ? " · 已自动跳过本人提交 " + c.skipped_own + " 条" : "");
    }
    var items = state.items.filter(function (i) {
      return !state.kind || i.kind === state.kind;
    });
    if (!items.length) {
      host.innerHTML =
        '<li class="idv-hint">' +
        (state.kind ? "这个分类下暂时没有待办。" : "现在没有待复核的待办。") +
        "</li>";
      return;
    }
    host.innerHTML = items.map(itemHtml).join("");
  }

  // ---- 取数 -----------------------------------------------------------------

  async function load() {
    var st = byId("rv-state");
    var deny = byId("rv-deny");
    if (deny) {
      deny.hidden = true;
      deny.innerHTML = "";
    }
    if (!authed()) {
      state.items = [];
      state.counts = {};
      state.verifier = "";
      render();
      say(st, T("请先用右上角「连接钱包」完成认证，再来打开复核队列。"), null);
      return;
    }
    say(st, "读取中…", null);
    try {
      // karmaFetch 只负责 fetch，不会替你加认证头 —— 少了 headers() 就是线上 401。
      var res = await api().karmaFetch(PATH + "/pending", {
        method: "GET",
        headers: api().headers(),
      });
      state.items = (res && res.items) || [];
      state.counts = (res && res.counts) || {};
      state.verifier = (res && res.verifier_identity_id) || "";
      render();
      say(st, "已刷新 · 复核岗 " + shortId(state.verifier), true);
    } catch (e) {
      state.items = [];
      state.counts = {};
      render();
      // 服务端的 401/403 是英文原文（HTTP 403: only a verifier-class profile …），
      // 直接摊给用户等于没翻。按状态给一句能落到实处的话，剩下的交给译表。
      var status = e && e.status;
      if (status === 401) say(st, T("还没认证：请先用右上角「连接钱包」完成认证。"), false);
      else if (status === 403) say(st, T("没有权限：这个身份还不是复核岗（verifier）。"), false);
      else say(st, (e && e.message) || "读取失败", false);
      if (deny && e && e.status === 403) {
        deny.hidden = false;
        // 这句话必须跟后端的规矩一致（services/governance_stake.py）：
        // 复核岗现在有两条路 —— 平台点名，或者平台开放申请后用**已锁仓的 USDC**质押开通；
        // 质押开出来的岗跟着押金走，押金一走岗就停。再念「只能靠运维加名单」，
        // 就等于告诉用户「你永远开不了」——后端已经能自助开通了。
        deny.textContent =
          "这个身份还打不开复核队列：队列只对复核岗（verifier）开放。" +
          "复核岗有两条路：平台点名开通，或者平台开放申请后用已锁仓的 USDC 质押开通" +
          " —— 押金一走，这个岗就自动停。";
        // 翻译是排队跑的（观察器 + 队列）：不等它这一轮，切完语言会先看见中文。
        if (window.CYBER_I18N && window.CYBER_I18N.applyPhrase) window.CYBER_I18N.applyPhrase(deny);
      }
    }
  }

  // ---- 裁决 -----------------------------------------------------------------

  async function decide(itemId, decision) {
    var item = state.items.filter(function (i) {
      return String(i.item_id) === String(itemId);
    })[0];
    if (!item) return;
    var st = document.querySelector('[data-rv-status="' + itemId + '"]');
    var reasonNode = document.querySelector('[data-rv-reason="' + itemId + '"]');
    var reason = String((reasonNode && reasonNode.value) || "").trim();
    var ac = item.auto_checks || {};
    var blocking = ac.blocking_failures || [];

    if (decision === "rejected" && !reason) {
      return say(st, "驳回要写理由：提交人会看到这段话", false);
    }
    if (decision === "verified" && blocking.length) {
      var ok = window.confirm(
        "机器已经判定这几项不通过：\n" +
          blocking.join("、") +
          "\n\n放行前请确认你已人工核对过。仍然放行吗？"
      );
      if (!ok) return say(st, "已取消，没有放行", false);
    }

    var decide = item.decide || {};
    if (!decide.approve_path) return say(st, "这条待办没有给出裁决接口", false);
    var body = {};
    body[decide.body_key || "decision"] = decision;
    body.reason = reason || null;

    say(st, "提交中…", null);
    try {
      await api().jsonPost(decide.approve_path, body);
      say(st, decision === "verified" ? "已通过" : "已驳回", true);
      state.items = state.items.filter(function (i) {
        return String(i.item_id) !== String(itemId);
      });
      render();
      load();
    } catch (e) {
      say(st, (e && e.message) || "裁决失败", false);
    }
  }

  // ---- 绑定 -----------------------------------------------------------------

  function setKind(value) {
    state.kind = value || "";
    var sel = byId("rv-kind");
    if (sel && sel.value !== state.kind) sel.value = state.kind;
    render();
  }

  function visible() {
    var sec = byId("reviews");
    return !!(sec && sec.classList.contains("active"));
  }

  function bind() {
    var rf = byId("rv-refresh");
    if (rf) rf.addEventListener("click", load);

    var sel = byId("rv-kind");
    if (sel) sel.addEventListener("change", function () { setKind(sel.value); });

    var list = byId("rv-list");
    if (list) {
      list.addEventListener("click", function (ev) {
        var btn = ev.target && ev.target.closest ? ev.target.closest("[data-rv-decide]") : null;
        if (!btn) return;
        decide(btn.getAttribute("data-rv-target"), btn.getAttribute("data-rv-decide"));
      });
    }

    document.addEventListener("karma-page-shown", function (ev) {
      var detail = (ev && ev.detail) || {};
      if (detail.page !== "reviews") return;
      setKind(SUB_KIND[detail.sub] != null ? SUB_KIND[detail.sub] : "");
      load();
    });
    document.addEventListener("karma-wallet-connected", function () {
      if (visible()) load();
    });
    document.addEventListener("karma-session-restored", function () {
      if (visible()) load();
    });

    render();
    if (visible()) load();
  }

  window.KarmaReviewsConsole = { refresh: load, state: state, setKind: setKind };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind);
  } else {
    bind();
  }
})();
