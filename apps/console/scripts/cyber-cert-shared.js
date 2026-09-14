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

  window.KarmaCert = {
    identity: identity,
    ensureProfile: ensureProfile,
    listProfiles: listProfiles,
    refreshIdentities: refreshIdentities,
  };
})();
