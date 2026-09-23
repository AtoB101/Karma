/**
 * 操作台 HTTP 客户端（apps/console/scripts/karma-public-api.js）的行为测试。
 *
 * 重点只有一条：**每次请求都必须有截止时间**。
 * 线上实测过一次 —— 用户把节点切到一台连不通的地址，操作台自己的数据请求
 * 全部发往那台机器并且永远不返回（十个请求挂了十几秒还在 pending），
 * 界面只能一直转圈：分不清是节点的问题还是自己网断了。
 * 有超时之后，这种情况会变成「一次明确的失败」——节点层也就有机会换一台。
 *
 * 跑法：node tests/js/test_console_fetch.cjs
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

function msleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

/** 一个「永远不返回、只在被中止时才拒绝」的 fetch —— 模拟连不通的节点。 */
function neverEndingFetch(log) {
  return function (url, opts) {
    if (log) log.calls.push({ url: url, opts: opts });
    return new Promise(function (_resolve, reject) {
      const sig = opts && opts.signal;
      if (!sig) return; // 没信号 = 永远挂着，正是要拦住的写法
      if (sig.aborted) {
        reject(new Error("aborted"));
        return;
      }
      sig.addEventListener("abort", function () {
        reject(new Error("aborted"));
      });
    });
  };
}

function makeEnv(opts) {
  const o = opts || {};
  const store = new Map();
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
    fetch: o.fetch || (() => Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve("{}") })),
  };
  if (o.timeoutMs !== undefined) sandbox.KARMA_FETCH_TIMEOUT_MS = o.timeoutMs;
  if (o.nodes) sandbox.KarmaNodes = o.nodes;
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(CODE, sandbox, { filename: SRC });
  return sandbox;
}

(async function testTimeoutAbortsAHungRequest() {
  const log = { calls: [] };
  const reported = [];
  const env = makeEnv({
    timeoutMs: 40,
    fetch: neverEndingFetch(log),
    nodes: { effectiveBase: () => "https://node.example.invalid", reportFailure: (b) => reported.push(b) },
  });
  const t0 = Date.now();
  let err = null;
  try {
    await env.cyberKarmaApi.karmaFetch("/v1/capacity/kid_x", { method: "GET" });
  } catch (e) {
    err = e;
  }
  const spent = Date.now() - t0;
  check("挂住的请求会被中止（不会一直转圈）", !!err, "没有抛错");
  check("在超时时间内就结束了", spent < 2000, spent + "ms");
  eq("请求带了中止信号", !!(log.calls[0] && log.calls[0].opts.signal), true);
  eq("请求地址用的是当前节点", log.calls[0] && log.calls[0].url, "https://node.example.invalid/v1/capacity/kid_x");
  eq("连不上会通知节点层（容灾才有机会接手）", reported[0], "https://node.example.invalid");
})();

(async function testHappyPathStillWorks() {
  const log = { calls: [] };
  const env = makeEnv({
    fetch: (url, opts) => {
      log.calls.push({ url, opts });
      return Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve('{"ok":true}') });
    },
  });
  const body = await env.cyberKarmaApi.karmaFetch("/health", { method: "GET" });
  eq("正常响应照常返回", body && body.ok, true);
  eq("同样带中止信号", !!log.calls[0].opts.signal, true);
})();

(async function testHttpErrorKeepsItsStatus() {
  const env = makeEnv({
    fetch: () => Promise.resolve({ ok: false, status: 403, statusText: "Forbidden", text: () => Promise.resolve('{"detail":"nope"}') }),
  });
  let err = null;
  try {
    await env.cyberKarmaApi.karmaFetch("/runtime/list-bound-keys", { method: "GET" });
  } catch (e) {
    err = e;
  }
  eq("HTTP 错误保留状态码（调用方要按码分流）", err && err.status, 403);
  check("错误信息里有原因", !!err && /nope/.test(err.message), err && err.message);
})();

(async function testCallerSignalIsNotOverridden() {
  const log = { calls: [] };
  const mine = new AbortController();
  const env = makeEnv({
    timeoutMs: 40,
    fetch: (url, opts) => {
      log.calls.push({ url, opts });
      return new Promise((resolve) => setTimeout(() => resolve({ ok: true, status: 200, text: () => Promise.resolve("{}") }), 5));
    },
  });
  await env.cyberKarmaApi.karmaFetch("/health", { method: "GET", signal: mine.signal });
  eq("调用方自己的 signal 不被覆盖", log.calls[0].opts.signal, mine.signal);
})();

(async function testNoReportWhenFetchIsFine() {
  const reported = [];
  const env = makeEnv({
    timeoutMs: 40,
    fetch: () => Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve("{}") }),
    nodes: { effectiveBase: () => "https://karma-network.ai", reportFailure: (b) => reported.push(b) },
  });
  await env.cyberKarmaApi.karmaFetch("/health", { method: "GET" });
  await msleep(60);
  eq("一切正常时不会误报节点故障", reported.length, 0);
})();

setTimeout(function () {
  if (failures) {
    console.error("\n" + failures + "/" + checks + " 项失败");
    process.exit(1);
  }
  console.log("ok  karma-public-api: " + checks + " checks passed");
}, 1200);
