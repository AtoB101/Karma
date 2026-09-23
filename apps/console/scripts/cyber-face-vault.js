/**
 * 操作台 · 刷脸保险柜（KarmaFaceVault）
 * ====================================
 *
 * 两件事，一个原理：
 *
 *   1. **主身份刷脸即激活** —— 刷一次脸（活体 + 多角度），在本机把采集到的几张图
 *      压成一个固定尺寸的**脸型描述子**（32×32 灰度、去均值除标准差），用钱包签名
 *      派生的密钥加密后连同摘要交上去；服务端复核签名与采集证据，直接置为已激活。
 *   2. **追加身份（第二张卡）** —— 填完标准字段再刷一次脸，本机把这个描述子与
 *      **首次激活留下的那份**比一个相似度（NCC）出来；分数过线 + 签名对得上 +
 *      参考模板一致 + 不是重放，服务端就自动开通这张卡，不进复核队列。
 *
 * 三条纪律
 * --------
 * * **明文不出这台设备**：描述子是「这张脸长什么样」的粗粒度数值，不是照片；
 *   而且它也是加密后才上传的（AES-GCM-256）。密钥来自钱包签名，Karma 没有私钥，
 *   复现不出这把密钥 —— 服务端拿到的是密文与摘要。
 * * **签名原文只有一个出处**：Python 侧 services/face_activation.py 也拼一份，
 *   两边逐字一致才行（单元测试拿本文件里的字符串做尺子）。
 * * **判严不判宽**：分数不够就让人重采一次（或者走服务商通道），绝不放过去。
 *
 * 边界：本机比对挡的是「拿别人的脸来加身份」和「拿旧采集重放」。控制浏览器的攻击者
 * 可以伪造分数 —— 那一层由钱包签名（他签不了）与交易风控兜；接了第三方实名 / 活体
 * 服务商之后这条路会自动换成服务商的 1:1 比对。
 */
(function (global) {
  "use strict";

  var TEMPLATE_SIZE = 32;
  var TEMPLATE_VERSION = 1;
  var ALGORITHM = "KFC-GRAY32-NCC-v1";
  var KDF_ITERATIONS = 250000;
  //: 中心裁切比例：取最短边的这个比例做一个正方形（采集时人已经被圈在正中间）。
  var CROP_RATIO = 0.62;
  var MIN_STD = 3.0; // 一片死白 / 死黑的图没有可比性

  var state = { key: null, keyIdentity: "" };

  function api() { return global.cyberKarmaApi; }
  function identity() { return String(global.KARMA_IDENTITY_ID || "").trim(); }
  function T(zh) {
    var t = global.CYBER_I18N;
    return t && t.T ? t.T(zh) : zh;
  }

  function bufToB64(buf) {
    var bytes = new Uint8Array(buf);
    var out = "";
    for (var i = 0; i < bytes.length; i += 1) out += String.fromCharCode(bytes[i]);
    return global.btoa(out);
  }

  function b64ToBuf(b64) {
    var raw = global.atob(String(b64 || ""));
    var bytes = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i += 1) bytes[i] = raw.charCodeAt(i);
    return bytes;
  }

  function sha256Hex(buf) {
    return global.crypto.subtle.digest("SHA-256", buf).then(hexOf);
  }

  function hexOf(buffer) {
    var bytes = new Uint8Array(buffer);
    var out = "";
    for (var i = 0; i < bytes.length; i += 1) out += ("0" + bytes[i].toString(16)).slice(-2);
    return out;
  }

  function utf8(text) {
    return new global.TextEncoder().encode(String(text));
  }

  function hexToBytes(hex) {
    var clean = String(hex || "");
    var out = new Uint8Array(Math.floor(clean.length / 2));
    for (var i = 0; i < out.length; i += 1) out[i] = parseInt(clean.substr(i * 2, 2), 16);
    return out;
  }

  function walletProvider() {
    var auth = global.KarmaWalletAuth;
    if (auth && typeof auth.activeProvider === "function") {
      var p = auth.activeProvider();
      if (p && typeof p.request === "function") return p;
    }
    if (global.ethereum && typeof global.ethereum.request === "function") return global.ethereum;
    return null;
  }

  function sessionWallet() {
    var auth = global.KarmaWalletAuth;
    if (auth && typeof auth.readSession === "function") {
      var s = auth.readSession();
      if (s && s.wallet) return String(s.wallet);
    }
    return "";
  }

  async function sign(message) {
    var provider = walletProvider();
    var addr = sessionWallet();
    if (!provider || !addr) throw new Error(T("请先连接钱包（右上角「连接钱包」）"));
    return provider.request({ method: "personal_sign", params: [message, addr] });
  }

  /* ------------------------------------------------------------------ 签名原文 */

  function buildActivationMessage(p) {
    return [
      "Karma Face Activation v1",
      "identity_id:" + p.identityId,
      "wallet_address:" + p.walletAddress,
      "capture_digest:" + p.captureDigest,
      "template_digest:" + p.templateDigest,
    ].join("\n");
  }

  function buildConsistencyMessage(p) {
    return [
      "Karma Face Consistency v1",
      "owner_identity_id:" + p.ownerIdentityId,
      "profile_id:" + p.profileId,
      "class:" + p.className,
      "wallet_address:" + p.walletAddress,
      "reference_digest:" + p.referenceDigest,
      "capture_digest:" + p.captureDigest,
      "score:" + Number(p.score).toFixed(4),
    ].join("\n");
  }

  function keyMessage() {
    return ["Karma Identity Face Key v1", "karma_identity_id:" + identity()].join("\n");
  }

  /* ------------------------------------------------------------------ 密钥 */

  function kdfSalt() {
    // 固定盐 + 身份 id：换台设备也能解出同一份模板（密钥仍然只在钱包手里）。
    return sha256Hex(utf8("karma-face-template-v1:" + identity()));
  }

  async function deriveKey(signature, saltHex) {
    var sig = String(signature || "").replace(/^0x/, "");
    var base = await global.crypto.subtle.importKey(
      "raw", utf8(sig), { name: "PBKDF2" }, false, ["deriveKey"]
    );
    return global.crypto.subtle.deriveKey(
      { name: "PBKDF2", salt: hexToBytes(saltHex), iterations: KDF_ITERATIONS, hash: "SHA-256" },
      base,
      { name: "AES-GCM", length: 256 },
      false,
      ["encrypt", "decrypt"]
    );
  }

  /** 拿到这次的加密密钥：优先用会话里已经解出来的那把，避免重复弹钱包。 */
  async function ensureKey() {
    if (state.key && state.keyIdentity === identity()) return state.key;
    var salt = await kdfSalt();
    var signature = await sign(keyMessage());
    var key = await deriveKey(signature, salt);
    state.key = key;
    state.keyIdentity = identity();
    return key;
  }

  function resetKey() {
    state.key = null;
    state.keyIdentity = "";
  }

  function hasKey() {
    return !!(state.key && state.keyIdentity === identity());
  }

  /* ------------------------------------------------------------------ 模板 */

  function imageFromB64(b64) {
    return new Promise(function (resolve, reject) {
      var img = new global.Image();
      img.onload = function () { resolve(img); };
      img.onerror = function () { reject(new Error(T("这张图读不出来，重采一次吧"))); };
      img.src = "data:image/jpeg;base64," + b64;
    });
  }

  /** 中心裁切 → 32×32 灰度 → 去均值 / 除标准差。返回 {v,size,gray,std}。 */
  function grayFromImage(img) {
    var side = Math.max(8, Math.round(Math.min(img.width, img.height) * CROP_RATIO));
    var sx = Math.round((img.width - side) / 2);
    var sy = Math.round((img.height - side) / 2);
    var canvas = global.document.createElement("canvas");
    canvas.width = TEMPLATE_SIZE;
    canvas.height = TEMPLATE_SIZE;
    var ctx = canvas.getContext("2d");
    ctx.drawImage(img, sx, sy, side, side, 0, 0, TEMPLATE_SIZE, TEMPLATE_SIZE);
    var data = ctx.getImageData(0, 0, TEMPLATE_SIZE, TEMPLATE_SIZE).data;
    var gray = new Array(TEMPLATE_SIZE * TEMPLATE_SIZE);
    var sum = 0;
    for (var i = 0; i < gray.length; i += 1) {
      var o = i * 4;
      var v = 0.299 * data[o] + 0.587 * data[o + 1] + 0.114 * data[o + 2];
      gray[i] = v;
      sum += v;
    }
    var mean = sum / gray.length;
    var acc = 0;
    for (var j = 0; j < gray.length; j += 1) {
      gray[j] -= mean;
      acc += gray[j] * gray[j];
    }
    var std = Math.sqrt(acc / gray.length);
    return { v: TEMPLATE_VERSION, size: TEMPLATE_SIZE, gray: gray, std: std };
  }

  function roundGray(template) {
    // 存 1 位小数：够比，也不至于让密文包变大。
    return {
      v: template.v,
      size: template.size,
      gray: template.gray.map(function (x) { return Math.round(x * 10) / 10; }),
    };
  }

  /** 一次采集里的每一张（正面 + 四个角度）都做一个模板，取最清晰的那张当主模板。 */
  async function buildTemplate(capture) {
    var frames = (capture && capture.frames) || [];
    if (!frames.length && capture && capture.b64) {
      frames = [{ b64: capture.b64, angle: "front" }];
    }
    var best = null;
    for (var i = 0; i < frames.length; i += 1) {
      if (!frames[i] || !frames[i].b64) continue;
      var img = await imageFromB64(frames[i].b64);
      var t = grayFromImage(img);
      // 死白 / 死黑的帧没有可比性，直接不算数；剩下的里挑对比度最高的那张当主模板。
      if (t.std < MIN_STD) continue;
      if (!best || t.std > best.std) best = t;
    }
    if (!best) throw new Error(T("画面太糊或者太暗，换个亮点的地方重采一次"));
    return best;
  }

  function normalize(template) {
    var gray = template.gray || [];
    var sum = 0;
    for (var i = 0; i < gray.length; i += 1) sum += gray[i];
    var mean = sum / (gray.length || 1);
    var c = new Array(gray.length);
    var acc = 0;
    for (var j = 0; j < gray.length; j += 1) {
      c[j] = gray[j] - mean;
      acc += c[j] * c[j];
    }
    var norm = Math.sqrt(acc) || 1;
    for (var k = 0; k < c.length; k += 1) c[k] /= norm;
    return c;
  }

  /** 归一化互相关：-1 ~ 1，越大越像。同一张脸通常明显高于不同的人。 */
  function compare(a, b) {
    if (!a || !b || !a.gray || !b.gray || a.gray.length !== b.gray.length) return 0;
    var na = normalize(a);
    var nb = normalize(b);
    var dot = 0;
    for (var i = 0; i < na.length; i += 1) dot += na[i] * nb[i];
    return Math.max(0, Math.min(1, dot));
  }

  function livenessOf(capture) {
    var frames = (capture && capture.frames) || [];
    var challenges = [];
    for (var i = 0; i < frames.length; i += 1) {
      var key = String((frames[i] && frames[i].angle) || "").trim();
      if (key) challenges.push(key);
    }
    return {
      angles: challenges.length || (capture && capture.source === "photo" ? 1 : 0),
      frames: frames.length,
      source: (capture && capture.source) || "camera",
      challenges: challenges,
      motion: 0,
    };
  }

  async function digestOfCapture(capture) {
    // 采集指纹 = 每一帧的 sha256 串起来再 sha256：换一次采集就换一个值（挡重放）。
    var frames = (capture && capture.frames) || [];
    var parts = [];
    for (var i = 0; i < frames.length; i += 1) {
      if (frames[i] && frames[i].b64) parts.push(await sha256Hex(utf8(frames[i].b64)));
    }
    if (!parts.length && capture && capture.b64) parts.push(await sha256Hex(utf8(capture.b64)));
    return sha256Hex(utf8(parts.join("|")));
  }

  /* ------------------------------------------------------------------ 加解密 */

  async function encryptTemplate(template) {
    var key = await ensureKey();
    var iv = new Uint8Array(12);
    global.crypto.getRandomValues(iv);
    var salt = await kdfSalt();
    var plain = utf8(JSON.stringify(template));
    var cipher = await global.crypto.subtle.encrypt({ name: "AES-GCM", iv: iv }, key, plain);
    return {
      cipher: bufToB64(cipher),
      templateDigest: await sha256Hex(plain),
      encryption: {
        algo: "AES-GCM-256",
        kdf: "PBKDF2-SHA256",
        iterations: KDF_ITERATIONS,
        salt_b64: salt,
        iv_b64: bufToB64(iv),
        key_wrap: "wallet-signature-v1",
      },
    };
  }

  async function decryptTemplate(b64, encryption) {
    var key = await ensureKey();
    var iv = b64ToBuf((encryption && encryption.iv_b64) || "");
    var plain = await global.crypto.subtle.decrypt(
      { name: "AES-GCM", iv: iv }, key, b64ToBuf(b64)
    );
    return JSON.parse(new global.TextDecoder().decode(plain));
  }

  async function capture() {
    var mod = global.KarmaFaceCapture;
    if (!mod || typeof mod.open !== "function") throw new Error(T("刷脸模块未加载，请刷新页面后再试。"));
    if (!mod.supported()) throw new Error(T("这台设备打不开摄像头，换一台再试。"));
    return mod.open({
      title: T("刷脸认证"),
      subtitle: T(
        "把脸放进圆圈里：<b>头顶和下巴都要在圈内</b>。照屏幕上的提示转头就行 —— <b>不用按键，系统会自己拍</b>。一共 <b>正脸 + 左右侧脸 + 抬头低头 5 个角度</b>，照片只留在这台设备上。"
      ),
    });
  }

  /* ------------------------------------------------------------------ 对外动作 */

  /** 主身份：刷脸即激活。返回服务端的判定。 */
  async function activateByFace(identityId) {
    var id = String(identityId || identity()).trim();
    var shot = await capture();
    if (!shot) return null; // 用户取消
    var template = await buildTemplate(shot);
    var captureDigest = await digestOfCapture(shot);
    var packed = await encryptTemplate(roundGray(template));
    var wallet = sessionWallet();
    var message = buildActivationMessage({
      identityId: id,
      walletAddress: wallet,
      captureDigest: captureDigest,
      templateDigest: packed.templateDigest,
    });
    var signature = await sign(message);
    return api().submitFaceActivation(id, {
      wallet_address: wallet,
      wallet_signature: signature,
      capture_digest: captureDigest,
      template_digest: packed.templateDigest,
      template_cipher: packed.cipher,
      algorithm: ALGORITHM,
      encryption: packed.encryption,
      liveness: livenessOf(shot),
    });
  }

  /**
   * 追加身份：再刷一次脸，跟首次留下的模板比一个分数。
   * 返回 {score, threshold, verdict}；不出结果（取消 / 没模板）返回 null。
   */
  async function confirmSamePerson(profileId, className) {
    var mod = api();
    var id = identity();
    var stored = await mod.getFaceTemplate(id);
    if (!stored || !stored.enrolled) {
      throw new Error(T("这个身份还没有刷脸模板：先把主身份刷脸激活，再来加身份。"));
    }
    var reference = await decryptTemplate(stored.template_cipher, stored.encryption);

    var shot = await capture();
    if (!shot) return null;
    var fresh = await buildTemplate(shot);
    var score = compare(reference, fresh);
    var captureDigest = await digestOfCapture(shot);
    var wallet = sessionWallet();
    var message = buildConsistencyMessage({
      ownerIdentityId: id,
      profileId: profileId,
      className: className,
      walletAddress: wallet,
      referenceDigest: stored.template_digest,
      captureDigest: captureDigest,
      score: score,
    });
    var signature = await sign(message);
    var verdict = await mod.confirmFaceConsistency(profileId, {
      wallet_address: wallet,
      wallet_signature: signature,
      reference_digest: stored.template_digest,
      capture_digest: captureDigest,
      score: score,
      liveness: livenessOf(shot),
      // 不刷新模板（只比对）：这里回填首次绑定时的加密参数，服务端仍然按同一套白名单校验。
      encryption: stored.encryption || {},
    });
    return { score: score, verdict: verdict, template: stored };
  }

  global.KarmaFaceVault = {
    ALGORITHM: ALGORITHM,
    TEMPLATE_SIZE: TEMPLATE_SIZE,
    activateByFace: activateByFace,
    buildActivationMessage: buildActivationMessage,
    buildConsistencyMessage: buildConsistencyMessage,
    buildTemplate: buildTemplate,
    capture: capture,
    compare: compare,
    confirmSamePerson: confirmSamePerson,
    decryptTemplate: decryptTemplate,
    digestOfCapture: digestOfCapture,
    ensureKey: ensureKey,
    grayFromImage: grayFromImage,
    hasKey: hasKey,
    keyMessage: keyMessage,
    livenessOf: livenessOf,
    resetKey: resetKey,
    sign: sign,
    supported: function () {
      return !!(global.crypto && global.crypto.subtle) && !!(global.KarmaFaceCapture && global.KarmaFaceCapture.supported());
    },
  };
})(window);
