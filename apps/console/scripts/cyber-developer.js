/**
 * 操作台 · 技能开发者实名（谁在卖）。
 *
 * 主体认证回答「这家公司是谁」，这里回答「操作这个身份的是哪个人」：
 *   ① 填真实姓名 / 职务 → ② 服务端给出待签开发者协议原文 → 钱包签名提交 → 复核
 *   → 之后**用同一个钱包**才能上架技能（上架签名必须等于签协议的钱包）。
 *
 * 两条红线与主体认证一致：
 *  1. 材料原件的明文永远不出这台设备：本地 AES-GCM-256（密钥由钱包签名派生），
 *     只上传密文包 + sha256 摘要；材料本来就是选传的。
 *  2. 协议原文不由前端拼：先问服务端要 message，原样显示给用户看，再让钱包签它。
 */
(function () {
  "use strict";

  var PBKDF2_ITERATIONS = 250000;
  var MAX_PACKAGE_BYTES = 6 * 1024 * 1024;
  var PATH = "/v1/developers";

  var dev = { materials: [], prepared: null, rows: [] };

  function byId(id) {
    return document.getElementById(id);
  }

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

  function session() {
    try {
      return JSON.parse(sessionStorage.getItem("karma_console_session") || "{}") || {};
    } catch (_) {
      return {};
    }
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

  function bufToB64(buf) {
    var bytes = new Uint8Array(buf);
    var out = "";
    for (var i = 0; i < bytes.length; i += 1) out += String.fromCharCode(bytes[i]);
    return window.btoa(out);
  }

  function randomHex(len) {
    var bytes = new Uint8Array(len);
    window.crypto.getRandomValues(bytes);
    var out = "";
    for (var i = 0; i < bytes.length; i += 1) out += ("0" + bytes[i].toString(16)).slice(-2);
    return out;
  }

  function sha256Hex(input) {
    var buf = typeof input === "string" ? new window.TextEncoder().encode(input) : input;
    return window.crypto.subtle.digest("SHA-256", buf).then(function (d) {
      var bytes = new Uint8Array(d);
      var out = "";
      for (var i = 0; i < bytes.length; i += 1) out += ("0" + bytes[i].toString(16)).slice(-2);
      return out;
    });
  }

  function walletProvider() {
    var auth = window.KarmaWalletAuth;
    if (auth && typeof auth.activeProvider === "function") {
      var p = auth.activeProvider();
      if (p && typeof p.request === "function") return p;
    }
    if (window.ethereum && typeof window.ethereum.request === "function") return window.ethereum;
    return null;
  }

  async function signMessage(message) {
    var provider = walletProvider();
    var addr = session().wallet;
    if (!provider || !addr) throw new Error("请先连接钱包（顶部「连接钱包」）");
    return provider.request({ method: "personal_sign", params: [message, addr] });
  }

  async function deriveKey(signatureHex, saltHex) {
    var enc = new window.TextEncoder();
    var material = await window.crypto.subtle.importKey(
      "raw", enc.encode(signatureHex), { name: "PBKDF2" }, false, ["deriveKey"]
    );
    return window.crypto.subtle.deriveKey(
      { name: "PBKDF2", salt: enc.encode(saltHex), iterations: PBKDF2_ITERATIONS, hash: "SHA-256" },
      material,
      { name: "AES-GCM", length: 256 },
      false,
      ["encrypt"]
    );
  }

  function readFileB64(file) {
    return new Promise(function (resolve, reject) {
      var reader = new FileReader();
      reader.onerror = function () { reject(new Error("读取文件失败：" + file.name)); };
      reader.onload = function () {
        var bytes = new Uint8Array(reader.result);
        var out = "";
        for (var i = 0; i < bytes.length; i += 1) out += String.fromCharCode(bytes[i]);
        resolve(window.btoa(out));
      };
      reader.readAsArrayBuffer(file);
    });
  }

  // ---- 表单 -----------------------------------------------------------------

  function form() {
    var role = byId("dev-role");
    return {
      real_name: String((byId("dev-real-name") || {}).value || "").trim(),
      role_title: String((byId("dev-role-title") || {}).value || "").trim(),
      contact_email: String((byId("dev-email") || {}).value || "").trim(),
      role: (role && role.value) || "developer",
    };
  }

  function sameForm(a, b) {
    if (!a || !b) return false;
    return (
      a.real_name === b.real_name &&
      a.role_title === b.role_title &&
      a.contact_email === b.contact_email &&
      a.role === b.role
    );
  }

  var STATUS_LABEL = {
    none: "未实名",
    pending: "复核中",
    verified: "已通过",
    rejected: "已驳回",
  };

  function renderList(rows) {
    var host = byId("dev-list");
    var badge = byId("dev-badge");
    var list = rows || [];
    var verified = list.filter(function (r) { return r && r.status === "verified"; })[0];
    var head = verified || list[0];
    if (badge) {
      badge.textContent = head ? (STATUS_LABEL[head.status] || head.status) : "未实名";
      badge.classList.toggle("ok", !!verified);
    }
    var hint = byId("dev-entity-hint");
    if (hint && head && head.legal_name) {
      hint.textContent = "归属主体取自你已通过的主体认证：" + head.legal_name;
    }
    if (!host) return;
    if (!list.length) {
      host.innerHTML =
        '<li class="idv-hint">这个身份下还没有开发者实名档案。填好①的姓名与职务，' +
        "点「生成待签协议」→「钱包签名并提交」。</li>";
      return;
    }
    host.innerHTML = list
      .map(function (r) {
        var bits = [
          '<b>' + esc(r.real_name || "—") + "</b>",
          esc(r.role_title || "—"),
          esc(STATUS_LABEL[r.status] || r.status || "—"),
          esc((r.developer_role || "developer")),
          r.signer_wallet ? "钱包 " + esc(String(r.signer_wallet).slice(0, 10)) + "…" : "",
        ].filter(Boolean);
        var note = r.review_note
          ? '<div class="idv-hint">复核意见：' + esc(r.review_note) + "</div>"
          : "";
        return "<li>" + bits.join(" · ") + note + "</li>";
      })
      .join("");
  }

  function renderDetail(view) {
    var out = byId("dev-out");
    if (out) out.textContent = JSON.stringify(view || {}, null, 2);
  }

  async function loadMine() {
    var status = byId("dev-status");
    var id = identity();
    if (!id) {
      renderList([]);
      return say(status, "先连接钱包", false);
    }
    try {
      var res = await api().karmaFetch(PATH + "/me", { method: "GET" });
      dev.rows = (res && res.developers) || [];
      renderList(dev.rows);
      renderDetail(res);
      var agree = byId("dev-message");
      if (agree && (agree.textContent === "—" || !agree.textContent.trim()) && res && res.agreement_text) {
        say(byId("dev-step-sign"), "待生成待签声明", null);
      }
    } catch (e) {
      renderList([]);
      say(status, (e && e.message) || "读取失败", false);
    }
  }

  // ---- ① 生成待签协议 -------------------------------------------------------

  async function prepare() {
    var status = byId("dev-status");
    var id = identity();
    if (!id) return say(status, "先连接钱包", false);
    var body = form();
    if (!body.real_name || !body.role_title || !body.contact_email) {
      return say(status, "真实姓名 / 职务 / 联系邮箱都要填", false);
    }
    say(status, "① 正在生成待签声明…", null);
    try {
      var res = await api().jsonPost(PATH + "/prepare", body);
      dev.prepared = res;
      var box = byId("dev-message");
      if (box) {
        box.textContent =
          "【开发者协议 " + (res.agreement_version || "") + "】\n" +
          (res.agreement_text || "") +
          "\n\n【你的钱包要签的原文】\n" +
          (res.message || "");
      }
      var hint = byId("dev-entity-hint");
      if (hint) {
        hint.textContent =
          "归属主体取自你已通过的主体认证：" +
          (res.legal_name || "—") +
          (res.official_domain ? "（" + res.official_domain + "）" : "");
      }
      say(byId("dev-step-info"), "已填", true);
      say(byId("dev-step-sign"), "待钱包签名", null);
      say(status, "① 已生成。核对上面的原文，再点②让钱包签名。", true);
    } catch (e) {
      dev.prepared = null;
      say(status, (e && e.message) || "生成失败", false);
    }
  }

  // ---- ③ 材料（选传） -------------------------------------------------------

  function renderMaterials() {
    var host = byId("dev-mat-list");
    var count = byId("dev-mat-count");
    if (count) count.textContent = dev.materials.length + " 份";
    say(byId("dev-step-mats"), dev.materials.length ? "已加入 " + dev.materials.length + " 份" : "可以跳过", null);
    if (!host) return;
    host.innerHTML = dev.materials
      .map(function (m, i) {
        return (
          "<li>" + esc(m.name) + "（" + esc(m.kind) + "）" +
          ' <button type="button" class="btn" data-dev-mat-drop="' + i + '">移除</button></li>'
        );
      })
      .join("");
  }

  async function addMaterial() {
    var fileInput = byId("dev-mat-file");
    var file = fileInput && fileInput.files && fileInput.files[0];
    if (!file) return say(byId("dev-mat-state"), "先选择一个文件", false);
    if (file.size > MAX_PACKAGE_BYTES / 2) {
      return say(byId("dev-mat-state"), "文件太大，请压到 3MB 以内", false);
    }
    say(byId("dev-mat-state"), "读取并计算摘要…", null);
    try {
      var b64 = await readFileB64(file);
      var digest = await sha256Hex(b64);
      dev.materials.push({
        kind: (byId("dev-mat-kind") || {}).value || "OTHER",
        name: ((byId("dev-mat-name") || {}).value || file.name).trim(),
        digest: digest,
        b64: b64,
        filename: file.name,
      });
      fileInput.value = "";
      renderMaterials();
      say(byId("dev-mat-state"), "已加入（原件只留在本地，提交时统一加密）", true);
    } catch (e) {
      say(byId("dev-mat-state"), (e && e.message) || "读取失败", false);
    }
  }

  // ---- ② 签名并提交 ---------------------------------------------------------

  async function submit() {
    var status = byId("dev-status");
    var id = identity();
    if (!id) return say(status, "先连接钱包", false);
    var body = form();
    if (!dev.prepared) return say(status, "先点「① 生成待签协议」", false);
    if (!sameForm(body, dev.prepared)) {
      return say(status, "表单改过了，请重新点「① 生成待签协议」再签", false);
    }
    try {
      say(status, "② 等钱包签名…", null);
      var signature = await signMessage(dev.prepared.message);
      var payload = {
        real_name: body.real_name,
        role_title: body.role_title,
        contact_email: body.contact_email,
        role: body.role,
        signature: signature,
      };

      if (dev.materials.length) {
        say(status, "② 本地加密材料包…", null);
        var saltHex = randomHex(16);
        var keyMessage = [
          "Karma Developer Doc Key v1",
          "karma_identity_id:" + id,
          "real_name:" + body.real_name,
          "salt:" + saltHex,
        ].join("\n");
        var keySig = await signMessage(keyMessage);
        var key = await deriveKey(keySig, saltHex);
        var iv = new Uint8Array(12);
        window.crypto.getRandomValues(iv);
        var bundle = {
          kind: "karma_developer_materials_v1",
          subject: body,
          materials: dev.materials.map(function (m) {
            return { kind: m.kind, name: m.name, filename: m.filename, b64: m.b64 };
          }),
        };
        var plaintext = new window.TextEncoder().encode(JSON.stringify(bundle));
        var cipher = await window.crypto.subtle.encrypt({ name: "AES-GCM", iv: iv }, key, plaintext);
        payload.materials = dev.materials.map(function (m) {
          return { kind: m.kind, name: m.name, digest: m.digest };
        });
        payload.package_digest = await sha256Hex(cipher);
        payload.package_cipher = bufToB64(cipher);
        payload.encryption = {
          algo: "AES-GCM-256",
          kdf: "PBKDF2-SHA256",
          iterations: PBKDF2_ITERATIONS,
          salt_b64: window.btoa(saltHex),
          iv_b64: bufToB64(iv),
          key_wrap: "wallet-signature-v1",
        };
      }

      say(status, "③ 提交复核…", null);
      var res = await api().jsonPost(PATH + "/submit", payload);
      renderDetail(res);
      dev.materials = [];
      renderMaterials();
      dev.prepared = null;
      await loadMine();
      say(status, "已提交，等待复核（通过后用同一个钱包就能上架技能）", true);
    } catch (e) {
      say(status, (e && e.message) || "提交失败", false);
    }
  }

  // ---- 绑定 -----------------------------------------------------------------

  function bind() {
    var p = byId("dev-prepare");
    if (p) p.addEventListener("click", prepare);
    var s = byId("dev-submit");
    if (s) s.addEventListener("click", submit);
    var ma = byId("dev-mat-add");
    if (ma) ma.addEventListener("click", addMaterial);
    var mc = byId("dev-mat-clear");
    if (mc) {
      mc.addEventListener("click", function () {
        dev.materials = [];
        renderMaterials();
      });
    }
    var list = byId("dev-mat-list");
    if (list) {
      list.addEventListener("click", function (ev) {
        var attr =
          ev.target && ev.target.getAttribute && ev.target.getAttribute("data-dev-mat-drop");
        if (attr == null) return;
        dev.materials.splice(Number(attr), 1);
        renderMaterials();
      });
    }
    var rf = byId("dev-refresh");
    if (rf) rf.addEventListener("click", loadMine);

    document.addEventListener("karma-wallet-connected", function () {
      loadMine();
    });
    document.addEventListener("karma-session-restored", function () {
      loadMine();
    });
    document.addEventListener("karma-page-shown", function (ev) {
      var detail = (ev && ev.detail) || {};
      if (detail.page === "identity" && detail.sub === "developer") loadMine();
    });

    renderMaterials();
    loadMine();
  }

  window.KarmaDeveloperConsole = { refresh: loadMine, state: dev };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind);
  } else {
    bind();
  }
})();