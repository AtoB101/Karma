/**
 * 主体认证留底包 —— 操作台解不解得开（apps/console/scripts/cyber-face-vault.js 的 openVerificationPackage）。
 *
 * 为什么要有这支：加子身份时的参考脸有两个出处，第二个就是主体认证（证件 + 刷脸）那一次
 * 留下的密文包。那份包是**在浏览器里**加密的（密钥由钱包签名派生），服务端自己解不开，
 * 所以「解不解得开」只能在真代码上验。这里按提交那一侧的约定封一份包，再让保险柜去解：
 *
 *   1. 出得来：角度帧和 face_digest 原样拿回；
 *   2. 换一把签名（不是本人）→ 解不开，而且要说人话；
 *   3. 包不是本人钱包封的（key_wrap 不对）→ 直接拒，别白弹一次钱包签名；
 *   4. 没有留底包 → 说「先给主身份留一张脸」。
 *
 * 跑法：node tests/js/test_console_face_package.cjs
 */
"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(__dirname, "..", "..");
const SRC = path.join(ROOT, "apps", "console", "scripts", "cyber-face-vault.js");

const ID = "kid_5f0aa8ccf7483983a8a2a5a9";
const WALLET = "0x5acc51116f66b84802c8321f286d09014a78346f";
const SALT_HEX = "3f2ac9d1b47e805c6a1d9e37f0b2548a";
const ITERATIONS = 100000;
const SIGNATURE = "0x" + "ab".repeat(65);
const OTHER_SIGNATURE = "0x" + "cd".repeat(65);
const FACE_DIGEST = "9f".repeat(32);
const BUNDLE = {
  v: 1,
  identity_id: ID,
  face_b64: "front-image",
  face_mime: "image/jpeg",
  face_frames: [
    { angle: "front", label: "正面", mime: "image/jpeg", b64: "front-image" },
    { angle: "left", label: "向左转", mime: "image/jpeg", b64: "left-image" },
  ],
};
let failures = 0;
let checks = 0;

function check(name, cond, extra) {
  checks += 1;
  if (cond) return;
  failures += 1;
  console.error("FAIL: " + name + (extra === undefined ? "" : " -> " + JSON.stringify(extra).slice(0, 300)));
}

function b64(buf) {
  return Buffer.from(new Uint8Array(buf)).toString("base64");
}

/** 按提交那一侧的约定封一份包：PBKDF2(签名原文, 盐 = salt hex 文本) → AES-GCM-256。 */
async function seal(bundle, signature, saltHex) {
  const te = new TextEncoder();
  const material = await crypto.subtle.importKey(
    "raw", te.encode(signature), { name: "PBKDF2" }, false, ["deriveKey"]
  );
  const key = await crypto.subtle.deriveKey(
    { name: "PBKDF2", salt: te.encode(saltHex), iterations: ITERATIONS, hash: "SHA-256" },
    material,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt"]
  );
  const iv = new Uint8Array(12).fill(7);
  const cipher = await crypto.subtle.encrypt({ name: "AES-GCM", iv: iv }, key, te.encode(JSON.stringify(bundle)));
  return {
    identity_id: ID,
    has_package: true,
    status: "verified",
    face_digest: FACE_DIGEST,
    package_cipher: b64(cipher),
    encryption: {
      algo: "AES-GCM-256",
      kdf: "PBKDF2-SHA256",
      iterations: ITERATIONS,
      salt_b64: Buffer.from(saltHex, "utf8").toString("base64"),
      iv_b64: b64(iv),
      key_wrap: "wallet-signature-v1",
    },
  };
}

/** 起一个假的钱包 + 假的 api，把刷脸保险柜真跑起来。 */
function boot(signature) {
  const provider = {
    request: async function (payload) {
      if (payload && payload.method === "personal_sign") return signature;
      throw new Error("unexpected method " + JSON.stringify(payload));
    },
  };
  const win = {
    KARMA_IDENTITY_ID: ID,
    CYBER_I18N: undefined,
    crypto: crypto,
    TextEncoder: TextEncoder,
    TextDecoder: TextDecoder,
    btoa: function (s) { return Buffer.from(String(s), "binary").toString("base64"); },
    atob: function (s) { return Buffer.from(String(s), "base64").toString("binary"); },
    KarmaWalletAuth: {
      activeProvider: function () { return provider; },
      readSession: function () { return { wallet: WALLET }; },
    },
  };
  const sandbox = { window: win, console: console, setTimeout: setTimeout };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(SRC, "utf8"), sandbox, { filename: SRC });
  return win.KarmaFaceVault;
}

async function main() {
  {
    const vault = boot(SIGNATURE);
    const sealed = await seal(BUNDLE, SIGNATURE, SALT_HEX);

    // ---- 1. 本人解得开 ------------------------------------------------------
    const opened = await vault.openVerificationPackage(sealed);
    check("角度帧原样拿回", JSON.stringify(opened.bundle.face_frames) === JSON.stringify(BUNDLE.face_frames), opened.bundle);
    check("正面那张也在", opened.bundle.face_b64 === "front-image", opened.bundle.face_b64);
    check("face_digest 原样带出（拿它当 reference_digest）", opened.faceDigest === FACE_DIGEST, opened.faceDigest);
    check("加密参数一并带出（服务端按同一套白名单校验）", opened.encryption.salt_b64 === sealed.encryption.salt_b64);

    // ---- 2. 换一把签名：解不开，要说人话 ------------------------------------
    const stranger = boot(OTHER_SIGNATURE);
    let why = "";
    try {
      await stranger.openVerificationPackage(sealed);
    } catch (e) {
      why = String((e && e.message) || e);
    }
    check("别人解不开", why.indexOf("解不开") >= 0, why);
  }

  // ---- 3. 包不是本人钱包封的 ----------------------------------------------
  {
    const vault = boot(SIGNATURE);
    const sealed = await seal(BUNDLE, SIGNATURE, SALT_HEX);
    sealed.encryption = Object.assign({}, sealed.encryption, { key_wrap: "operator-passphrase-v1" });
    let why = "";
    try {
      await vault.openVerificationPackage(sealed);
    } catch (e) {
      why = String((e && e.message) || e);
    }
    check("非本人密钥封的包直接拒", why.indexOf("解不开") >= 0, why);
  }

  // ---- 4. 根本没有留底包 --------------------------------------------------
  {
    const vault = boot(SIGNATURE);
    let why = "";
    try {
      await vault.openVerificationPackage({ has_package: false, face_digest: null, encryption: {} });
    } catch (e) {
      why = String((e && e.message) || e);
    }
    check("没有留底包要说清先去留一张脸", why.indexOf("还没有刷脸模板") >= 0, why);
  }

  // ---- 5. 密钥原文只有一处出处：提交那一侧逐字相同 ----------------------
  {
    const verifyJs = fs.readFileSync(path.join(ROOT, "apps", "console", "scripts", "cyber-identity-verify.js"), "utf8");
    const vaultJs = fs.readFileSync(SRC, "utf8");
    for (const line of ["Karma Identity Doc Key v1", "karma_identity_id:", "salt:"]) {
      check("提交那一侧有密钥原文 " + line, verifyJs.indexOf('"' + line + '"') >= 0, line);
      check("保险柜这一侧有密钥原文 " + line, vaultJs.indexOf('"' + line + '"') >= 0, line);
    }
    check("KEY_MESSAGE 里的身份是同一处取的（window.KARMA_IDENTITY_ID）", vaultJs.indexOf("identity()") >= 0);
  }

  console.log((failures ? "FAILED " : "ok  ") + "console face package: " + (checks - failures) + "/" + checks + " checks passed");
  process.exit(failures ? 1 : 0);
}

main().catch(function (e) {
  console.error(e);
  process.exit(2);
});
