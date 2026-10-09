/**
 * 授权向导 · 选已有档案时把已授额度/边界原样填回（cyber-authorize.js 的 prefillFromProfile）。
 *
 * 线上反馈（2026-10-10）：小爱已经授过额度、权限，但「给 agent 授权」向导选它之后
 * 还是空白/默认值，等于让用户再授权一遍。这里把模块真的跑起来，钉住：
 *   1. 选一个已授权的档案，额度、单笔、日上限、人工确认、权限都要按它原样填回；
 *   2. 没授过边界的档案仍走默认权限，不把空值写进去。
 *
 * 跑法：node tests/js/test_console_authorize_prefill.cjs
 */
"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(__dirname, "..", "..");
const SRC = path.join(ROOT, "apps", "console", "scripts", "cyber-authorize.js");

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

function makeNode(id) {
  const attrs = {};
  const handlers = {};
  const node = {
    id: id,
    textContent: "",
    className: "",
    title: "",
    type: "",
    hidden: false,
    disabled: false,
    value: "",
    checked: false,
    style: {},
    options: [],
    children: [],
    appendChild: function (child) { this.children.push(child); return child; },
    addEventListener: function (ev, fn) { (handlers[ev] = handlers[ev] || []).push(fn); },
    getAttribute: function (k) { return Object.prototype.hasOwnProperty.call(attrs, k) ? attrs[k] : null; },
    setAttribute: function (k, v) { attrs[k] = String(v); },
    removeAttribute: function (k) { delete attrs[k]; },
    classList: { toggle: function () {}, add: function () {}, remove: function () {} },
    querySelectorAll: function () { return []; },
    fire: function (ev) {
      const fns = handlers[ev] || [];
      for (let i = 0; i < fns.length; i += 1) fns[i]({ target: node });
    },
  };
  let html = "";
  Object.defineProperty(node, "innerHTML", {
    get: function () { return html; },
    set: function (v) { html = v; if (v === "") node.children.length = 0; },
  });
  return node;
}

function boot(api) {
  const nodes = {};
  const byId = function (id) { if (!nodes[id]) nodes[id] = makeNode(id); return nodes[id]; };
  nodes["agw-human"] = makeNode("agw-human");
  nodes["agw-human"].options = [{ value: "above_single" }, { value: "always" }, { value: "off" }];
  const document = {
    readyState: "complete",
    getElementById: byId,
    createElement: function () { return makeNode("__new"); },
    addEventListener: function () {},
    querySelector: function () { return null; },
    querySelectorAll: function () { return []; },
    dispatchEvent: function () { return true; },
    documentElement: makeNode("__html"),
    body: makeNode("__body"),
  };
  const window = {
    document: document,
    KARMA_IDENTITY_ID: "kid_test",
    cyberKarmaApi: api,
    KarmaDisplayId: { of: function (id) { return String(id || "").slice(0, 8); }, remote: function (id) { return String(id || ""); } },
    KarmaNodes: { effectiveBase: function () { return ""; } },
    KarmaWalletAuth: {},
    karmaRuntimeApi: {},
    CYBER_I18N: {},
  };
  window.window = window;
  const sandbox = {
    window: window,
    document: document,
    navigator: {},
    console: console,
    setTimeout: setTimeout,
    clearTimeout: clearTimeout,
  };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(SRC, "utf8"), sandbox, { filename: SRC });
  return { nodes: nodes, byId: byId, window: window };
}

function flush() {
  return new Promise(function (resolve) { setTimeout(resolve, 0); });
}

async function main() {
  const authorized = {
    profile_id: "p_authorized",
    class: "individual",
    display_name: "小爱",
    kyc_status: "verified",
    visibility: "public",
    status: "active",
    spend_policy: {
      permissions: ["request_voucher", "verify_voucher", "submit_receipt", "update_progress", "request_settlement", "sync_task_status", "discover_agents", "place_order"],
      single_limit: 50,
      daily_limit: 100,
      high_risk_mode: "above_single",
    },
  };
  const bare = {
    profile_id: "p_bare",
    class: "individual",
    display_name: "新助理",
    kyc_status: "none",
    visibility: "public",
    status: "active",
    spend_policy: {},
  };
  const api = {
    listRoleProfiles: async function () { return { profiles: [authorized, bare] }; },
    getAllocations: async function () {
      return {
        locked_usdc: 200,
        allocations: [{ profile_id: "p_authorized", allocated_credits: 50 }, { profile_id: "p_bare", allocated_credits: 0 }],
      };
    },
    getCapacity: async function () { return { total_locked_usdc: 200 }; },
    setAllocations: async function () { return {}; },
    putAutomationPolicy: async function () { return {}; },
  };

  const env = boot(api);
  await flush();
  await flush();

  const sel = env.byId("agw-identity");
  check("授权向导已跑起来（renderIdentities 写了选项）", sel.innerHTML.indexOf("p_authorized") >= 0, sel.innerHTML);

  sel.value = "p_authorized";
  sel.fire("change");
  await flush();

  eq("额度回填成已有分配", env.byId("agw-amount").value, "50");
  eq("单笔上限回填", env.byId("agw-single").value, "50");
  eq("日上限回填", env.byId("agw-daily").value, "100");
  eq("人工确认回填", env.byId("agw-human").value, "above_single");
  const perms = env.window.KarmaAuthorize && env.window.KarmaAuthorize.state.selectedPerms;
  check("权限回填成档案已有 8 条", Array.isArray(perms) && perms.length === 8 && perms.indexOf("verify_voucher") >= 0, JSON.stringify(perms));

  sel.value = "p_bare";
  sel.fire("change");
  await flush();
  const barePerms = env.window.KarmaAuthorize.state.selectedPerms;
  check("没有边界的档案退回默认权限（不把空值写进去）", Array.isArray(barePerms) && barePerms.indexOf("place_order") >= 0, JSON.stringify(barePerms));

  console.log((failures ? "FAILED " : "ok  ") + "authorize wizard prefill: " + (checks - failures) + "/" + checks + " checks passed");
  process.exit(failures ? 1 : 0);
}

main().catch(function (e) {
  console.error(e);
  process.exit(2);
});
