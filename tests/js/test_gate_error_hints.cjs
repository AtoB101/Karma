/**
 * 服务端闸门的英文 detail → 用户看到的人话（apps/console/scripts/karma-public-api.js）。
 *
 * 真机踩过：在操作台点「生成」，屏幕上只有一句
 *   HTTP 400: agent_binding is required: every runtime key must name the agent it is
 *   issued to, and that agent must activate it in Console with the 8-character
 *   matching code before the key can spend anything
 * —— 用户既不知道错在哪，也不知道下一步点哪儿。
 *
 * 这条测试跑的是真代码（vm 里加载 karma-public-api.js + 一个假的 fetch），
 * 钉住三件事：
 *   1. 认得的闸门：message 变成一句可执行的中文；
 *   2. 原文不丢：err.detail / err.serverMessage 里还在（排查要看它）；
 *   3. 不认得的口径：message 原样保留「HTTP <code>: <detail>」，不假装看得懂。
 *
 * 跑法：node tests/js/test_gate_error_hints.cjs
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

/** 从源码里取人话，别在测试里抄一份 —— 抄的那份迟早和实现走散。 */
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

function makeEnv(fetchImpl) {
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
    fetch: fetchImpl,
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(CODE, sandbox, { filename: SRC });
  return sandbox;
}

function failingFetch(status, detail) {
  return () =>
    Promise.resolve({
      ok: false,
      status: status,
      statusText: "Bad Request",
      text: () => Promise.resolve(JSON.stringify({ detail: detail })),
    });
}

const AGENT_BINDING_DETAIL =
  "agent_binding is required: every runtime key must name the agent it is issued to, and that " +
  "agent must activate it in Console with the 8-character matching code before the key can spend anything";

(async function testKnownGateBecomesAdvice() {
  const env = makeEnv(failingFetch(400, AGENT_BINDING_DETAIL));
  let err = null;
  try {
    await env.karmaRuntimeApi.runtimeCreateKey({});
  } catch (e) {
    err = e;
  }
  eq("状态码照旧给调用方", err && err.status, 400);
  eq("message 变成人话", err && err.message, hintFor("agent_binding is required"));
  check("人话不是英文 API 原文", !!err && err.message.indexOf("agent_binding is required") < 0, err && err.message);
  check("原文留在 err.detail", !!err && String(err.detail).indexOf("agent_binding is required") >= 0, err && err.detail);
  check(
    "原文留在 err.serverMessage（含 HTTP 码）",
    !!err && /^HTTP 400: agent_binding is required/.test(String(err.serverMessage)),
    err && err.serverMessage
  );
})();

(async function testMismatchedAgentIdsGetTheirOwnHint() {
  const env = makeEnv(failingFetch(403, "agent_id must match agent_binding"));
  let err = null;
  try {
    await env.karmaRuntimeApi.runtimeCreateKey({});
  } catch (e) {
    err = e;
  }
  eq("两个字段写岔了有单独一句", err && err.message, hintFor("agent_id must match agent_binding"));
})();

(async function testUnknownDetailIsNotPretendedToBeUnderstood() {
  const env = makeEnv(failingFetch(400, "some brand new gate nobody mapped"));
  let err = null;
  try {
    await env.karmaRuntimeApi.runtimeCreateKey({});
  } catch (e) {
    err = e;
  }
  eq("不认识的口径原样抛", err && err.message, "HTTP 400: some brand new gate nobody mapped");
  eq("也不写 serverMessage", err && err.serverMessage, undefined);
})();

setTimeout(function () {
  if (failures) {
    console.error("FAILED " + failures + "/" + checks + " gate-hint checks");
    process.exit(1);
  }
  console.log("ok  gate error hints: " + checks + " checks passed");
}, 50);
