/**
 * 建立子身份 · 卡片清单（apps/console/scripts/cyber-identity-verify.js 的 loadSubs）
 *
 * 线上实测（2026-10-10）：这一整块渲染成「读取失败：T is not defined」。
 * 7f362e7 给这一页加「同人刷脸已核验」文案时用了 T() / Tf()，但这个模块自己
 * 没有定义它们（别的操作台模块都在文件里各定义一份）。ReferenceError 被 loadSubs
 * 自己的 try/catch 吞掉 —— 页面不报错、控制台干净，用户只看到一句「读取失败」，
 * 他建好的卡一张都不显示（连「小爱」建好了也看不见）。
 *
 * 所以这里把模块真的跑起来（假 DOM + 假 API），钉两件事：
 *   1. 清单要真的把卡画出来，而不是那句「读取失败」；
 *   2. 没开通的卡上要有「刷脸确认」按钮：点一下调 confirmSamePerson(profile_id, class)，
 *      当场开通；主身份还没刷过脸这种「比对不了」的情况要如实说出来，不装作已开通。
 *
 * 跑法：node tests/js/test_console_sub_list.cjs
 */
"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(__dirname, "..", "..");
const SRC = path.join(ROOT, "apps", "console", "scripts", "cyber-identity-verify.js");
const NO_TEMPLATE = "这个身份还没有刷脸模板：先把主身份刷脸激活，再来加身份。";

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
    children: [],
    handlers: {},
    appendChild: function (child) { this.children.push(child); return child; },
    addEventListener: function (ev, fn) { (this.handlers[ev] = this.handlers[ev] || []).push(fn); },
    setAttribute: function () {},
    removeAttribute: function () {},
    classList: { toggle: function () {}, add: function () {}, remove: function () {} },
    querySelectorAll: function () { return []; },
    dispatchEvent: function () { return true; },
    click: async function () {
      const fns = this.handlers.click || [];
      for (let i = 0; i < fns.length; i += 1) await fns[i]({});
    },
  };
  // 真 DOM 里 innerHTML = "" 会把子节点清空 —— 假的也要清，否则重新渲染后读到的是旧行。
  let html = "";
  Object.defineProperty(node, "innerHTML", {
    get: function () { return html; },
    set: function (value) { html = value; if (value === "") node.children.length = 0; },
  });
  return node;
}

/** 把模块真的跑起来：假 DOM + 假 API，返回 {nodes, window, api}。 */
function boot(api) {
  const nodes = {};
  const byId = function (id) { if (!nodes[id]) nodes[id] = makeNode(id); return nodes[id]; };
  const document = {
    readyState: "complete",
    getElementById: byId,
    createElement: function () { return makeNode("__new"); },
    addEventListener: function () {},
    querySelectorAll: function () { return []; },
    dispatchEvent: function () { return true; },
    documentElement: makeNode("__html"),
    body: makeNode("__body"),
  };
  const window = { document: document, KARMA_IDENTITY_ID: "kid_test", cyberKarmaApi: api };
  const sandbox = {
    window: window,
    document: document,
    console: console,
    setTimeout: setTimeout,
    clearTimeout: clearTimeout,
    CustomEvent: function (type) { this.type = type; },
  };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(SRC, "utf8"), sandbox, { filename: SRC });
  return { nodes: nodes, byId: byId, window: window };
}

function flush() {
  return new Promise(function (resolve) { setTimeout(resolve, 0); });
}

function btnByText(row, text) {
  const hit = row.children.filter(function (c) { return c.textContent === text; });
  return hit.length ? hit[0] : null;
}

function card(status, extra) {
  const base = {
    profile_id: "p_" + status,
    class: "individual",
    display_name: "小爱",
    kyc_status: status,
    bound_wallet_address: "0x5acc51116f66b84802c8321f286d09014a78346f",
    kyc_payload: {},
  };
  return Object.assign(base, extra || {});
}

async function main() {
  const state = { verified: false, listCalls: 0, vaultCalls: [], vaultError: null };
  const api = {
    listRoleProfiles: async function () {
      state.listCalls += 1;
      const pending = card("pending", { kyc_payload: { kind: "face_confirm" } });
      const opened = card("verified", {
        profile_id: "p_opened",
        display_name: "老卡",
        kyc_payload: { face_consistency: { score: 0.91 } },
      });
      return { profiles: state.verified ? [Object.assign({}, pending, { kyc_status: "verified", kyc_payload: { face_consistency: { score: 0.9 } } }), opened] : [pending, opened] };
    },
    getAllocations: async function () { return { allocations: [{ profile_id: "p_pending", allocated_credits: 100 }] }; },
    getIdentityVerification: async function () { return { status: "verified" }; },
    getEscrowState: async function () { return { committed_usdc: 0 }; },
    getCapacity: async function () { return { total_locked_usdc: 0 }; },
  };

  const env = boot(api);
  await flush();
  await flush();

  const list = env.byId("idsub-list");
  check("清单不报错（T/Tf 要在这个模块里定义）", list.textContent.indexOf("读取失败") < 0, JSON.stringify(list.textContent));
  eq("两张卡都画出来了", list.children.length, 2);
  const rows = list.children;
  check("第一张是「小爱」", rows[0].innerHTML.indexOf("小爱") >= 0, rows[0].innerHTML);
  check("没开通的卡显示「复核中」", rows[0].innerHTML.indexOf("复核中") >= 0, rows[0].innerHTML);
  check("没开通的卡有「刷脸确认」按钮", !!btnByText(rows[0], "刷脸确认"), JSON.stringify(rows[0].children.map(function (c) { return c.textContent; })));
  check("刷脸开通的卡不再有「刷脸确认」按钮", !btnByText(rows[1], "刷脸确认"), JSON.stringify(rows[1].children.map(function (c) { return c.textContent; })));
  check("刷脸开通的卡单独一句话", rows[1].innerHTML.indexOf("同人刷脸已核验") >= 0, rows[1].innerHTML);

  // ---- 点「刷脸确认」：当场开通 -------------------------------------------
  env.window.KarmaFaceVault = {
    confirmSamePerson: async function (pid, klass) {
      state.vaultCalls.push([pid, klass]);
      state.verified = true;
      return { score: 0.9, verdict: { threshold: 0.35 } };
    },
  };
  const before = state.listCalls;
  await btnByText(rows[0], "刷脸确认").click();
  await flush();
  await flush();
  eq("按 (profile_id, class) 调同人比对", JSON.stringify(state.vaultCalls), JSON.stringify([["p_pending", "individual"]]));
  const status = env.byId("idsub-list-status");
  check("结果说「已经开通」", status.textContent.indexOf("已经开通") >= 0, JSON.stringify(status.textContent));
  check("结果带上相似度与阈值", status.textContent.indexOf("0.9000") >= 0 && status.textContent.indexOf("0.3500") >= 0, JSON.stringify(status.textContent));
  check("开通后重读清单", state.listCalls > before, "listCalls=" + state.listCalls);
  const rows2 = list.children;
  check("那张卡从「复核中」变成已核验", rows2[0].innerHTML.indexOf("同人刷脸已核验") >= 0, rows2[0].innerHTML);
  check("开通后按钮收掉了", !btnByText(rows2[0], "刷脸确认"), JSON.stringify(rows2[0].children.map(function (c) { return c.textContent; })));

  // ---- 主身份还没刷过脸：如实说出来，按钮放回去 ---------------------------
  state.verified = false;
  env.window.KarmaFaceVault = {
    confirmSamePerson: async function () { throw new Error(NO_TEMPLATE); },
  };
  env.window.KarmaIdentityVerify.refresh();
  await flush();
  await flush();
  const again = env.byId("idsub-list").children[0];
  const retry = btnByText(again, "刷脸确认");
  check("重读清单后未开通的卡又能刷脸", !!retry);
  await retry.click();
  await flush();
  await flush();
  check("比对不了就把原因原样说出来", env.byId("idsub-list-status").textContent.indexOf(NO_TEMPLATE) >= 0, JSON.stringify(env.byId("idsub-list-status").textContent));
  check("失败后按钮放回去，可以再试", !btnByText(env.byId("idsub-list").children[0], "刷脸确认").disabled);
  check("失败不装作已开通", env.byId("idsub-list").children[0].innerHTML.indexOf("同人刷脸已核验") < 0);

  console.log((failures ? "FAILED " : "ok  ") + "console sub list: " + (checks - failures) + "/" + checks + " checks passed");
  process.exit(failures ? 1 : 0);
}

main().catch(function (e) {
  console.error(e);
  process.exit(2);
});
