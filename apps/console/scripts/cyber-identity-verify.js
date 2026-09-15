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
      return;
    }
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
    } catch (e) {
      if (badge) badge.textContent = "状态读取失败";
    }
  }

  // ---- 提交 ---------------------------------------------------------------

  function maskDocNumber(raw) {
    var digits = String(raw || "").replace(/[^0-9A-Za-z]/g, "");
    if (!digits) return "";
    if (digits.length <= 4) return "****" + digits;
    return "*".repeat(Math.min(12, digits.length - 4)) + digits.slice(-4);
  }

  function refreshSubmitState() {
    var ready =
      !!state.docFront &&
      !!state.face &&
      !!String(byId("idv-name").value || "").trim() &&
      !!String(byId("idv-doc-number").value || "").trim() &&
      byId("idv-consent").checked &&
      !!identity();
    // 已经交过（pending / verified）就不再放行：再点只会换回一个 409。
    var alreadySent = state.serverStatus === "pending" || state.serverStatus === "verified";
    byId("idv-submit").disabled = !ready || state.submitting || alreadySent;
  }

  async function submitVerification() {
    if (state.submitting) return;
    var status = byId("idv-status");
    var id = identity();
    if (!id) { say(status, "请先连接钱包", false); return; }

    state.submitting = true;
    refreshSubmitState();
    try {
      say(status, "① 证件就绪，② 正在本地加密…", null);
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
      faceDigest: await sha256Hex(new window.TextEncoder().encode(bundle.face_b64 || "")),
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
        var kyc = KYC_LABELS[p.kyc_status] || "未采集";
        var wallet = String(p.bound_wallet_address || "");
        var walletText = wallet
          ? (wallet.length > 12 ? wallet.slice(0, 6) + "…" + wallet.slice(-4) : wallet)
          : "未绑操作钱包";
        el.innerHTML =
          '<div class="idv-sub-main"><b>' + esc(title) + "</b>" +
          "<span>" + esc(label) + "</span></div>" +
          '<div class="idv-sub-meta">额度 ' + money(row ? row.allocated_credits : 0) + " USDC</div>" +
          '<div class="idv-sub-meta">人脸 ' + esc(kyc) + "</div>" +
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
        host.appendChild(el);
      });
    } catch (e) {
      host.textContent = "读取失败：" + (e && (e.message || e) || e);
    }
  }

  async function createSub() {
    var status = byId("idsub-status");
    var id = identity();
    if (!id) { say(status, "请先连接钱包", false); return; }
    var roleKey = byId("idsub-role").value;
    var role = ROLES[roleKey] || ROLES.life;
    var name = String(byId("idsub-name").value || "").trim() || role.label;
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
      var created = await api().createRoleProfile({
        owner_identity_id: id,
        "class": role.klass,
        display_name: name,
      });
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

      if (state.subFace) {
        say(status, "⑤ 提交人脸确认…", null);
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

      say(status, "✅ 子身份已建立：" + name, true);
      await finishSub(status);
    } catch (e) {
      say(status, "建立失败：" + (e && (e.message || e.detail) || e), false);
    }
  }

  async function finishSub() {
    resetSubDraft();
    byId("idsub-form").hidden = true;
    ["idsub-name", "idsub-amount", "idsub-single", "idsub-daily"].forEach(function (k) {
      var n = byId(k);
      if (n) n.value = "";
    });
    byId("idsub-ack").checked = false;
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
      byId("idv-face-state").textContent = "照片已就绪";
      thumb(byId("idv-face-thumb"), state.face.b64);
      refreshSubmitState();
    });

    byId("idv-face-open").addEventListener("click", async function () {
      var status = byId("idv-face-state");
      var cap = window.KarmaFaceCapture;
      if (!cap) {
        status.textContent = "取景组件没加载，用「用照片」那张";
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
      status.textContent = "刷脸已采集";
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
    });
    byId("idsub-cancel").addEventListener("click", function () {
      resetSubDraft();
      byId("idsub-form").hidden = true;
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
