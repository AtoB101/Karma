/**
 * 授权向导 · 选已有子身份卡时，把卡上「已经定好的边界」原样读出来（cyber-authorize.js 的 cardPolicy）。
 *
 * 2026-10-13 用户口径：这一页不再让用户重填类型 / 额度 / 单笔 / 日限 / 权限 —— 这些都在
 * 「身份 · 认证 → 建立子身份」刷脸开通那一步落到 role profile 的 spend_policy + allocation
 * 里了。向导只负责把这张卡上已经定好的那份**只读展示**出来（#agw-card-list），生成时也用
 * 同一份。这里把模块真的跑起来，钉住：
 *   1. 选一张建过边界的卡：cardPolicy() 要还原分配额度 / 单笔 / 日限 / 人工确认 / 8 条权限，
 *      且 fromCard=true、只读面板真的写了这些值、默认值提示不出现；
 *   2. 没建过边界的卡：退回系统默认（单笔 100 / 日限 500 / 默认 7 条权限），额度为 0、
 *      fromCard=false —— 不把空值写进去，也不冒充用户签过的边界。
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
    set: function (v) { html = String(v); if (html === "") node.children.length = 0; },
  });
  return node;
}

function boot(api) {
  const nodes = {};
  const byId = function (id) { if (!nodes[id]) nodes[id] = makeNode(id); return nodes[id]; };
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

  const pol = env.window.KarmaAuthorize.cardPolicy();
  check("cardPolicy 认得出这张卡", !!pol);
  eq("额度取自这张卡的分配", pol.amount, 50);
  eq("单笔上限取自这张卡", pol.single, 50);
  eq("日上限取自这张卡", pol.daily, 100);
  eq("人工确认取自这张卡", pol.human, "above_single");
  check("权限取自这张卡的 8 条", Array.isArray(pol.perms) && pol.perms.length === 8 && pol.perms.indexOf("verify_voucher") >= 0, JSON.stringify(pol.perms));
  check("边界来自卡上（fromCard）", pol.fromCard === true);
  const cardList = String(env.byId("agw-card-list").innerHTML);
  check("只读面板写了这张卡的额度", cardList.indexOf("50.00") >= 0, cardList);
  check("只读面板写了这张卡的日上限", cardList.indexOf("100.00") >= 0, cardList);
  check("建过边界的卡不显示「默认值」提示", env.byId("agw-policy-warn").hidden === true);

  sel.value = "p_bare";
  sel.fire("change");
  await flush();

  const barePol = env.window.KarmaAuthorize.cardPolicy();
  eq("没有边界的卡：额度 0", barePol.amount, 0);
  eq("没有边界的卡：单笔退回默认", barePol.single, 100);
  eq("没有边界的卡：日限退回默认", barePol.daily, 500);
  check("没有边界的卡：退回默认权限（含 place_order）", barePol.perms.indexOf("place_order") >= 0 && barePol.perms.length === 7, JSON.stringify(barePol.perms));
  check("没有边界的卡：fromCard=false", barePol.fromCard === false);
  check("没有边界的卡：给了「默认值」提示", String(env.byId("agw-policy-warn").textContent).indexOf("系统默认值") >= 0, env.byId("agw-policy-warn").textContent);

  console.log((failures ? "FAILED " : "ok  ") + "authorize wizard prefill: " + (checks - failures) + "/" + checks + " checks passed");
  process.exit(failures ? 1 : 0);
}

main().catch(function (e) {
  console.error(e);
  process.exit(2);
});
