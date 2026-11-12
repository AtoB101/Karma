/**
 * 节点层（apps/console/scripts/karma-nodes.js）的行为测试。
 *
 * 用 vm 造一个假的浏览器环境把文件跑起来，测的是真代码路径：
 * 选节点、探活、容灾、自定义节点的增删校验 —— 不是 grep 文本。
 *
 * 跑法：node tests/js/test_karma_nodes.cjs
 */
"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const SRC = path.resolve(__dirname, "..", "..", "apps", "console", "scripts", "karma-nodes.js");
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

function okResponse(body, status) {
  return {
    ok: (status || 200) < 400,
    status: status || 200,
    json: () => Promise.resolve(body),
  };
}

function makeEnv(opts) {
  const o = opts || {};
  const store = new Map();
  const sandbox = {
    console,
    setTimeout,
    clearTimeout,
    Promise,
    JSON,
    Date,
    performance,
    AbortController,
    localStorage: {
      getItem: (k) => (store.has(k) ? store.get(k) : null),
      setItem: (k, v) => store.set(k, String(v)),
      removeItem: (k) => store.delete(k),
    },
    location: { hostname: o.host === undefined ? "127.0.0.1" : o.host, origin: o.origin || "http://127.0.0.1:8787" },
    fetch: o.fetch || (() => Promise.resolve(okResponse({ status: "ok", version: "0.1.0" }))),
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(CODE, sandbox, { filename: SRC });
  return { sandbox, store, N: sandbox.KarmaNodes };
}

function msleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

/* --------------------------------------------------------------- 用例 */

(function testPureHelpers() {
  const local = makeEnv({ host: "127.0.0.1", origin: "http://127.0.0.1:8787" });
  eq("local page detected", local.N._pure.isLocalPage(), true);
  eq("empty base on local page -> local API", local.N._pure.resolveBase(""), "http://127.0.0.1:8000");

  const prod = makeEnv({ host: "karma-network.ai", origin: "https://karma-network.ai" });
  eq("prod page not local", prod.N._pure.isLocalPage(), false);
  eq("empty base on prod -> same origin", prod.N._pure.resolveBase(""), "https://karma-network.ai");
  eq("trailing slash stripped", prod.N._pure.resolveBase("https://node.example.com/"), "https://node.example.com");

  eq("reject javascript: scheme", prod.N._pure.isValidBase("javascript:alert(1)"), false);
  eq("reject data: scheme", prod.N._pure.isValidBase("data:text/html,x"), false);
  eq("accept https", prod.N._pure.isValidBase("https://node.example.com"), true);
  eq("accept http", prod.N._pure.isValidBase("http://10.0.0.5:8000/"), true);
  eq("empty means same-origin", prod.N._pure.isValidBase(""), true);
})();

(function testBuiltinListScope() {
  const local = makeEnv({ host: "127.0.0.1" });
  const localIds = local.N.list().map((n) => n.id);
  check("local page sees the dev node", localIds.indexOf("local") >= 0, JSON.stringify(localIds));
  eq("local default node is same-origin", local.N.current().id, "same-origin");

  const prod = makeEnv({ host: "karma-network.ai", origin: "https://karma-network.ai" });
  const prodIds = prod.N.list().map((n) => n.id);
  check("prod page hides the dev node", prodIds.indexOf("local") < 0, JSON.stringify(prodIds));
  eq("prod effective base is the origin", prod.N.effectiveBase(), "https://karma-network.ai");
})();

(function testBootstrapFromLegacyBase() {
  const env = makeEnv({ host: "127.0.0.1" });
  env.store.set("karma_cyber_api_base", "http://127.0.0.1:8000/");
  const node = env.N.bootstrap();
  eq("legacy base maps to the builtin local node", node && node.id, "local");
  eq("selection persisted", env.store.get("karma_console_node_id"), "local");
})();

(function testSelectWritesEverywhere() {
  const env = makeEnv({ host: "127.0.0.1" });
  const seen = [];
  env.N.onChange((d) => seen.push(d));
  const node = env.N.select("official");
  eq("selected node returned", node.id, "official");
  eq("base persisted", env.store.get("karma_cyber_api_base"), "https://karma-network.ai");
  eq("id persisted", env.store.get("karma_console_node_id"), "official");
  eq("window base synced", env.sandbox.KARMA_API_BASE, "https://karma-network.ai");
  eq("effective base follows", env.N.effectiveBase(), "https://karma-network.ai");
  eq("listener fired", seen.length, 1);
  eq("list marks the current node", env.N.list().filter((n) => n.selected).map((n) => n.id).join(","), "official");
})();

(function testHandTypedBaseWinsOverStaleId() {
  // 「连接设置」里手填过一台自建节点，node id 还是上一台 —— 不能把用户甩到别的机器上。
  const env = makeEnv({ host: "127.0.0.1" });
  env.N.select("official");
  env.store.set("karma_cyber_api_base", "http://192.168.1.5:8000");
  eq("typed base is honoured", env.N.effectiveBase(), "http://192.168.1.5:8000");
  const cur = env.N.current();
  eq("typed base surfaces as its own entry", cur.base, "http://192.168.1.5:8000");
  const rows = env.N.list();
  eq("it shows up once in the list", rows.filter((n) => n.base === "http://192.168.1.5:8000").length, 1);
  eq("and it is the current one", rows.filter((n) => n.selected).length, 1);
  // 删掉它 → 回到同源，而不是留在原地。
  env.N.removeCustom(cur.id);
  eq("removing the typed base falls back to same-origin", env.N.current().id, "same-origin");
})();

(function testCustomNodeValidation() {
  const env = makeEnv({ host: "127.0.0.1" });
  const bad = env.N.addCustom({ label: "x", base: "ftp://nope" });
  eq("bad scheme rejected", bad.ok, false);
  eq("bad scheme message", bad.error, "节点地址必须以 http:// 或 https:// 开头");

  const first = env.N.addCustom({ label: "我的节点", base: "https://node.example.com/" });
  eq("custom node added", first.ok, true);
  eq("trailing slash normalised", env.N.list().filter((n) => n.custom)[0].base, "https://node.example.com");

  const dupe = env.N.addCustom({ base: "https://node.example.com" });
  eq("duplicate rejected", dupe.ok, false);
  eq("duplicate message", dupe.error, "这个地址已经在列表里了");

  for (let i = 0; i < 10; i += 1) env.N.addCustom({ base: "https://n" + i + ".example.com" });
  const customs = env.N.list().filter((n) => n.custom);
  eq("custom list capped at 8", customs.length, 8);

  const keep = customs[0].id;
  env.N.select(keep);
  eq("selected custom node", env.N.current().id, keep);
  eq("removing a node falls back to another", env.N.removeCustom(keep) && env.N.current().id !== keep, true);
})();

(async function testProbe() {
  const good = makeEnv({ fetch: () => Promise.resolve(okResponse({ status: "ok", version: "0.1.0" })) });
  const r1 = await good.N.probe(good.N.current().id);
  eq("healthy node passes", r1.ok, true);
  eq("version carried through", r1.version, "0.1.0");

  const bad = makeEnv({
    fetch: () => Promise.resolve({ ok: false, status: 503, json: () => Promise.resolve({}) }),
  });
  const r2 = await bad.N.probe(bad.N.current().id);
  eq("503 is not healthy", r2.ok, false);

  const thrown = makeEnv({ fetch: () => Promise.reject(new Error("CORS")) });
  const r3 = await thrown.N.probe(thrown.N.current().id);
  eq("network error is not healthy", r3.ok, false);
  check("network error surfaced", /CORS/.test(r3.error), JSON.stringify(r3));

  const hung = makeEnv({ fetch: () => new Promise(() => {}) });
  const r4 = await hung.N.probe(hung.N.current().id, { timeoutMs: 30 });
  eq("hung node times out", r4.ok, false);

  const all = await good.N.probeAll();
  check("probeAll covers every visible node", all.length === good.N.list().length, JSON.stringify(all));
  eq("health snapshot cached", good.N.healthOf("same-origin").ok, true);
})();

(async function testFailover() {
  const offline = new Set(["http://127.0.0.1:8000"]);
  const env = makeEnv({
    host: "127.0.0.1",
    fetch: (url) => {
      for (const dead of offline) {
        if (String(url).indexOf(dead) === 0) return Promise.reject(new Error("connect ECONNREFUSED"));
      }
      return Promise.resolve(okResponse({ status: "ok", version: "0.1.0" }));
    },
  });

  eq("autofail is opt-in", env.N.autofailOn(), false);
  eq("no failover while off", await env.N.reportFailure(env.N.effectiveBase()), null);

  env.N.setAutofail(true);
  eq("autofail persisted", env.store.get("karma_console_node_autofail"), "1");

  const moved = await env.N.reportFailure("http://127.0.0.1:8000");
  check("failover picked another node", !!moved, JSON.stringify(moved));
  eq("current node changed", moved.id, "official");
  eq("selection persisted after failover", env.store.get("karma_console_node_id"), "official");

  const env2 = makeEnv({
    host: "127.0.0.1",
    fetch: () => Promise.reject(new Error("down")),
  });
  env2.N.setAutofail(true);
  eq("nothing healthy -> no switch", await env2.N.reportFailure(env2.N.effectiveBase()), null);
  eq("current node unchanged", env2.N.current().id, "same-origin");

  await msleep(1);
})();

setTimeout(function () {
  if (failures) {
    console.error("\n" + failures + "/" + checks + " checks failed");
    process.exit(1);
  }
  console.log("ok  karma-nodes: " + checks + " checks passed");
}, 400);
