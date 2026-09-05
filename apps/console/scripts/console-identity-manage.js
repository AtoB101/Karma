/**
 * Karma Console — identity role profile management (P3 write entry).
 *
 * Injects a compact panel on the Overview page for:
 *   - creating a role profile (class + display name),
 *   - granting an authorized disclosure on the active profile,
 *   - submitting KYC for the active profile.
 *
 * Uses cyberKarmaApi (list/createRoleProfile, grantDisclosure, submitKyc) and
 * re-refreshes the identity switcher after creation.
 */
(function (global) {
  function api() {
    return global.cyberKarmaApi;
  }

  function el(sel, root) {
    return (root || document).querySelector(sel);
  }

  function status(msg, ok) {
    var n = el("[data-im-status]");
    if (!n) return;
    n.textContent = msg;
    n.style.color = ok ? "var(--ok, #4ade80)" : "#f87171";
  }

  function activeProfileId() {
    var s = global.KarmaIdentitySwitcher;
    return s && s.getActiveProfileId ? s.getActiveProfileId() : "";
  }

  function panel() {
    var existing = document.querySelector("[data-identity-manage]");
    if (existing) return existing;
    var main = document.querySelector("main");
    if (!main) return null;

    var sec = document.createElement("section");
    sec.className = "panel";
    sec.setAttribute("data-identity-manage", "");
    sec.innerHTML =
      '<h2 style="font-size:1rem;margin-bottom:0.5rem">🪪 身份档案管理</h2>' +
      '<div class="grid cols-2">' +
      '<label>class<br><select data-im-class style="width:100%;margin-top:0.25rem">' +
      '<option value="individual">individual</option>' +
      '<option value="merchant">merchant</option>' +
      '<option value="enterprise">enterprise</option>' +
      '<option value="verifier">verifier</option>' +
      '<option value="arbitrator">arbitrator</option>' +
      '</select></label>' +
      '<label>display name<br><input data-im-name type="text" placeholder="我的档案" style="width:100%;margin-top:0.25rem"></label>' +
      '<label>授权方 identity<br><input data-im-party type="text" placeholder="party-x" style="width:100%;margin-top:0.25rem"></label>' +
      '<label>scope<br><select data-im-scope style="width:100%;margin-top:0.25rem">' +
      '<option value="transaction">transaction（逐笔）</option>' +
      '<option value="ledger">ledger（整本）</option>' +
      '</select></label>' +
      '<label>task_id（transaction 必填）<br><input data-im-task type="text" style="width:100%;margin-top:0.25rem"></label>' +
      '</div>' +
      '<p style="margin-top:0.6rem;display:flex;gap:0.5rem;flex-wrap:wrap;align-items:center">' +
      '<button type="button" class="btn" data-im-create>创建档案</button>' +
      '<button type="button" class="btn" data-im-grant>授权披露</button>' +
      '<button type="button" class="btn" data-im-kyc>提交 KYC</button>' +
      '<span class="sub" data-im-status></span>' +
      '</p>';

    main.appendChild(sec);
    bind(sec);
    return sec;
  }

  function bind(sec) {
    el("[data-im-create]", sec).addEventListener("click", function () {
      createProfile(sec).catch(function () {});
    });
    el("[data-im-grant]", sec).addEventListener("click", function () {
      grant(sec).catch(function () {});
    });
    el("[data-im-kyc]", sec).addEventListener("click", function () {
      submitKyc(sec).catch(function () {});
    });
  }

  async function createProfile(sec) {
    var a = api();
    if (!a || !a.createRoleProfile) {
      status("缺少 API 客户端", false);
      return;
    }
    var cls = el("[data-im-class]", sec).value;
    var name = el("[data-im-name]", sec).value.trim();
    var body = { owner_identity_id: String(global.KARMA_IDENTITY_ID || "").trim(), class: cls };
    if (name) body.display_name = name;
    status("创建中…", null);
    try {
      var p = await a.createRoleProfile(body);
      status("已创建 " + (p.profile_id || "").slice(0, 8) + "（" + cls + "）", true);
      if (global.KarmaIdentitySwitcher && global.KarmaIdentitySwitcher.refresh) {
        global.KarmaIdentitySwitcher.refresh();
      }
    } catch (e) {
      status("失败: " + (e.message || e), false);
    }
  }

  async function grant(sec) {
    var pid = activeProfileId();
    if (!pid) {
      status("请先在顶部选择档案", false);
      return;
    }
    var party = el("[data-im-party]", sec).value.trim();
    var scope = el("[data-im-scope]", sec).value;
    var task = el("[data-im-task]", sec).value.trim();
    var a = api();
    if (!party) {
      status("请填授权方 identity", false);
      return;
    }
    status("授权中…", null);
    try {
      var body = { authorized_identity_id: party, scope: scope };
      if (scope === "transaction") body.task_id = task || undefined;
      await a.grantDisclosure(pid, body);
      status("已授权 " + party + "（" + scope + "）", true);
    } catch (e) {
      status("失败: " + (e.message || e), false);
    }
  }

  async function submitKyc(sec) {
    var pid = activeProfileId();
    if (!pid) {
      status("请先在顶部选择档案", false);
      return;
    }
    var a = api();
    status("提交 KYC…", null);
    try {
      await a.submitKyc(pid, { source: "console", note: "console submit" });
      status("已提交（pending）", true);
    } catch (e) {
      status("失败: " + (e.message || e), false);
    }
  }

  global.KarmaIdentityManage = { panel: panel };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", panel);
  } else {
    panel();
  }
})(window);
