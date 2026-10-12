/**
 * 操作台「接入一个 Agent」合并后的一条龙：一颗按钮、两个方向。
 *
 * 2026-10-13 用户口径：授权向导与旧的「接入一个 Agent」合并成同一张卡——
 * 身份 / 名字只填一次，方向决定走不走目录注册。这里把两个模块真的跑起来，
 * 点那一颗按钮，验证它按方向发出正确的调用：
 *   1. 收款方向：先 ownerConnect（同一个 agent 名）再 runtimeCreateKey，
 *      且目录 API Key 与标签都回到交付卡；
 *   2. 付款方向（未选行业）：只铸钥匙，不进目录；
 *   3. 收款方向但没选行业：当场拦下，两个调用都不发。
 *
 * 跑法：node tests/js/test_console_agent_onestop_merge.cjs
 */
"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(__dirname, "..", "..");
const SCRIPTS = path.join(ROOT, "apps", "console", "scripts");

let failures = 0;
let checks = 0;
function check(name, cond, extra) {
  checks += 1;
  if (cond) return;
  failures += 1;
  console.error("FAIL: " + name + (extra ? " \u2014 " + extra : ""));
}
function eq(name, actual, expected) {
  check(name, actual === expected, "expected " + JSON.stringify(expected) + ", got " + JSON.stringify(actual));
}

function makeNode(id) {
  const attrs = {};
  const handlers = {};
  const node = {
    id: id, textContent: "", className: "", title: "", type: "", hidden: false,
    disabled: false, value: "", checked: false, style: {}, options: [], children: [],
    appendChild: function (c) { this.children.push(c); return c; },
    addEventListener: function (ev, fn) { (handlers[ev] = handlers[ev] || []).push(fn); },
    getAttribute: function (k) { return Object.prototype.hasOwnProperty.call(attrs, k) ? attrs[k] : null; },
    setAttribute: function (k, v) { attrs[k] = String(v); },
    removeAttribute: function (k) { delete attrs[k]; },
    hasAttribute: function (k) { return Object.prototype.hasOwnProperty.call(attrs, k); },
    classList: { toggle: function () {}, add: function () {}, remove: function () {}, contains: function () { return false; } },
    querySelectorAll: function () { return []; },
    querySelector: function () { return null; },
    closest: function () { return null; },
    focus: function () {}, scrollIntoView: function () {},
    remove: function () {},
    fire: function (ev) { (handlers[ev] || []).forEach(function (fn) { fn({ target: node }); }); },
  };
  let html = "";
  Object.defineProperty(node, "innerHTML", {
    get: function () { return html; },
    set: function (v) { html = String(v); if (html === "") node.children.length = 0; },
  });
  return node;
}

function boot(api, calls) {
  const nodes = {};
  const byId = function (id) { if (!nodes[id]) nodes[id] = makeNode(id); return nodes[id]; };
  nodes["agw-human"] = makeNode("agw-human");
  nodes["agw-human"].options = [{ value: "above_single" }, { value: "always" }, { value: "off" }];

  const permNodes = ["request_voucher", "verify_voucher", "submit_receipt", "update_progress",
    "request_settlement", "sync_task_status", "discover_agents", "place_order"].map(function (k) {
    const n = makeNode("perm_" + k); n.checked = true; n.setAttribute("data-agw-perm", k); return n;
  });
  const typeNode = makeNode("type"); typeNode.value = "life";

  const agentsHost = makeNode("agents");
  const document = {
    readyState: "complete",
    getElementById: byId,
    createElement: function () { return makeNode("__new"); },
    addEventListener: function () {}, removeEventListener: function () {},
    querySelector: function (sel) {
      if (sel === 'input[name="agw-type"]:checked') return typeNode;
      if (sel && sel.charAt(0) === "#") return byId(sel.slice(1));
      return null;
    },
    querySelectorAll: function (sel) {
      if (sel === "[data-agw-perm]") return permNodes;
      return [];
    },
    dispatchEvent: function () { return true; },
    documentElement: makeNode("__html"),
    body: makeNode("__body"),
    head: makeNode("__head"),
  };

  const wallet = { request: async function (m) { return m.method === "eth_requestAccounts" ? ["0xabc"] : "0xsig"; } };
  const window = {
    document: document,
    KARMA_IDENTITY_ID: "kid_test",
    cyberKarmaApi: api,
    karmaRuntimeApi: { runtimeCreateKey: async function (payload) { calls.runtimeCreateKey.push(payload); return { runtime_key: "rk_test" }; } },
    KarmaWalletAuth: { activeProvider: function () { return wallet; } },
    KarmaDisplayId: { of: function (id) { return String(id || "").slice(0, 8); }, remote: function (id) { return String(id || ""); } },
    KarmaNodes: { effectiveBase: function () { return ""; } },
    KarmaServiceSpec: {
      renderForm: function () {}, fillFromExample: function () {},
      industryTitle: function (row, fb) { return (row && row.title_zh) || fb; },
      collect: function () { return { spec: { ok: 1 }, problems: [] }; },
    },
    CYBER_I18N: {},
    CustomEvent: function (t, o) { this.type = t; this.detail = (o || {}).detail; },
  };
  window.window = window;
  const sandbox = { window: window, document: document, navigator: {}, console: console,
    setTimeout: setTimeout, clearTimeout: clearTimeout, CustomEvent: window.CustomEvent };
  vm.createContext(sandbox);
  for (const f of ["cyber-authorize.js", "cyber-agents.js"]) {
    const full = path.join(SCRIPTS, f);
    vm.runInContext(fs.readFileSync(full, "utf8"), sandbox, { filename: full });
  }
  window.__calls = calls;
  return { nodes: nodes, byId: byId, window: window, calls: calls };
}

function flush(n) {
  let p = Promise.resolve();
  for (let i = 0; i < (n || 4); i += 1) p = p.then(function () { return new Promise(function (r) { setTimeout(r, 0); }); });
  return p;
}

const PROFILE = { profile_id: "p_love", "class": "individual", display_name: "小爱", kyc_status: "verified", visibility: "public", status: "active", spend_policy: {} };

function baseApi(calls) {
  return {
    listRoleProfiles: async function () { return { profiles: [PROFILE] }; },
    getAllocations: async function () { return { locked_usdc: 200, allocations: [{ profile_id: "p_love", allocated_credits: 0 }] }; },
    getCapacity: async function () { return { total_locked_usdc: 200 }; },
    setAllocations: async function () { return {}; },
    putAutomationPolicy: async function () { return {}; },
    listOnboardingIndustries: async function () { return { industries: [{ industry_id: "food", group: "g", title_zh: "餐饮" }] }; },
    getOnboardingIndustry: async function () { return { industry: { industry_id: "food", title_zh: "餐饮", fields: [] } }; },
    listMyAgents: async function () { return { agents: [] }; },
    ownerConnect: async function (payload) {
      calls.ownerConnect.push(payload);
      return { agent: { agent_id: payload.agent_id, name: payload.display_name }, credentials: { api_key: "ak_test" }, p1_ready: true };
    },
  };
}

function fill(env, opts) {
  const sel = env.byId("agw-identity");
  sel.value = "p_love";
  sel.fire("change");
  env.byId("agw-agent").value = opts.agentName || "claw-001";
  env.byId("agw-amount").value = "50";
  env.byId("agw-single").value = "100";
  env.byId("agw-daily").value = "500";
  env.byId("agw-ack").checked = true;
  env.byId("ag-side").value = opts.side;
  env.byId("ag-vertical").value = opts.vertical || "";
}

async function main() {
  // 1 · 收款方向：先注册进目录，再铸钥匙
  {
    const calls = { ownerConnect: [], runtimeCreateKey: [] };
    const env = boot(baseApi(calls), calls);
    await flush();
    fill(env, { side: "seller", vertical: "food" });
    env.byId("ag-vertical").fire("change");
    await flush(6);
    env.byId("agw-generate").fire("click");
    await flush(8);
    eq("收款方向：ownerConnect 调了 1 次", calls.ownerConnect.length, 1);
    eq("同一个 agent 名当 agent_id", calls.ownerConnect[0] && calls.ownerConnect[0].agent_id, "claw-001");
    eq("scope_profile_id 用第 1 步选的身份", calls.ownerConnect[0] && calls.ownerConnect[0].scope_profile_id, "p_love");
    eq("行业硬指标随注册一起交", calls.ownerConnect[0] && calls.ownerConnect[0].answers && calls.ownerConnect[0].answers.service_specs && calls.ownerConnect[0].answers.service_specs.food && calls.ownerConnect[0].answers.service_specs.food.ok, 1);
    eq("钥匙也铸了，绑同一个 agent", calls.runtimeCreateKey.length, 1);
    eq("agent_binding = agent 名", calls.runtimeCreateKey[0] && calls.runtimeCreateKey[0].agent_binding, "claw-001");
    eq("agent_id = agent 名", calls.runtimeCreateKey[0] && calls.runtimeCreateKey[0].agent_id, "claw-001");
    check("目录 API Key 进了交付卡", String(env.byId("agw-result").innerHTML).indexOf("ak_test") >= 0);
    eq("API Key 留在本页供交付包用", (env.window.KarmaAgentKeys || {})["claw-001"], "ak_test");
  }

  // 2 · 付款方向（未选行业）：只铸钥匙
  {
    const calls = { ownerConnect: [], runtimeCreateKey: [] };
    const env = boot(baseApi(calls), calls);
    await flush();
    fill(env, { side: "buyer", vertical: "" });
    env.byId("agw-generate").fire("click");
    await flush(8);
    eq("付款方向：不进目录", calls.ownerConnect.length, 0);
    eq("付款方向：照样铸钥匙", calls.runtimeCreateKey.length, 1);
  }

  // 3 · 收款方向但没选行业：当场拦下
  {
    const calls = { ownerConnect: [], runtimeCreateKey: [] };
    const env = boot(baseApi(calls), calls);
    await flush();
    fill(env, { side: "seller", vertical: "" });
    env.byId("agw-generate").fire("click");
    await flush(8);
    eq("没选行业：不进目录", calls.ownerConnect.length, 0);
    eq("没选行业：也不铸钥匙", calls.runtimeCreateKey.length, 0);
    check("当场给出提示", String(env.byId("agw-gen-status").textContent).length > 0, env.byId("agw-gen-status").textContent);
  }

  console.log((failures ? "FAILED " : "ok  ") + "agent one-stop merge: " + (checks - failures) + "/" + checks + " checks passed");
  process.exit(failures ? 1 : 0);
}

main().catch(function (e) { console.error(e); process.exit(2); });
