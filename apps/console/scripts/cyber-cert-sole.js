/**
 * 个体助理认证 —— 个体工商户 / 个人经营者。
 *
 * 为什么单独一条流程：个体户往往没有官网，走不了企业那套「官网控制权」校验。
 * 所以这里认的是「营业执照 + 经营范围 + 主营产品 + 经营地址 + 联系方式」，
 * 落在身份档案（class=merchant）的 KYC 上，由复核岗按同一套状态机复核。
 *
 * 红线与其它认证页一致：
 *  - 资质原件的明文永远不出这台设备：本地 AES-GCM-256 加密，只上传密文包与 sha256 摘要。
 *  - 密钥由钱包签名在本地派生（PBKDF2）；Karma 没有私钥，也复现不了这个签名。
 */
(function () {
  "use strict";

  var PBKDF2_ITERATIONS = 250000;
  var MAX_FILE_BYTES = 1.5 * 1024 * 1024;
  var MAX_PACKAGE_BYTES = 4 * 1024 * 1024;

  var sole = { docs: [] };

  function byId(id) {
    return document.getElementById(id);
  }

  function api() {
    return window.cyberKarmaApi || {};
  }

  function cert() {
    return window.KarmaCert || {};
  }

  function identity() {
    return cert().identity ? cert().identity() : String(window.KARMA_IDENTITY_ID || "").trim();
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

  function value(id) {
    var node = byId(id);
    return node ? String(node.value || "").trim() : "";
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

  // ---- 主体信息 -------------------------------------------------------------

  var FIELDS = [
    ["sole-name", "business_name", "字号 / 主体名称"],
    ["sole-operator", "operator_name", "经营者姓名"],
    ["sole-reg-no", "registration_no", ""],
    ["sole-region", "region", ""],
    ["sole-scope", "business_scope", "经营范围"],
    ["sole-products", "main_products", "主营产品 / 服务"],
    ["sole-address", "business_address", "经营地址"],
    ["sole-phone", "contact_phone", ""],
    ["sole-email", "contact_email", "联系邮箱"],
  ];

  function subjectBody() {
    var out = {};
    FIELDS.forEach(function (f) { out[f[1]] = value(f[0]); });
    return out;
  }

  function missingFields() {
    var missing = [];
    FIELDS.forEach(function (f) {
      if (f[2] && !value(f[0])) missing.push(f[2]);
    });
    var email = value("sole-email");
    if (email && email.indexOf("@") < 1) missing.push("联系邮箱（格式不对）");
    return missing;
  }

  function displayName() {
    return value("sole-display") || value("sole-name");
  }

  // ---- 状态与回显 -----------------------------------------------------------

  var KYC_LABELS = {
    none: "未提交",
    pending: "复核中",
    verified: "已通过",
    rejected: "已驳回",
  };

  function renderProfiles(profiles) {
    var badge = byId("sole-badge");
    var host = byId("sole-list");
    var rows = profiles || [];
    var first = rows[0] || null;
    if (badge) {
      badge.textContent = first ? KYC_LABELS[first.kyc_status] || first.kyc_status : "未提交";
      badge.classList.toggle("ok", !!first && first.kyc_status === "verified");
      badge.classList.toggle("bad", !!first && first.kyc_status === "rejected");
    }
    if (!host) return;
    if (!rows.length) {
      host.innerHTML = "<li>还没有个体助理身份。填完上面的资料提交一次，这里就会出现它和它的复核状态。</li>";
      return;
    }
    host.innerHTML = rows
      .map(function (p) {
        var status = KYC_LABELS[p.kyc_status] || p.kyc_status || "未提交";
        var payload = p.kyc_payload || {};
        var who = p.display_name || payload.business_name || p.profile_id;
        var where = payload.business_address ? " · " + esc(payload.business_address) : "";
        var note = payload.verification && payload.verification.reason
          ? "<br /><span style=\"color:#f87171\">驳回原因：" + esc(payload.verification.reason) + "</span>"
          : "";
        return "<li><b>" + esc(who) + "</b> · " + esc(status) + where + note + "</li>";
      })
      .join("");
  }

  async function loadProfiles() {
    var id = identity();
    if (!id) {
      renderProfiles([]);
      say(byId("sole-status"), "先连接钱包", false);
      return [];
    }
    try {
      var rows = await cert().listProfiles("merchant");
      renderProfiles(rows);
      prefill(rows[0]);
      return rows;
    } catch (e) {
      say(byId("sole-status"), (e && e.message) || "读取失败", false);
      return [];
    }
  }

  /** 已经交过的资料回填到表单：刷新页面不用重打一遍。 */
  function prefill(profile) {
    var payload = profile && profile.kyc_payload;
    if (!payload || payload.kind !== "sole_proprietor") return;
    FIELDS.forEach(function (f) {
      var node = byId(f[0]);
      if (node && !node.value && payload[f[1]]) node.value = payload[f[1]];
    });
    var docs = payload.docs || [];
    if (docs.length) {
      say(byId("sole-doc-add-state"), "已提交 " + docs.length + " 份（原件不再回显，如需更新请重新上传）", null);
    }
  }

  // ---- 资质 -----------------------------------------------------------------

  function renderDocs() {
    var host = byId("sole-doc-list");
    var count = byId("sole-doc-count");
    if (count) count.textContent = sole.docs.length + " 份";
    if (!host) return;
    host.innerHTML = sole.docs.length
      ? sole.docs
          .map(function (d) {
            return "<li><b>" + esc(d.name) + "</b> · " + esc(d.kind) + " · 摘要 " + esc(d.digest.slice(0, 12)) + "…</li>";
          })
          .join("")
      : "<li>还没有加入资质。营业执照必传。</li>";
    refreshSubmitState();
  }

  async function addDoc() {
    var input = byId("sole-doc-file");
    var file = input && input.files && input.files[0];
    if (!file) return say(byId("sole-doc-add-state"), "先选择一个文件", false);
    if (file.size > MAX_FILE_BYTES) {
      return say(byId("sole-doc-add-state"), "文件太大，请压到 1.5MB 以内", false);
    }
    say(byId("sole-doc-add-state"), "读取并计算摘要…", null);
    try {
      var b64 = await readFileB64(file);
      var digest = await sha256Hex(b64);
      sole.docs.push({
        kind: (byId("sole-doc-kind") || {}).value || "OTHER",
        name: (value("sole-doc-name") || file.name).trim(),
        digest: digest,
        b64: b64,
        filename: file.name,
      });
      input.value = "";
      renderDocs();
      say(byId("sole-doc-add-state"), "已加入（原件只留在本地，提交时统一加密）", true);
    } catch (e) {
      say(byId("sole-doc-add-state"), (e && e.message) || "读取失败", false);
    }
  }

  // ---- 提交 -----------------------------------------------------------------

  function refreshSubmitState() {
    var btn = byId("sole-submit");
    if (!btn) return;
    var consent = byId("sole-consent");
    var ready = !!identity() && !!consent && consent.checked && sole.docs.length > 0;
    btn.disabled = !ready;
  }

  async function submit() {
    var status = byId("sole-status");
    var id = identity();
    if (!id) return say(status, "先连接钱包", false);
    var consent = byId("sole-consent");
    if (!consent || !consent.checked) return say(status, "请先勾选真实性确认", false);
    var missing = missingFields();
    if (missing.length) return say(status, "还差：" + missing.join(" / "), false);
    if (!sole.docs.some(function (d) { return d.kind === "BUSINESS_LICENSE"; })) {
      return say(status, "至少要加入一份营业执照（资质类型选「营业执照」）", false);
    }
    var total = sole.docs.reduce(function (n, d) { return n + d.b64.length; }, 0);
    if (total > MAX_PACKAGE_BYTES) {
      return say(status, "资质总量太大，请减少份数或压缩后再传", false);
    }

    var subject = subjectBody();
    try {
      say(status, "① 建立 / 匹配个体身份档案…", null);
      var profile = await cert().ensureProfile("merchant", displayName());
      var profileId = profile && profile.profile_id;
      if (!profileId) throw new Error("身份档案建立失败");

      say(status, "② 等钱包签名派生密钥…", null);
      var saltHex = randomHex(16);
      var message = [
        "Karma Sole Proprietor Doc Key v1",
        "karma_identity_id:" + id,
        "profile_id:" + profileId,
        "salt:" + saltHex,
      ].join("\n");
      var signature = await signMessage(message);

      say(status, "③ 本地加密资质包…", null);
      var key = await deriveKey(signature, saltHex);
      var iv = new Uint8Array(12);
      window.crypto.getRandomValues(iv);
      var bundle = {
        kind: "karma_sole_certifications_v1",
        subject: subject,
        certifications: sole.docs.map(function (d) {
          return { kind: d.kind, name: d.name, filename: d.filename, b64: d.b64 };
        }),
      };
      var plaintext = new window.TextEncoder().encode(JSON.stringify(bundle));
      var cipher = await window.crypto.subtle.encrypt({ name: "AES-GCM", iv: iv }, key, plaintext);
      var docDigest = await sha256Hex(sole.docs.map(function (d) { return d.digest; }).join("|"));

      var payload = Object.assign({ kind: "sole_proprietor", consent: true }, subject, {
        docs: sole.docs.map(function (d) {
          return { kind: d.kind, name: d.name, digest: d.digest };
        }),
        doc_digest: docDigest,
        package_digest: await sha256Hex(cipher),
        package_cipher: bufToB64(cipher),
        encryption: {
          algo: "AES-GCM-256",
          kdf: "PBKDF2-SHA256",
          iterations: PBKDF2_ITERATIONS,
          salt_b64: window.btoa(saltHex),
          iv_b64: bufToB64(iv),
          key_wrap: "wallet-signature-v1",
        },
      });

      say(status, "④ 提交复核…", null);
      await api().submitKyc(profileId, payload);
      say(status, "已提交，等待复核（密文包 " + Math.round(bufToB64(cipher).length / 1024) + " KB）", true);
      sole.docs = [];
      renderDocs();
      await cert().refreshIdentities();
      await loadProfiles();
    } catch (e) {
      say(status, (e && (e.message || e.detail)) || "提交失败", false);
    }
  }

  function reset() {
    sole.docs = [];
    FIELDS.forEach(function (f) {
      var node = byId(f[0]);
      if (node) node.value = "";
    });
    var display = byId("sole-display");
    if (display) display.value = "";
    var consent = byId("sole-consent");
    if (consent) consent.checked = false;
    var status = byId("sole-status");
    if (status) status.textContent = "—";
    renderDocs();
  }

  function init() {
    var add = byId("sole-doc-add");
    if (add) add.addEventListener("click", function () { addDoc(); });
    var clear = byId("sole-doc-clear");
    if (clear) {
      clear.addEventListener("click", function () {
        sole.docs = [];
        renderDocs();
        say(byId("sole-doc-add-state"), "已清空", null);
      });
    }
    var submitBtn = byId("sole-submit");
    if (submitBtn) submitBtn.addEventListener("click", function () { submit(); });
    var resetBtn = byId("sole-reset");
    if (resetBtn) resetBtn.addEventListener("click", reset);
    var consent = byId("sole-consent");
    if (consent) consent.addEventListener("change", refreshSubmitState);
    ["sole-name", "sole-operator", "sole-scope", "sole-products", "sole-address", "sole-email"].forEach(function (id) {
      var node = byId(id);
      if (node) node.addEventListener("input", refreshSubmitState);
    });
    renderDocs();
    loadProfiles();
    document.addEventListener("karma-wallet-connected", function () { loadProfiles(); });
    document.addEventListener("karma-session-restored", function () { loadProfiles(); });
    document.addEventListener("karma-profile-switched", function () { refreshSubmitState(); });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
