/**
 * 认证页共用件 —— 身份档案（role profile）的建立与回读。
 *
 * 三张认证页（个人 / 个体 / 企业）都要回答同一个问题：「这次认证挂在哪个身份名下」。
 * 答案统一走这里，别让三份脚本各写一套建档案的逻辑，否则迟早出现
 * 同一份资料挂到两个档案上、或者侧栏「选择身份」看不见新身份。
 *
 * 边界：这里只建档案 / 读档案，不做任何加密，也不碰私钥与助记词。
 */
(function () {
  "use strict";

  function api() {
    return window.cyberKarmaApi || {};
  }

  function identity() {
    try {
      return (
        String(window.KARMA_IDENTITY_ID || "").trim() ||
        sessionStorage.getItem("karma_console_identity") ||
        ""
      );
    } catch (_) {
      return String(window.KARMA_IDENTITY_ID || "").trim();
    }
  }

  /** 同名同类就复用；换了名字才算新身份。找不到就建一个。 */
  async function ensureProfile(klass, displayName) {
    var id = identity();
    if (!id) throw new Error("请先连接钱包");
    if (!klass) throw new Error("缺少身份种类");
    var name = String(displayName || "").trim();
    var body = await api().listRoleProfiles(id);
    var rows = (body && body.profiles) || [];
    for (var i = 0; i < rows.length; i += 1) {
      var p = rows[i];
      if (!p || p["class"] !== klass) continue;
      if (!name || String(p.display_name || "").trim() === name) return p;
    }
    var payload = { owner_identity_id: id, "class": klass };
    if (name) payload.display_name = name;
    return api().createRoleProfile(payload);
  }

  /** 列出某一类身份档案（用于回显已提交的资料与复核状态）。 */
  async function listProfiles(klass) {
    var id = identity();
    if (!id) return [];
    var body = await api().listRoleProfiles(id);
    var rows = (body && body.profiles) || [];
    if (!klass) return rows;
    return rows.filter(function (p) { return p && p["class"] === klass; });
  }

  /** 建完档案让侧栏「选择身份」立刻看到它。 */
  function refreshIdentities() {
    var sw = window.KarmaIdentitySwitcher;
    if (sw && typeof sw.refresh === "function") {
      return Promise.resolve(sw.refresh()).catch(function () {});
    }
    return Promise.resolve();
  }

  // ---- 提交前自检 ---------------------------------------------------------
  //
  // 三张认证页共用：把「机器能查的」先查一遍，别让用户提交完才发现信用代码抄错一位。
  // 只读接口，登录即可用；结论分三档，跟复核台同一套口径。

  var CHECK_LABEL = {
    pass: "已自动通过",
    fail: "自动不通过",
    manual: "机器判不了，需人工",
    unavailable: "查不动 / 未接入数据源",
  };
  var CHECK_TONE = { pass: "ok", fail: "err", manual: "warn", unavailable: "warn" };

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

  function precheck(kind, subject, websiteVerified) {
    return api().jsonPost("/v1/reviews/precheck", {
      kind: kind,
      subject: subject || {},
      website_verified: !!websiteVerified,
    });
  }

  function renderPrecheck(host, result) {
    if (!host) return;
    var checks = (result && result.checks) || [];
    if (!checks.length) {
      host.innerHTML = '<li class="idv-hint">没有可自检的项。</li>';
      return;
    }
    host.innerHTML = checks
      .map(function (c) {
        var tone = CHECK_TONE[c.status] || "warn";
        var blocking = c.blocking && c.status === "fail";
        return (
          '<li class="rv-check ' + tone + '"><span class="rv-dot"></span>' +
          "<b>" + esc(c.label || c.key) + "</b>" +
          '<span class="rv-state">' + esc(CHECK_LABEL[c.status] || c.status) + "</span>" +
          (blocking ? '<span class="rv-pill err">阻断：先改再提交</span>' : "") +
          (c.note ? '<div class="rv-note">' + esc(c.note) + "</div>" : "") +
          "</li>"
        );
      })
      .join("");
  }

  /** 一个按钮的完整动作：跑自检 → 摊开每项结论 → 写一句人话总结。 */
  async function runPrecheck(kind, subject, websiteVerified, host, status) {
    say(status, "自检中…", null);
    try {
      var res = await precheck(kind, subject, websiteVerified);
      renderPrecheck(host, res);
      var bad = (res.blocking_failures || []).length;
      var human = (res.needs_human || []).length;
      if (bad) {
        say(status, "有 " + bad + " 项要先改，改完再提交", false);
      } else if (human) {
        say(status, "机器能查的都过了，" + human + " 项要人工看（提交后进复核队列）", true);
      } else {
        say(status, "自检通过，可以提交", true);
      }
      return res;
    } catch (e) {
      say(status, (e && e.message) || "自检失败", false);
      return null;
    }
  }

  window.KarmaCert = {
    identity: identity,
    ensureProfile: ensureProfile,
    listProfiles: listProfiles,
    refreshIdentities: refreshIdentities,
    precheck: precheck,
    renderPrecheck: renderPrecheck,
    runPrecheck: runPrecheck,
  };
})();
