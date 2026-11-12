/**
 * 会话续期心跳（apps/console/scripts/console-wallet-auth.js 的 reauth / checkSession）。
 *
 * 真机背景：SIWE 令牌只有 15 分钟。页面一直开着时它会在用户眼皮底下过期，而入口门禁
 * 只在事件上重算 —— 「过期」本身不产生事件，`ensureFreshToken` 导出了也没有调用方。
 * 结果就是：界面看着正常，点「生成接入包」却拿到英文 HTTP 401；「接入确认」那张卡
 * 因为同一条会话鉴权一直是空的，用户以为自己抄错了匹配码。
 *
 * 这条测试钉住心跳的三条规则：
 *   1. 过期但钱包还授权：**静默重签一次**（只多一次签名），拿到新令牌；
 *   2. 换了账号 / 钱包锁着：不替用户做主，关门（karma-session-expired）而不是硬签；
 *   3. 用户取消了签名：关门，而且**同一枚令牌只试一次** —— 不能每 30 秒弹一次钱包。
 *
 * 跑法：node tests/js/test_console_session_watch.cjs
 */
"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const SRC = path.resolve(__dirname, "..", "..", "apps", "console", "scripts", "console-wallet-auth.js");
const CODE = fs.readFileSync(SRC, "utf8");

let failures = 0;
let checks = 0;

function check(name, cond, extra) {
  checks += 1;
  if (cond) return;
  failures += 1;
  console.error("FAIL: " + name + (extra ? " — " + extra : ""));
}

function eq(name, actual, expected) {
  check(name, actual === expected, "expected " + JSON.stringify(expected) + ", got " + JSON.stringify(actual));
}

const WALLET = "0xAbCdEf0123456789";

function b64url(o) {
  return Buffer.from(JSON.stringify(o)).toString("base64").replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_");
}

/** 一枚只有 exp 的假 JWT —— 只被 jwtExpiry 用来判断「还剩多久」。 */
function jwt(expSeconds) {
  return b64url({ alg: "HS256" }) + "." + b64url({ exp: expSeconds }) + ".sig";
}

function makeEnv() {
  const store = new Map();
  const now = Math.floor(Date.now() / 1000);
  store.set("karma_console_wallet", WALLET);
  store.set("karma_console_identity", "kid-1");
  store.set("karma_console_wallet_name", "MetaMask");
  store.set("karma_console_access_token", jwt(now - 120)); // 过期两分钟
  store.set("karma_console_token_expires_at", String(Date.now() - 120000));

  const ctl = { mode: "locked", accountCalls: 0, signCalls: 0, events: [], intervals: 0 };

  const provider = {
    isMetaMask: true,
    request: async (args) => {
      const method = args && args.method;
      if (method === "eth_accounts") {
        ctl.accountCalls += 1;
        if (ctl.mode === "locked") throw new Error("wallet is locked");
        if (ctl.mode === "other") return ["0x9999888877776666"];
        return [WALLET];
      }
      if (method === "personal_sign") {
        ctl.signCalls += 1;
        if (ctl.mode === "reject") {
          const e = new Error("user rejected");
          e.code = 4001;
          throw e;
        }
        return "0xsig";
      }
      throw new Error("unsupported method " + method);
    },
  };

  function json(body) {
    return { ok: true, status: 200, statusText: "OK", text: () => Promise.resolve(JSON.stringify(body)) };
  }

  const sandbox = {
    console,
    setTimeout,
    clearTimeout,
    isFinite,
    Number,
    String,
    Object,
    Array,
    Error,
    Promise,
    JSON,
    Date,
    encodeURIComponent,
    decodeURIComponent,
    escape,
    unescape,
    atob: (s) => Buffer.from(s, "base64").toString("binary"),
    btoa: (s) => Buffer.from(s, "binary").toString("base64"),
    setInterval: () => {
      ctl.intervals += 1;
      return 1;
    },
    clearInterval: () => {},
    sessionStorage: {
      getItem: (k) => (store.has(k) ? store.get(k) : null),
      setItem: (k, v) => store.set(k, String(v)),
      removeItem: (k) => store.delete(k),
    },
    location: { protocol: "https:", hostname: "karma-network.ai", origin: "https://karma-network.ai" },
    navigator: { userAgent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)" },
    ethereum: provider,
    addEventListener: () => {},
    dispatchEvent: () => true,
    fetch: (url) => {
      if (String(url).indexOf("/v1/auth/siwe/challenge") >= 0) {
        return Promise.resolve(json({ nonce: "n1", message: "karma-network.ai wants you to sign in" }));
      }
      if (String(url).indexOf("/v1/auth/siwe/verify") >= 0) {
        return Promise.resolve(json({ access_token: jwt(Math.floor(Date.now() / 1000) + 900), identity_id: "kid-1" }));
      }
      return Promise.resolve(json({}));
    },
  };

  function Event2(name, init) {
    this.type = name;
    this.detail = init && init.detail;
  }
  const documentStub = {
    readyState: "complete",
    querySelectorAll: () => [],
    getElementById: () => null,
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: (ev) => {
      if (ev && ev.type) ctl.events.push(ev.type);
      return true;
    },
    body: { classList: { add: () => {}, remove: () => {}, contains: () => false } },
  };
  sandbox.Event = Event2;
  sandbox.CustomEvent = Event2;
  sandbox.document = documentStub;
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(CODE, sandbox, { filename: SRC });
  return { env: sandbox, ctl, store };
}

function expiredCount(ctl) {
  return ctl.events.filter((n) => n === "karma-session-expired").length;
}

function tick() {
  return new Promise((r) => setTimeout(r, 10));
}

(async function () {
  // 载入时（钱包锁着）不该发生任何签名 —— restore() 只提示，不打扰用户。
  {
    const { env, ctl } = makeEnv();
    await tick();
    eq("载入时钱包锁着：不签名", ctl.signCalls, 0);
    eq("载入时就装上了心跳", ctl.intervals, 1);
    check("载入时令牌还是过期的", env.KarmaWalletAuth.tokenState() !== "ok");
  }

  // 1) 过期但钱包还授权 → 静默重签一次，拿到新令牌，不关门
  {
    const { env, ctl, store } = makeEnv();
    await tick();
    const before = store.get("karma_console_access_token");
    ctl.mode = "ok";
    const out = await env.KarmaWalletAuth.checkSession();
    eq("心跳结果是 renewed", out, "renewed");
    eq("多了一次签名（就一次）", ctl.signCalls, 1);
    check("令牌换新了", store.get("karma_console_access_token") !== before);
    eq("新令牌是 ok", env.KarmaWalletAuth.tokenState(), "ok");
    eq("没有关门", expiredCount(ctl), 0);
  }

  // 2) 换了账号：不替用户做主，关门，且不弹签名
  {
    const { env, ctl } = makeEnv();
    await tick();
    ctl.mode = "other";
    eq("心跳结果是 expired", await env.KarmaWalletAuth.checkSession(), "expired");
    eq("一次签名都没有", ctl.signCalls, 0);
    eq("门关了一次", expiredCount(ctl), 1);
    eq("再跳一次还是 expired", await env.KarmaWalletAuth.checkSession(), "expired");
    eq("门不会再关第二次（不刷屏）", expiredCount(ctl), 1);
  }

  // 3) 用户取消签名：关门；同一枚令牌只试一次 —— 不能每 30 秒弹一次钱包
  {
    const { env, ctl } = makeEnv();
    await tick();
    ctl.mode = "reject";
    eq("心跳结果是 expired", await env.KarmaWalletAuth.checkSession(), "expired");
    eq("试过一次签名", ctl.signCalls, 1);
    eq("门关了一次", expiredCount(ctl), 1);
    await env.KarmaWalletAuth.checkSession();
    await env.KarmaWalletAuth.checkSession();
    eq("后续心跳不再弹钱包", ctl.signCalls, 1);
    eq("也不会重复关门", expiredCount(ctl), 1);
  }

  // 4) 会话好好的：心跳什么都不做
  {
    const { env, ctl, store } = makeEnv();
    await tick();
    store.set("karma_console_access_token", jwt(Math.floor(Date.now() / 1000) + 900));
    store.set("karma_console_token_expires_at", String(Date.now() + 900000));
    eq("心跳结果是 ok", await env.KarmaWalletAuth.checkSession(), "ok");
    eq("不签名", ctl.signCalls, 0);
    eq("不关门", expiredCount(ctl), 0);
  }

  if (failures) {
    console.error("FAILED " + failures + "/" + checks + " session-watch checks");
    process.exit(1);
  }
  console.log("ok  console session watch: " + checks + " checks passed");
})();