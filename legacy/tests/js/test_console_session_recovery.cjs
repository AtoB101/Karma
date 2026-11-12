/**
 * 会话过期时的自愈（apps/console/scripts/karma-public-api.js）。
 *
 * 真机背景：SIWE 令牌只有 15 分钟，页面一直开着就会过期 —— 入口门禁只在事件上重算，
 * 「过期」这件事本身不产生事件。用户点「生成接入包」时看到的是最后那句英文
 *   HTTP 401: Authentication required
 * 而同一时刻「接入确认」那张卡也是空的（同一条会话鉴权），于是他以为是自己抄错了匹配码。
 *
 * 这条测试钉住自愈的四条规则：
 *   1. 会话类失败（401 / 403 且 detail 说的是 authentication required）：静默重签一次
 *      + 把请求原样重放一遍（带新令牌）；
 *   2. 续不上：把门重新关上（markExpired 一次）并照原样抛出；
 *   3. 只重放一次 —— 重放再失败不再重放（不会有循环）；
 *   4. 不是会话类的 4xx（例如 agent_id must match agent_binding）一次都不重试；
 *      从来没连过钱包的访客也不触发重签（那不是「过期」）。
 *
 * 跑法：node tests/js/test_console_session_recovery.cjs
 */
"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const SRC = path.resolve(__dirname, "..", "..", "apps", "console", "scripts", "karma-public-api.js");
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

/** 人话直接从源码里取，别在测试里抄一份（抄的那份迟早和实现走散）。 */
function hintFor(needle) {
  const rows = CODE.split(/\r?\n/);
  for (let i = 0; i < rows.length; i += 1) {
    if (rows[i].indexOf(needle) >= 0) {
      for (let j = i; j < Math.min(rows.length, i + 4); j += 1) {
        const m = /hint:\s*"((?:[^"\\]|\\.)*)"/.exec(rows[j]);
        if (m) return m[1];
      }
    }
  }
  return "";
}

let SESSION_HINT = "";

function jsonResponse(status, body) {
  return {
    ok: status >= 200 && status < 300,
    status: status,
    statusText: "x",
    text: () => Promise.resolve(JSON.stringify(body)),
  };
}

/**
 * 一个假 fetch：按「第几次调用」给答复。每一次都记下 Authorization，便于断言重放带的是新令牌。
 * answers: [{status, body}, ...]；用完就用最后一个。
 */
function scriptedFetch(log, answers) {
  return function (url, opts) {
    const headers = (opts && opts.headers) || {};
    log.calls.push({
      url: url,
      auth: headers["Authorization"] || headers["authorization"] || "",
    });
    const a = answers[Math.min(log.calls.length - 1, answers.length - 1)];
    return Promise.resolve(jsonResponse(a.status, a.body));
  };
}

function makeEnv(opts) {
  const o = opts || {};
  const store = new Map();
  const log = { calls: [], reauth: 0, expired: 0 };
  const session = o.session === undefined ? { wallet: "0xAbC", accessToken: "old-token" } : o.session;
  const sandbox = {
    console,
    setTimeout,
    clearTimeout,
    isFinite,
    Number,
    String,
    Object,
    Error,
    Promise,
    JSON,
    Date,
    AbortController,
    AbortSignal,
    sessionStorage: {
      getItem: (k) => (store.has(k) ? store.get(k) : null),
      setItem: (k, v) => store.set(k, String(v)),
      removeItem: (k) => store.delete(k),
    },
    location: { hostname: "karma-network.ai", origin: "https://karma-network.ai" },
    fetch: scriptedFetch(log, o.answers || [{ status: 200, body: { ok: true } }]),
  };
  if (session) {
    sandbox.KARMA_ACCESS_TOKEN = session.accessToken || "";
    sandbox.KARMA_IDENTITY_ID = session.identityId || "kid-1";
  }
  if (o.walletAuth !== null) {
    sandbox.KarmaWalletAuth = Object.assign(
      {
        readSession: () => session,
        reauth: async () => {
          log.reauth += 1;
          return !!o.reauthOk;
        },
        markExpired: () => {
          log.expired += 1;
        },
      },
      o.walletAuth || {}
    );
  }
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(CODE, sandbox, { filename: SRC });
  return { env: sandbox, log };
}

async function call(env) {
  try {
    const body = await env.karmaRuntimeApi.runtimeCreateKey({ wallet_address: "0xAbC" });
    return { body: body, err: null };
  } catch (e) {
    return { body: null, err: e };
  }
}

function authAfterReauth(env) {
  env.KARMA_ACCESS_TOKEN = "new-token";
}

(async function () {
  SESSION_HINT = hintFor("Authentication required");

  // 1) 401 → 静默重签一次 → 带新令牌重放 → 成功
  {
    const { env, log } = makeEnv({
      answers: [{ status: 401, body: { detail: "Authentication required" } }, { status: 200, body: { key_id: "k1" } }],
      reauthOk: true,
    });
    env.KarmaWalletAuth.reauth = async () => {
      log.reauth += 1;
      authAfterReauth(env);
      return true;
    };
    const r = await call(env);
    eq("续签成功后这次调用真的成功了", r.body && r.body.key_id, "k1");
    eq("只重签一次", log.reauth, 1);
    eq("发了两次请求（原 + 重放）", log.calls.length, 2);
    eq("重放带的是新令牌", log.calls[1].auth, "Bearer new-token");
  }

  // 2) 401 → 续不上 → 关门 + 原样抛出（带人话）
  {
    const { env, log } = makeEnv({
      answers: [{ status: 401, body: { detail: "Authentication required" } }],
      reauthOk: false,
    });
    const r = await call(env);
    eq("续不上就抛出", !!r.err, true);
    eq("状态码照旧", r.err && r.err.status, 401);
    eq("给用户的是人话", r.err && r.err.message, SESSION_HINT);
    check("人话不是英文原文", !!r.err && r.err.message.indexOf("Authentication required") < 0, r.err && r.err.message);
    eq("原文留在 err.detail", r.err && r.err.detail, "Authentication required");
    eq("只重签一次", log.reauth, 1);
    eq("没有重放（续不上）", log.calls.length, 1);
    eq("把门重新关上一次", log.expired, 1);
  }

  // 3) 不会循环：重放还是 401，就停在那里
  {
    const { env, log } = makeEnv({
      answers: [{ status: 401, body: { detail: "Authentication required" } }],
      reauthOk: true,
    });
    const r = await call(env);
    eq("重放再失败就抛出", !!r.err, true);
    eq("一共只发了两次请求（没有第三次）", log.calls.length, 2);
    eq("也只重签了一次", log.reauth, 1);
  }

  // 4) 非会话类的 403（两个字段写岔了）：一次都不重试
  {
    const { env, log } = makeEnv({
      answers: [{ status: 403, body: { detail: "agent_id must match agent_binding" } }],
      reauthOk: true,
    });
    const r = await call(env);
    eq("抛出", !!r.err, true);
    eq("没有重签", log.reauth, 0);
    eq("没有重放", log.calls.length, 1);
    eq("没有关门", log.expired, 0);
  }

  // 5) 会话类 403，但从来没连过钱包：不重签、不关门（各模块自己提示去连钱包）
  {
    const { env, log } = makeEnv({
      answers: [{ status: 403, body: { detail: "authentication required: connect a wallet first" } }],
      reauthOk: true,
      session: { wallet: "", accessToken: "" },
    });
    const r = await call(env);
    eq("抛出", !!r.err, true);
    eq("访客不触发重签", log.reauth, 0);
    eq("访客不关门（他本来就在门口）", log.expired, 0);
    eq("只发一次", log.calls.length, 1);
  }

  // 6) 没有钱包模块时保持原样
  {
    const { env, log } = makeEnv({
      answers: [{ status: 401, body: { detail: "Authentication required" } }],
      walletAuth: null,
    });
    const r = await call(env);
    eq("照旧抛出", !!r.err, true);
    eq("一次请求", log.calls.length, 1);
  }

  if (failures) {
    console.error("FAILED " + failures + "/" + checks + " session-recovery checks");
    process.exit(1);
  }
  console.log("ok  console session recovery: " + checks + " checks passed");
})();