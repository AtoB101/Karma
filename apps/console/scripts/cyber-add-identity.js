/**
 * 操作台 · 追加身份（第二张卡）
 * ==============================
 *
 * 主身份刷脸激活之后，再加一张身份卡只要两步：
 *
 *   ① **按标准填**：选身份类型（个人 / 商户 / 企业）+ 名字 + 联系方式 —— 这是这张卡
 *      对外要亮出来的东西；
 *   ② **再刷一次脸**：本机把这一次的脸与**首次激活留下的模板**比一个分数，
 *      分数过线 + 签名对得上 + 参考模板一致 + 不是重放 → 服务端当场把这张卡置为已核验。
 *
 * 为什么不排队等人工：加身份要防的是「别人拿你的身份卡去开新卡」，而这件事的判据是
 * **脸是不是同一个人**，不是材料写得漂不漂亮。所以判据放在刷脸上，通过了就即时开通；
 * 材料（名字 / 联系方式）只作为这张卡的展示信息一并记档。
 *
 * 治理岗（复核 / 仲裁）不在这条路上：那两个岗要质押，见 services/governance_stake.py。
 */
(function (global) {
  "use strict";

  var CLASSES = [
    { key: "individual", label: "个人 · 生活助理" },
    { key: "merchant", label: "商户 · 个体经营" },
    { key: "enterprise", label: "企业 · 商业主体" },
  ];

  var state = { busy: false, profiles: [], created: null, note: "", err: "", score: null };

  function api() { return global.cyberKarmaApi; }
  function byId(id) { return document.getElementById(id); }
  function identity() { return String(global.KARMA_IDENTITY_ID || "").trim(); }
  function T(zh) {
    var t = global.CYBER_I18N;
    return t && t.T ? t.T(zh) : zh;
  }
  function Tf(zh) {
    var t = global.CYBER_I18N;
    var args = [zh];
    for (var i = 1; i < arguments.length; i += 1) args.push(arguments[i]);
    if (t && t.Tf) return t.Tf.apply(t, args);
    var out = T(zh);
    for (var k = 1; k < arguments.length; k += 1) {
      out = out.split("{" + (k - 1) + "}").join(arguments[k] == null ? "" : String(arguments[k]));
    }
    return out;
  }
  function esc(v) {
    return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function labelOf(key) {
    for (var i = 0; i < CLASSES.length; i += 1) {
      if (CLASSES[i].key === key) return T(CLASSES[i].label);
    }
    return key;
  }
  function classValue() {
    var sel = byId("aid-class");
    return sel ? String(sel.value || "individual") : "individual";
  }

  function render() {
    var host = byId("idv-add-identity");
    if (!host) return;
    var st = state.created;
    var options = CLASSES.map(function (c) {
      return (
        '<option value="' + esc(c.key) + '"' +
        (c.key === classValue() ? " selected" : "") +
        ">" + esc(T(c.label)) + "</option>"
      );
    }).join("");

    var body =
      '<div class="section-header"><div><h3>' + esc(T("追加身份 · 再刷一次脸就开通")) + "</h3><p>" +
      esc(
        T(
          "填好这张卡对外要亮的信息，再刷一次脸：系统拿这一次的脸和你首次激活时留下的模板比一次，是同一个人就当场开通 —— 不排队、不等人工。"
        )
      ) +
      "</p></div></div>" +
      '<div class="aid-grid">' +
      '<div class="field"><label>' + esc(T("身份类型")) + "</label><select id=\"aid-class\">" + options + "</select></div>" +
      '<div class="field"><label>' + esc(T("这张卡的名字")) + '</label><input id="aid-name" type="text" placeholder="' + esc(T("例如：采购助理 / 门店收款")) + '" /></div>' +
      '<div class="field"><label>' + esc(T("联系方式（邮箱或手机，可不填）")) + '</label><input id="aid-contact" type="text" placeholder="' + esc(T("给谁看就填谁")) + '" /></div>' +
      "</div>" +
      '<div class="aid-actions">' +
      '<button type="button" class="btn" id="aid-create">' + esc(T("① 先建这张卡")) + "</button>" +
      '<button type="button" class="btn primary" id="aid-face">' + esc(T("② 再刷脸一次 · 自动核对同一个人")) + "</button>" +
      "</div>";

    if (st) {
      body +=
        '<p class="aid-note">' +
        esc(
          Tf(
            "待核对的卡：{0} · {1} · kyc_status={2}",
            labelOf(st["class"] || st.class_),
            st.display_name || st.profile_id,
            st.kyc_status || "none"
          )
        ) +
        "</p>";
    }
    if (state.score != null) {
      body +=
        '<p class="aid-note aid-ok">' +
        esc(Tf("同一个人：相似度 {0}（阈值 {1}）。这张卡已经开通。", Number(state.score).toFixed(4), state.threshold != null ? Number(state.threshold).toFixed(4) : "—")) +
        "</p>";
    }
    if (state.note) body += '<p class="aid-note aid-ok">' + esc(state.note) + "</p>";
    if (state.err) body += '<p class="aid-note aid-bad">' + esc(state.err) + "</p>";
    body +=
      '<p class="aid-hint">' +
      esc(
        T(
          "还没激活主身份？先在上面第 ② 步刷一次脸 —— 有了模板，这里才能跟你自己比对。"
        )
      ) +
      "</p>";

    host.innerHTML = body;
    wire();
  }

  function wire() {
    var create = byId("aid-create");
    if (create) create.addEventListener("click", doCreate);
    var face = byId("aid-face");
    if (face) face.addEventListener("click", doFace);
  }

  async function doCreate() {
    if (state.busy) return;
    var id = identity();
    state.err = "";
    state.note = "";
    if (!id) { state.err = T("请先连接钱包。"); render(); return; }
    var nameInput = byId("aid-name");
    var name = String((nameInput && nameInput.value) || "").trim();
    var contact = String((byId("aid-contact") || {}).value || "").trim();
    var body = { owner_identity_id: id, "class": classValue() };
    if (name) body.display_name = name;
    if (contact) body.kyc_payload = { contact: contact };
    state.busy = true;
    state.note = T("正在建卡…");
    render();
    try {
      var p = await api().createRoleProfile(body);
      state.created = p;
      state.note = T("这张卡建好了：下一步刷一次脸核对是同一个人。");
      state.err = "";
    } catch (e) {
      state.err = String((e && e.message) || e);
      state.note = "";
    } finally {
      state.busy = false;
      render();
    }
  }

  async function doFace() {
    if (state.busy) return;
    var id = identity();
    if (!id) { state.err = T("请先连接钱包。"); render(); return; }
    var vault = global.KarmaFaceVault;
    if (!vault || !vault.confirmSamePerson) { state.err = T("刷脸模块未加载，请刷新页面后再试。"); render(); return; }
    var pid = state.created && state.created.profile_id;
    if (!pid) { state.err = T("先点「① 先建这张卡」，再刷脸核对。"); render(); return; }
    state.busy = true;
    state.err = "";
    state.note = T("正在比对这一次的脸和首次激活留下的模板…");
    render();
    try {
      var res = await vault.confirmSamePerson(pid, classValue());
      if (!res) {
        state.note = T("已取消。");
      } else {
        state.score = res.score;
        state.threshold = (res.verdict && res.verdict.threshold) != null ? res.verdict.threshold : null;
        state.created = Object.assign({}, state.created, { kyc_status: "verified" });
        state.note = T("已开通。");
        try { document.dispatchEvent(new CustomEvent("karma-capacity-changed")); } catch (_) {}
      }
    } catch (e) {
      state.score = null;
      state.err = String((e && e.message) || e);
      state.note = "";
    } finally {
      state.busy = false;
      render();
    }
  }

  function init() {
    if (!byId("idv-add-identity")) return;
    render();
    ["karma-wallet-connected", "karma-session-restored", "karma-identity-changed"].forEach(function (evt) {
      document.addEventListener(evt, function () { render(); });
    });
  }

  global.KarmaAddIdentity = {
    init: init,
    render: render,
    doCreate: doCreate,
    doFace: doFace,
    classes: CLASSES,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window);
