/**
 * 身份 · 认证 —— 一个页面把「我是谁」和「我认证过」做完。
 *
 * 主身份：连钱包 → 上传证件 + 刷脸 → 本地加密 → 提交 → 核验通过 = 身份卡生效。
 * 子身份：角色（生活 / 工作 / 企业助理）+ 权限 + 额度 + 边界 + 操作钱包 + 刷脸。
 *
 * 红线（和 services/identity_verification.py 一致）：
 * - 证件与人脸只在浏览器里存在；加密（AES-GCM-256）之后才上传。
 * - 只调用钱包的 personal_sign 派生密钥，永不读取私钥 / 助记词。
 * - 证件号只上传后 4 位掩码，完整号码不出本机。
 */
(function () {
  "use strict";

  var MAX_SIDE = 1280;
  var JPEG_QUALITY = 0.72;
  var PBKDF2_ITERATIONS = 250000;

  var state = {
    docFront: null,
    docBack: null,
    face: null,
    stream: null,
    submitting: false,
    serverStatus: "none",
    lastPackage: null,
    subFace: null,
    subWallet: "",
    subWalletSignature: "",
  };

  /* 三种身份，和侧栏「选择身份」、三张认证页一一对应。 */
  var ROLES = {
    life: { label: "生活助理", klass: "individual" },
    sole: { label: "个体助理", klass: "merchant" },
    entity: { label: "企业主体", klass: "enterprise" },
  };

  var PERM_LABELS = {
    request_voucher: "开付款凭证",
    verify_voucher: "核验对方凭证",
    submit_receipt: "提交回执",
    update_progress: "更新进度",
    request_settlement: "发起结算",
    sync_task_status: "同步任务状态",
    discover_agents: "发现 agent / 商家",
    place_order: "在额度内下单",
  };
  var DEFAULT_PERMS = [
    "request_voucher",
    "submit_receipt",
    "update_progress",
    "request_settlement",
    "sync_task_status",
  ];

  var VERIFY_LABELS = {
    none: "未认证",
    pending: "核验中",
    verified: "已认证",
    rejected: "被拒，可重新提交",
  };

  function byId(id) {
    return document.getElementById(id);
  }

  function api() {
    return window.cyberKarmaApi;
  }

  function identity() {
    return String(window.KARMA_IDENTITY_ID || "").trim();
  }

  function session() {
    try {
      return window.KarmaWalletAuth && window.KarmaWalletAuth.readSession
        ? window.KarmaWalletAuth.readSession()
        : {};
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
    node.textContent = text;
    node.style.color = ok === true ? "var(--accent,#4ade80)" : ok === false ? "#f87171" : "var(--text-dim)";
  }

  function money(n) {
    var v = Number(n);
    if (!isFinite(v)) return "—";
    return (Math.round(v * 100) / 100).toFixed(2);
  }

  /** 译文（没接 i18n 或没这条译文时原样返回中文）。 */
  function T(zh) {
    var i18n = window.CYBER_I18N;
    return i18n && i18n.T ? i18n.T(zh) : zh;
  }

  /** 模板版：Tf("同一个人：相似度 {0}", 0.9) —— 带变量的整句才不会被拆成半中半英。 */
  function Tf(zh) {
    var i18n = window.CYBER_I18N;
    if (i18n && i18n.Tf) return i18n.Tf.apply(i18n, arguments);
    var out = String(zh == null ? "" : zh);
    for (var i = 1; i < arguments.length; i += 1) {
      out = out.split("{" + (i - 1) + "}").join(arguments[i] == null ? "" : String(arguments[i]));
    }
    return out;
  }

  // ---- 本地加密管线 --------------------------------------------------------

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
    for (var i = 0; i < bytes.length; i += 1) {
      out += ("0" + bytes[i].toString(16)).slice(-2);
    }
    return out;
  }

  function sha256Hex(buf) {
    return window.crypto.subtle.digest("SHA-256", buf).then(function (d) {
      var bytes = new Uint8Array(d);
      var out = "";
      for (var i = 0; i < bytes.length; i += 1) out += ("0" + bytes[i].toString(16)).slice(-2);
      return out;
    });
  }

  /** 密钥来自钱包签名：Karma 没有私钥，也复现不了这个签名。 */
  function keyMessage(saltHex) {
    return [
      "Karma Identity Doc Key v1",
      "karma_identity_id:" + identity(),
      "salt:" + saltHex,
    ].join("\n");
  }

  /** 大图先压到长边 1280、JPEG 0.72：密文包要待在 8MB 以内。 */
  function fileToScaledB64(file) {
    return new Promise(function (resolve, reject) {
      var reader = new FileReader();
      reader.onerror = function () { reject(new Error("读取文件失败")); };
      reader.onload = function () {
        var img = new Image();
        img.onerror = function () { reject(new Error("这不是一张能识别的图片")); };
        img.onload = function () {
          var scale = Math.min(1, MAX_SIDE / Math.max(img.width, img.height));
          var canvas = document.createElement("canvas");
          canvas.width = Math.max(1, Math.round(img.width * scale));
          canvas.height = Math.max(1, Math.round(img.height * scale));
          canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
          var url = canvas.toDataURL("image/jpeg", JPEG_QUALITY);
          resolve({ b64: url.split(",")[1] || "", mime: "image/jpeg" });
        };
        img.src = String(reader.result);
      };
      reader.readAsDataURL(file);
    });
  }

  function thumb(node, b64) {
    if (!node) return;
    node.innerHTML = b64
      ? '<img alt="已采集" src="data:image/jpeg;base64,' + b64 + '" />'
      : "";
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

  async function signKeyMessage(message) {
    var provider = walletProvider();
    var addr = session().wallet;
    if (!provider || !addr) throw new Error("请先连接钱包（右上角「连接钱包」）");
    return provider.request({ method: "personal_sign", params: [message, addr] });
  }

  // ---- 主身份卡 ------------------------------------------------------------

  function renderMaster() {
    var id = identity();
    var s = session();
    // 对外只显示 kid1 编号；真 ID 放 title，鼠标停一下就能复制。
    var idNode = byId("idv-master-id");
    if (idNode) {
      var shown = id || "";
      try {
        if (shown && window.KarmaDisplayId && window.KarmaDisplayId.of) {
          shown = window.KarmaDisplayId.of(shown, 0);
        }
      } catch (_) {}
      idNode.textContent = shown || "—";
      idNode.title = id || "";
    }
    byId("idv-master-wallet").textContent = s.wallet || "—";
    var badge = byId("idv-master-badge");
    if (badge) {
      badge.textContent = id ? "已连接" : "未连接钱包";
      badge.className = "idv-badge" + (id ? " on" : "");
    }
  }

  async function loadMasterMoney() {
    var id = identity();
    var node = byId("idv-master-money");
    if (!node) return;
    if (!id) { node.textContent = "—"; return; }
    var locked = 0;
    var allocated = 0;
    try {
      var esc = await api().getEscrowState(id);
      locked = Number((esc && esc.committed_usdc) || 0);
    } catch (_) {}
    if (!locked) {
      try {
        var cap = await api().getCapacity(id);
        locked = Number((cap && cap.total_locked_usdc) || 0);
      } catch (_) {}
    }
    try {
      var alloc = await api().getAllocations(id);
      (alloc.allocations || []).forEach(function (row) {
        allocated += Number(row.allocated_credits || 0);
      });
    } catch (_) {}
    node.textContent =
      money(locked) + " / " + money(allocated) + " / " + money(Math.max(0, locked - allocated)) + " USDC";
  }

  async function loadVerification() {
    var id = identity();
    var badge = byId("idv-verify-badge");
    if (!id) {
      if (badge) { badge.textContent = "未连接钱包"; badge.className = "idv-badge"; }
      refreshSubmitState();
      return;
    }
    refreshSubmitState();
    try {
      var v = await api().getIdentityVerification(id);
      var status = (v && v.status) || "none";
      state.serverStatus = status;
      if (badge) {
        badge.textContent = VERIFY_LABELS[status] || status;
        badge.className = "idv-badge" + (status === "verified" ? " on" : status === "rejected" ? " bad" : "");
      }
      var node = byId("idv-master-verify");
      if (node) node.textContent = VERIFY_LABELS[status] || status;
      if (status === "pending" || status === "verified") {
        var send = byId("idv-send-state");
        if (send) send.textContent = status === "verified" ? "已通过" : "已提交，等核验";
        var submit = byId("idv-submit");
        if (submit && status === "verified") {
          submit.disabled = true;
          submit.textContent = "已认证";
        }
      }
      // 状态拿到之后再说一次「还差什么」：交过的（pending / verified）不该继续催提交。
      refreshSubmitState();
    } catch (e) {
      if (badge) badge.textContent = "状态读取失败";
      refreshSubmitState();
    }
  }

  // ---- 提交 ---------------------------------------------------------------

  function maskDocNumber(raw) {
    var digits = String(raw || "").replace(/[^0-9A-Za-z]/g, "");
    if (!digits) return "";
    if (digits.length <= 4) return "****" + digits;
    return "*".repeat(Math.min(12, digits.length - 4)) + digits.slice(-4);
  }

  /**
   * 差哪几项才能提交。
   *
   * 之前这里只算一个 ready，按钮静默变灰 —— 用户把资料全填了却不知道为什么点不动。
   * 现在把「还差什么」原样列出来，灰按钮旁边必须看得见原因。
   */
  function submitMissing() {
    var missing = [];
    if (!identity()) missing.push("连接钱包");
    if (!state.docFront) missing.push("证件正面");
    if (!state.face) missing.push("刷脸（正/左/右/抬/低 五个角度）");
    if (!String((byId("idv-name") || {}).value || "").trim()) missing.push("姓名");
    if (!String((byId("idv-doc-number") || {}).value || "").trim()) missing.push("证件号（后 4 位）");
    if (!(byId("idv-consent") || {}).checked) missing.push("勾选真实性确认");
    return missing;
  }

  function refreshSubmitState() {
    var missing = submitMissing();
    // 已经交过（pending / verified）就不再放行：再点只会换回一个 409。
    var alreadySent = state.serverStatus === "pending" || state.serverStatus === "verified";
    var submit = byId("idv-submit");
    if (!submit) return;
    submit.disabled = missing.length > 0 || state.submitting || alreadySent;
    var why = byId("idv-need");
    var text;
    if (alreadySent) {
      text = "已经提交过了 —— 等核验结果就行，同一份不用交两次。";
    } else if (state.submitting) {
      text = "正在提交…";
    } else if (missing.length) {
      text = "还差：" + missing.join(" / ");
    } else {
      text = "都齐了，点「提交认证」就行。";
    }
    // title 也带上：鼠标停在按钮上一样能看见差什么。
    submit.title = missing.length ? "还差：" + missing.join(" / ") : "";
    if (why) {
      why.textContent = text;
      why.className = "idv-need" + (!missing.length && !alreadySent && !state.submitting ? " ok" : "");
    }
  }

  async function submitVerification() {
    if (state.submitting) return;
    var status = byId("idv-status");
    var id = identity();
    if (!id) { say(status, "请先连接钱包", false); return; }

    state.submitting = true;
    refreshSubmitState();
    try {
      say(
        status,
        "① 证件就绪，② 人脸 " + (faceFrames().length ? faceFrames().length + " 个角度" : "照片通道") + " 已就绪，正在本地加密…",
        null
      );
      var bundle = {
        v: 1,
        identity_id: id,
        created_at: new Date().toISOString(),
        doc_front_b64: state.docFront ? state.docFront.b64 : "",
        doc_front_mime: state.docFront ? state.docFront.mime : "",
        doc_back_b64: state.docBack ? state.docBack.b64 : "",
        doc_back_mime: state.docBack ? state.docBack.mime : "",
        face_b64: state.face ? state.face.b64 : "",
        face_mime: state.face ? state.face.mime : "",
        // 人脸不再是「一张」：五个角度全部进密文包，复核方拿到的是一整组姿态。
        face_source: (state.face && state.face.source) || "",
        face_frames: faceFrames(),
      };
      var saltHex = randomHex(16);
      var signature = await signKeyMessage(keyMessage(saltHex));
      say(status, "③ 钱包已签名，正在加密…", null);
      var pack = await encryptPackageWithSalt(bundle, signature, saltHex);
      state.lastPackage = pack;
      byId("idv-enc-state").textContent = "已加密 " + Math.round(pack.cipherB64.length / 1024) + " KB";
      say(status, "④ 正在提交…", null);

      var body = {
        level: "basic",
        doc_digest: pack.docDigest,
        face_digest: pack.faceDigest,
        package_digest: pack.packageDigest,
        package_cipher: pack.cipherB64,
        encryption: pack.encryption,
        extracted: {
          full_name: String(byId("idv-name").value || "").trim(),
          doc_type: byId("idv-doc-type").value,
          doc_number_mask: maskDocNumber(byId("idv-doc-number").value),
          valid_until: String(byId("idv-valid").value || "").trim(),
          // 复核结果要有人可通知：邮箱是联系方式的必填项。
          contact_email: String((byId("idv-email") || {}).value || "").trim(),
          contact_phone: String((byId("idv-phone") || {}).value || "").trim(),
          // 复核方一眼要能分辨：这是活体多角度采集，还是走了单张照片的兜底通道。
          face_match_hint: faceHint(),
          consent: true,
        },
      };
      var saved = await api().submitIdentityVerification(id, body);
      byId("idv-send-state").textContent = "已提交";
      say(status, "已提交，等核验（状态：" + (VERIFY_LABELS[saved.status] || saved.status) + "）", true);
      byId("idv-submit").disabled = true;
      await loadVerification();
    } catch (e) {
      say(status, "提交失败：" + (e && (e.message || e.detail) || e), false);
    } finally {
      state.submitting = false;
      refreshSubmitState();
    }
  }

  /** 采集结果里的人脸帧：多角度采集是几帧，照片兜底通道是空数组。 */
  function faceFrames() {
    var face = state.face;
    if (!face || !Array.isArray(face.frames)) return [];
    return face.frames
      .filter(function (f) { return f && f.b64; })
      .map(function (f) {
        return {
          angle: f.angle || "",
          label: f.label || "",
          mime: f.mime || "image/jpeg",
          b64: f.b64,
          via: f.via || "camera",
          motion: typeof f.diff === "number" ? f.diff : null,
        };
      });
  }

  /** 复核方的提示条：写清是哪种采集通道、采了几个角度。 */
  function faceHint() {
    var face = state.face;
    if (!face) return "";
    var frames = faceFrames();
    if (face.source === "photo" || !frames.length) return "照片通道（非多角度采集）";
    var labels = frames
      .map(function (f) { return f.label || f.angle; })
      .filter(Boolean);
    return (frames.length + "角度采集:" + labels.join("/")).slice(0, 32);
  }

  /**
   * 人脸摘要必须覆盖**全部角度**。
   * 只对第一张算摘要的话，后面几张被人换掉也查不出来 —— 摘要就白做了。
   */
  function faceDigestInput(bundle) {
    var frames = Array.isArray(bundle.face_frames) ? bundle.face_frames : [];
    if (!frames.length) return String(bundle.face_b64 || "");
    return frames
      .map(function (f) {
        return String((f && f.angle) || "") + ":" + String((f && f.b64) || "");
      })
      .join("|");
  }

  /** 证件包和人脸包共用这一个加密管线：盐由调用方给，避免重复弹钱包签名。 */
  async function encryptPackageWithSalt(bundle, signatureHex, saltHex) {
    // 需要在 deriveKey 里用同一个盐，所以这里重新走一遍，避免两次签名。
    var iv = new Uint8Array(12);
    window.crypto.getRandomValues(iv);
    var key = await deriveKeyWithSalt(signatureHex, saltHex);
    var plaintext = new window.TextEncoder().encode(JSON.stringify(bundle));
    var cipher = await window.crypto.subtle.encrypt({ name: "AES-GCM", iv: iv }, key, plaintext);
    return {
      cipherB64: bufToB64(cipher),
      packageDigest: await sha256Hex(cipher),
      docDigest: await sha256Hex(new window.TextEncoder().encode(bundle.doc_front_b64 || "")),
      faceDigest: await sha256Hex(new window.TextEncoder().encode(faceDigestInput(bundle))),
      encryption: {
        algo: "AES-GCM-256",
        kdf: "PBKDF2-SHA256",
        iterations: PBKDF2_ITERATIONS,
        salt_b64: window.btoa(saltHex),
        iv_b64: bufToB64(iv),
        key_wrap: "wallet-signature-v1",
      },
    };
  }

  async function deriveKeyWithSalt(signatureHex, saltHex) {
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

  // ---- 子身份 --------------------------------------------------------------

  /** 生活助理走本页这条直线；个体 / 企业要走各自的资质认证页，选完类型把入口亮出来。 */
  var SUB_ROUTE = {
    sole: {
      sub: "sole",
      hint: "个体助理认证走资质流程：营业执照 + 经营范围 + 经营地址 + 联系方式，复核通过后这张卡才会开通。",
      cta: "去完成个体助理认证",
    },
    entity: {
      sub: "enterprise",
      hint: "企业主体认证走资质流程：营业执照 + 法定代表人 + 官网控制权 + 企业邮箱，复核通过后这张卡才会开通。",
      cta: "去完成企业主体认证",
    },
  };

  /** 选了类型就切形态：生活助理直接建卡，个体 / 企业跳到自己的认证流程。 */
  function syncSubRoute() {
    var roleKey = String((byId("idsub-role") || {}).value || "life");
    var route = SUB_ROUTE[roleKey];
    var direct = byId("idsub-direct");
    var create = byId("idsub-create");
    var hint = byId("idsub-route-hint");
    var go = byId("idsub-route-go");
    var cta = byId("idsub-goto-cert");
    if (direct) direct.hidden = !!route;
    if (create) create.hidden = !!route;
    if (hint) {
      hint.hidden = !route;
      hint.textContent = route ? route.hint : "";
    }
    if (go) go.hidden = !route;
    if (cta && route) cta.textContent = route.cta;
  }

  function permsNode() {
    var host = byId("idsub-perms");
    if (!host || host.childElementCount) return host;
    Object.keys(PERM_LABELS).forEach(function (perm) {
      var label = document.createElement("label");
      label.className = "idv-perm";
      label.innerHTML =
        '<input type="checkbox" value="' + esc(perm) + '"' +
        (DEFAULT_PERMS.indexOf(perm) >= 0 ? " checked" : "") + " /> " + esc(PERM_LABELS[perm]);
      host.appendChild(label);
    });
    return host;
  }

  function selectedPerms() {
    var host = permsNode();
    if (!host) return [];
    return Array.prototype.slice
      .call(host.querySelectorAll("input:checked"))
      .map(function (i) { return i.value; });
  }

  /** 人脸 / KYC 状态的对外说法。 */
  var KYC_LABELS = { none: "未采集", pending: "复核中", verified: "已通过", rejected: "未通过" };

  async function loadSubs() {
    var host = byId("idsub-list");
    if (!host) return;
    var id = identity();
    if (!id) { host.textContent = "连接钱包后显示你的子身份"; return; }
    try {
      var body = await api().listRoleProfiles(id);
      var profiles = (body && body.profiles) || [];
      if (!profiles.length) { host.textContent = "还没有子身份。点右上角「+ 新建子身份」。"; return; }
      var allocs = {};
      try {
        var a = await api().getAllocations(id);
        (a.allocations || []).forEach(function (r) { allocs[r.profile_id] = r; });
      } catch (_) {}
      host.innerHTML = "";
      profiles.forEach(function (p, idx) {
        var row = allocs[p.profile_id];
        var el = document.createElement("div");
        el.className = "idv-sub-row";
        // 对外只说人话：角色名 + kid 编号，不把 verifier / individual 这种底座类名和 profile_id 写给用户看。
        var sw = window.KarmaIdentitySwitcher;
        var did = window.KarmaDisplayId;
        var title = (sw && sw.identityTitle ? sw.identityTitle(p) : "") || p.display_name || "子身份";
        var label = did && did.of ? did.of(p.profile_id, idx + 1) : "子身份" + (idx + 1);
        // 同人刷脸开的档 ≠ 走资质复核审过的档：文案必须分得开（G9）。
        var faceOpened = !!(p.kyc_payload && p.kyc_payload.face_consistency);
        var kyc = p.kyc_status === "verified" && faceOpened
          ? T("同人刷脸已核验")
          : T(KYC_LABELS[p.kyc_status] || "未采集");
        var wallet = String(p.bound_wallet_address || "");
        var walletText = wallet
          ? (wallet.length > 12 ? wallet.slice(0, 6) + "…" + wallet.slice(-4) : wallet)
          : "未绑操作钱包";
        el.innerHTML =
          '<div class="idv-sub-main"><b>' + esc(title) + "</b>" +
          "<span>" + esc(label) + "</span></div>" +
          '<div class="idv-sub-meta">额度 ' + money(row ? row.allocated_credits : 0) + " USDC</div>" +
          '<div class="idv-sub-meta">' + esc(Tf("人脸 {0}", kyc)) + "</div>" +
          '<div class="idv-sub-meta">' + esc(walletText) + "</div>";
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "btn";
        btn.textContent = "切到这张";
        btn.addEventListener("click", function () {
          if (window.KarmaIdentitySwitcher && window.KarmaIdentitySwitcher.setActiveProfileId) {
            window.KarmaIdentitySwitcher.setActiveProfileId(p.profile_id);
          }
        });
        el.appendChild(btn);
        // 还没开通的卡：本人再刷一次脸当场开通 —— 不用把这张卡推倒重建。
        if (!(p.kyc_status === "verified" && faceOpened)) {
          var faceBtn = document.createElement("button");
          faceBtn.type = "button";
          faceBtn.className = "btn";
          faceBtn.textContent = "刷脸确认";
          faceBtn.addEventListener("click", function () {
            faceConfirm(p.profile_id, p["class"], faceBtn);
          });
          el.appendChild(faceBtn);
        }
        host.appendChild(el);
      });
    } catch (e) {
      host.textContent = "读取失败：" + (e && (e.message || e) || e);
    }
  }

  /** 上一次的分流块先撤掉：重试成功时别让旧提示继续挂着。 */
  function clearFaceRoute(status) {
    if (!status || !status.parentNode) return;
    var next = status.nextSibling;
    while (next) {
      var after = next.nextSibling;
      if (next.nodeType === 1 && String(next.className || "").indexOf("idv-face-route") >= 0) {
        status.parentNode.removeChild(next);
      }
      next = after;
    }
  }

  /**
   * 参考脸拿不到时的分流提示：不只说「为什么」，还把「下一步点哪」摆出来。
   *
   * 主体认证留过底、但那份包本机解不开（早期记录 / 换过钱包）时，卡本身没问题 ——
   * 去主身份页刷一次脸重建可比对的脸，回来点「刷脸确认」即可，不用把卡推倒重建。
   * 返回 true 表示这块提示已经接管，调用方不必再写一遍原始报错。
   */
  function faceRouteHint(status, err) {
    var code = String((err && err.code) || "");
    if (
      code !== "face_on_file_missing" &&
      code !== "face_package_legacy" &&
      code !== "face_package_unopenable"
    ) {
      return false;
    }
    if (!status || !status.parentNode) return false;
    clearFaceRoute(status);
    say(status, String((err && err.message) || err), false);
    var box = document.createElement("div");
    box.className = "idv-face-route";
    var how = document.createElement("p");
    how.className = "idv-face-route-lead";
    how.textContent = T(
      "这张卡不用重建：去主身份页刷一次脸激活（只需一次），回来再点「刷脸确认」，同一个人就当场开通。"
    );
    var go = document.createElement("button");
    go.type = "button";
    go.className = "btn";
    go.textContent = T("去主身份页刷脸激活 →");
    go.addEventListener("click", function () {
      if (window.cyberSwitchPage) window.cyberSwitchPage("identity", "master");
      var step = document.getElementById("mst-step-activate");
      if (step && step.scrollIntoView) step.scrollIntoView({ block: "center" });
    });
    box.appendChild(how);
    box.appendChild(go);
    status.parentNode.insertBefore(box, status.nextSibling);
    return true;
  }

  /**
   * 已经建好的卡：本人刷一次脸，跟主身份首次激活留下的模板比一次 —— 同一个人当场开通。
   *
   * 判据在脸上，不在材料上：主身份还没刷过脸（本机没有模板）时这里会把原因如实说出来
   * （「先把主身份刷脸激活，再来加身份」），绝不把卡硬写成已核验。
   */
  async function faceConfirm(profileId, className, btn) {
    var status = byId("idsub-list-status");
    var vault = window.KarmaFaceVault;
    if (!vault || !vault.confirmSamePerson) {
      say(status, "刷脸模块未加载，请刷新页面后再试。", false);
      return;
    }
    if (btn) btn.disabled = true;
    clearFaceRoute(status);
    say(status, "正在比对这一次的脸和首次激活留下的模板…", null);
    try {
      var res = await vault.confirmSamePerson(profileId, className);
      if (!res) {
        say(status, "已取消。", null);
        if (btn) btn.disabled = false;
        return;
      }
      var thr = res.verdict && res.verdict.threshold;
      say(
        status,
        Tf(
          "同一个人：相似度 {0}（阈值 {1}）。这张卡已经开通。",
          Number(res.score).toFixed(4),
          thr != null ? Number(thr).toFixed(4) : "—"
        ),
        true
      );
      try { document.dispatchEvent(new CustomEvent("karma-capacity-changed")); } catch (_) {}
      await loadSubs();
    } catch (e) {
      if (btn) btn.disabled = false;
      if (faceRouteHint(status, e)) return;
      say(status, String((e && (e.message || e)) || e), false);
    }
  }

  async function createSub() {
    var status = byId("idsub-status");
    clearFaceRoute(status);
    var id = identity();
    if (!id) { say(status, "请先连接钱包", false); return; }
    var roleKey = byId("idsub-role").value;
    var role = ROLES[roleKey] || ROLES.life;
    if (SUB_ROUTE[roleKey]) {
      say(status, "个体 / 企业身份要走各自的资质认证：点上面的「去完成认证」。", false);
      return;
    }
    var name = String(byId("idsub-name").value || "").trim() || role.label;
    var contact = String((byId("idsub-contact") || {}).value || "").trim();
    var amount = Number(byId("idsub-amount").value || 0);
    var single = Number(byId("idsub-single").value || 0);
    var daily = Number(byId("idsub-daily").value || 0);
    var perms = selectedPerms();
    if (!byId("idsub-ack").checked) { say(status, "请先勾选「我确认这些权限与边界」", false); return; }
    if (!perms.length) { say(status, "至少选一项权限", false); return; }
    if (single > 0 && daily > 0 && single > daily) { say(status, "单笔最高不能大于每日上限", false); return; }
    if (amount <= 0 && single > 0) { say(status, "要给它单笔额度，得先分配额度", false); return; }

    try {
      say(status, "① 建子身份…", null);
      var createBody = { owner_identity_id: id, "class": role.klass, display_name: name };
      // 联系方式是这张卡对外亮出来的资料，跟名字一起在建立时记档。
      if (contact) createBody.kyc_payload = { contact: contact };
      var created = await api().createRoleProfile(createBody);
      var profileId = created.profile_id;

      say(status, "② 写权限与边界…", null);
      await api().updateRoleProfile(profileId, {
        spend_policy: {
          permissions: perms,
          single_limit: single,
          daily_limit: daily,
          high_risk_mode: byId("idsub-human").value,
        },
      });

      if (amount > 0) {
        say(status, "③ 划额度…", null);
        var current = {};
        var existing = await api().getAllocations(id);
        (existing.allocations || []).forEach(function (r) { current[r.profile_id] = Number(r.allocated_credits || 0); });
        current[profileId] = amount;
        await api().setAllocations(id, current);
      }

      if (state.subWallet) {
        // 签名串里必须带 profile_id，所以签名只能放在建卡之后。
        say(status, "④ 绑操作钱包（要钱包签名）…", null);
        if (!state.subWalletSignature) await signSubWalletFor(profileId);
        await api().bindRoleProfileWallet(profileId, {
          wallet_address: state.subWallet,
          wallet_signature: state.subWalletSignature,
        });
      }

      var openedByFace = false;
      if (state.subFace) {
        say(status, "⑤ 核对是不是同一个人…", null);
        // 判据放在脸上：跟主身份首次激活留下的模板比一次，同一个人就当场开通。
        var vault = window.KarmaFaceVault;
        var why = "";
        var whyErr = null;
        if (vault && vault.confirmSamePerson) {
          try {
            var verdict = await vault.confirmSamePerson(profileId, role.klass, state.subFace);
            if (verdict && verdict.score != null) {
              openedByFace = true;
              say(
                status,
                Tf(
                  "同一个人：相似度 {0}（阈值 {1}）。这张卡已经开通。",
                  Number(verdict.score).toFixed(4),
                  (verdict.verdict && verdict.verdict.threshold) != null
                    ? Number(verdict.verdict.threshold).toFixed(4)
                    : "—"
                ) + " · " + name,
                true
              );
            }
          } catch (faceErr) {
            why = String((faceErr && (faceErr.message || faceErr)) || faceErr);
            whyErr = faceErr;
          }
        } else {
          why = "刷脸模块未加载";
        }
        // 同人这条路走不通（例如主身份还没刷脸激活）——
        // 退回待复核，并把原因如实写出来，不装作已经好了。
        if (!openedByFace) {
          say(status, "⑤ 先存成待复核…", null);
          try {
            var bundle = {
              v: 1, identity_id: id, profile_id: profileId,
              created_at: new Date().toISOString(),
              face_b64: state.subFace.b64, face_mime: state.subFace.mime,
            };
            var saltHex = randomHex(16);
            var sig = await signKeyMessage(keyMessage(saltHex));
            var pack = await encryptPackageWithSalt(bundle, sig, saltHex);
            await api().submitKyc(profileId, {
              kind: "face_confirm",
              face_digest: pack.faceDigest,
              package_digest: pack.packageDigest,
              package_cipher: pack.cipherB64,
              encryption: pack.encryption,
              consent: true,
            });
          } catch (faceErr) {
            say(status, "子身份已建立，但人脸提交失败：" + (faceErr && (faceErr.message || faceErr) || faceErr), false);
            await finishSub(status);
            return;
          }
        }
      }

      if (!openedByFace) {
        say(status, "✅ 子身份已建立：" + name + (why ? "（" + why + "）" : ""), true);
        // 拿不到参考脸的那几种（本机解不开留底包）：把下一步摆出来，别只留一句报错。
        if (whyErr) faceRouteHint(status, whyErr);
      }
      await finishSub(status);
    } catch (e) {
      say(status, "建立失败：" + (e && (e.message || e.detail) || e), false);
    }
  }

  async function finishSub() {
    resetSubDraft();
    byId("idsub-form").hidden = true;
    ["idsub-name", "idsub-contact", "idsub-amount", "idsub-single", "idsub-daily"].forEach(function (k) {
      var n = byId(k);
      if (n) n.value = "";
    });
    byId("idsub-ack").checked = false;
    // 建完一张卡，「选择助理身份」和「接入 Agent」都要立刻看到它 —— 两个模块都监听这个事件。
    try { document.dispatchEvent(new CustomEvent("karma-capacity-changed")); } catch (_) {}
    await loadSubs();
    await loadMasterMoney();
  }

  /** 清掉这次草稿：新建/取消一张卡时，不继承上一张的操作钱包和已采集的人脸。 */
  function resetSubDraft() {
    state.subFace = null;
    state.subWallet = "";
    state.subWalletSignature = "";
    var faceState = byId("idsub-face-state");
    if (faceState) faceState.textContent = "未采集";
    var walletState = byId("idsub-wallet-state");
    if (walletState) walletState.textContent = "未绑定（默认用主身份钱包）";
  }

  async function bindSubWallet() {
    var status = byId("idsub-wallet-state");
    try {
      var provider = walletProvider();
      if (!provider) { say(status, "没检测到钱包插件", false); return; }
      var accounts = await provider.request({ method: "eth_requestAccounts" });
      var addr = accounts && accounts[0];
      if (!addr) { say(status, "钱包没有返回地址", false); return; }
      say(status, "已选钱包 " + addr.slice(0, 6) + "…" + addr.slice(-4) + "（建卡时签名确认）", null);
      state.subWallet = addr;
      state.subWalletSignature = "";
    } catch (e) {
      say(status, "绑定失败：" + (e && (e.message || e) || e), false);
    }
  }

  async function signSubWalletFor(profileId) {
    if (!state.subWallet) return;
    var message = [
      "Karma Sub-Identity Wallet Bind",
      "profile_id:" + profileId,
      "owner_identity_id:" + identity(),
      "wallet_address:" + state.subWallet,
    ].join("\n");
    var provider = walletProvider();
    state.subWalletSignature = await provider.request({
      method: "personal_sign",
      params: [message, state.subWallet],
    });
  }

  // ---- 事件 ---------------------------------------------------------------

  function bind() {
    if (!byId("idv-master")) return;

    byId("idv-doc-front").addEventListener("change", async function (ev) {
      var f = ev.target.files && ev.target.files[0];
      if (!f) return;
      state.docFront = await fileToScaledB64(f);
      byId("idv-doc-state").textContent = "正面已就绪";
      thumb(byId("idv-doc-thumb"), state.docFront.b64);
      refreshSubmitState();
    });

    byId("idv-doc-back").addEventListener("change", async function (ev) {
      var f = ev.target.files && ev.target.files[0];
      if (!f) return;
      state.docBack = await fileToScaledB64(f);
      byId("idv-doc-state").textContent = "正反面已就绪";
      refreshSubmitState();
    });

    byId("idv-face-file").addEventListener("change", async function (ev) {
      var f = ev.target.files && ev.target.files[0];
      if (!f) return;
      state.face = await fileToScaledB64(f);
      // 走的是单张照片的兜底通道：复核方必须能看出来，所以这里如实打标。
      state.face.source = "photo";
      byId("idv-face-state").textContent = "单张照片已就绪（非多角度采集）";
      thumb(byId("idv-face-thumb"), state.face.b64);
      refreshSubmitState();
    });

    byId("idv-face-open").addEventListener("click", async function () {
      var status = byId("idv-face-state");
      var cap = window.KarmaFaceCapture;
      if (!cap) {
        status.textContent = "取景组件没加载，用下面「用照片」那张";
        return;
      }
      status.textContent = "正在刷脸…";
      var shot = await cap.open({ title: "刷脸认证", facing: "user" });
      if (!shot) {
        // 用户取消：别把他原来那张擦掉。
        status.textContent = state.face ? "照片已就绪" : "未采集";
        return;
      }
      state.face = shot;
      var got = (shot && shot.frames && shot.frames.length) || 0;
      status.textContent = got
        ? "刷脸已采集（" + got + " 个角度：正/左/右/抬/低）"
        : "刷脸已采集";
      thumb(byId("idv-face-thumb"), shot.b64);
      refreshSubmitState();
    });

    ["idv-name", "idv-doc-number", "idv-consent"].forEach(function (k) {
      byId(k).addEventListener("input", refreshSubmitState);
      byId(k).addEventListener("change", refreshSubmitState);
    });
    byId("idv-consent").addEventListener("change", function () {
      if (byId("idv-consent").checked) byId("idv-read-state").textContent = "已确认";
      refreshSubmitState();
    });

    byId("idv-submit").addEventListener("click", submitVerification);

    var pc = byId("idv-precheck");
    if (pc) {
      pc.addEventListener("click", function () {
        var run = (window.KarmaCert || {}).runPrecheck;
        if (!run) return say(byId("idv-status"), "自检组件没加载", false);
        run(
          "personal",
          {
            full_name: String((byId("idv-name") || {}).value || "").trim(),
            contact_email: String((byId("idv-email") || {}).value || "").trim(),
          },
          false,
          byId("idv-precheck-list"),
          byId("idv-status")
        );
      });
    }
    byId("idv-reset").addEventListener("click", function () {
      state.docFront = null;
      state.docBack = null;
      state.face = null;
      thumb(byId("idv-doc-thumb"), "");
      thumb(byId("idv-face-thumb"), "");
      byId("idv-doc-state").textContent = "未上传";
      byId("idv-face-state").textContent = "未采集";
      byId("idv-enc-state").textContent = "待加密";
      byId("idv-send-state").textContent = "待提交";
      say(byId("idv-status"), "—", null);
      refreshSubmitState();
    });

    byId("idsub-new").addEventListener("click", function () {
      permsNode();
      resetSubDraft();
      byId("idsub-form").hidden = false;
      byId("idsub-status").textContent = "—";
      syncSubRoute();
    });
    byId("idsub-cancel").addEventListener("click", function () {
      resetSubDraft();
      byId("idsub-form").hidden = true;
    });
    var idsubRole = byId("idsub-role");
    if (idsubRole) idsubRole.addEventListener("change", syncSubRoute);
    byId("idsub-goto-cert").addEventListener("click", function () {
      var route = SUB_ROUTE[(byId("idsub-role") || {}).value || "life"];
      if (route && window.cyberSwitchPage) window.cyberSwitchPage("identity", route.sub);
    });
    byId("idsub-wallet").addEventListener("click", bindSubWallet);
    byId("idsub-face").addEventListener("click", async function () {
      var status = byId("idsub-face-state");
      var cap = window.KarmaFaceCapture;
      if (!cap) return say(status, "取景组件没加载", false);
      var shot = await cap.open({ title: "子身份刷脸确认", facing: "user" });
      if (!shot) return say(status, "已取消", false);
      state.subFace = shot;
      say(status, "已采集", true);
    });
    byId("idsub-create").addEventListener("click", async function () {
      await createSub();
    });

    document.addEventListener("karma-wallet-connected", function () {
      renderMaster();
      loadVerification();
      loadMasterMoney();
      loadSubs();
    });
    document.addEventListener("karma-session-restored", function () {
      renderMaster();
      loadVerification();
      loadMasterMoney();
      loadSubs();
    });
    document.addEventListener("karma-alloc-changed", loadMasterMoney);

    refreshSubmitState();
    renderMaster();
    loadVerification();
    loadMasterMoney();
    loadSubs();
  }

  window.KarmaIdentityVerify = {
    refresh: function () {
      renderMaster();
      loadVerification();
      loadMasterMoney();
      loadSubs();
    },
    maskDocNumber: maskDocNumber,
    state: state,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind);
  } else {
    bind();
  }
})();
