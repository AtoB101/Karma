/**
 * 接入确认 · 两个宿主（apps/console/scripts/cyber-bind-requests.js）
 *
 * 用户实测（2026-10-12）：「操作台里找不到输匹配码的地方」—— 输码框原来只挂在
 * 「设置 → 接入确认」那张卡片上，Agent 接入那条一条龙里没有。现在第 ③ 步
 * 「激活 · 输入匹配码」（#ag-activate）是主入口，设置页那张留着当兜底：
 * 两个宿主必须都有码框、都亮红点、都能就地输码 —— 少画一个，用户还是找不到。
 *
 * 另一件容易踩的事：两张卡片各有一个输入框，点哪张的「确认绑定」就得读哪张的值。
 * 只按 key_id 去全局找第一个框，会把「在设置页填好了、却读到 Agent 接入页那个空框」
 * 判成「匹配码不是 8 位」—— 这个坑专门钉一条。
 *
 * 跑法：node tests/js/test_console_bind_requests_hosts.cjs
 */
"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(__dirname, "..", "..");
const SRC = path.join(ROOT, "apps", "console", "scripts", "cyber-bind-requests.js");
const KEY = "40dd572ce5491bd0077b48ce147acbce";
const CODE = "K4QP-3M2X";

let failures = 0;
let checks = 0;

function check(name, cond, extra) {
  checks += 1;
  if (cond) return;
  failures += 1;
  console.error("FAIL: " + name + (extra ? " -- " + extra : ""));
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
    value: "",
    hidden: false,
    attrs: {},
    handlers: {},
    children: [],
    addEventListener: function (ev, fn) { (this.handlers[ev] = this.handlers[ev] || []).push(fn); },
    setAttribute: function (k, v) { this.attrs[k] = v; },
    getAttribute: function (k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; },
    removeAttribute: function (k) { delete this.attrs[k]; },
    classList: {
      _on: {},
      toggle: function (c, on) { this._on[c] = !!on; },
      add: function (c) { this._on[c] = true; },
      remove: function (c) { this._on[c] = false; },
      contains: function (c) { return !!this._on[c]; },
    },
    querySelector: function () { return null; },
    querySelectorAll: function () { return []; },
    appendChild: function (c) { this.children.push(c); return c; },
    dispatchEvent: function () { return true; },
  };
  let html = "";
  Object.defineProperty(node, "innerHTML", {
    get: function () { return html; },
    set: function (v) { html = v; if (v === "") node.children.length = 0; },
  });
  return node;
}

/** 一个「被点到的元素」：只需要 closest 能按选择器回答。 */
function target(answers) {
  return {
    closest: function (sel) {
      return Object.prototype.hasOwnProperty.call(answers, sel) ? answers[sel] : null;
    },
  };
}

function boot(api) {
  const nodes = {};
  const byId = function (id) {
    if (!nodes[id]) nodes[id] = makeNode(id);
    return nodes[id];
  };
  const clickHandlers = [];
  // 两张卡片各一个码框：Agent 接入页那个在文档里排前面（页面顺序），设置页那个在后。
  const inputAg = makeNode("input-ag");
  inputAg.setAttribute("data-bind-code", KEY);
  const inputSet = makeNode("input-set");
  inputSet.setAttribute("data-bind-code", KEY);
  const boxAg = makeNode("box-ag");
  boxAg.querySelector = function (sel) { return sel === "[data-bind-code]" ? inputAg : null; };
  const boxSet = makeNode("box-set");
  boxSet.querySelector = function (sel) { return sel === "[data-bind-code]" ? inputSet : null; };

  const document = {
    readyState: "complete",
    getElementById: byId,
    createElement: function () { return makeNode("__new"); },
    addEventListener: function (ev, fn) { if (ev === "click") clickHandlers.push(fn); },
    querySelector: function (sel) {
      if (sel === '.nav-main[data-page="settings"]') return byId("nav-settings");
      if (sel === '.nav-main[data-page="agents"]') return byId("nav-agents");
      return null;
    },
    querySelectorAll: function (sel) {
      if (sel === "[data-bind-code]") return [inputAg, inputSet];
      return [];
    },
    dispatchEvent: function () { return true; },
    body: makeNode("__body"),
    documentElement: makeNode("__html"),
  };
  const window = {
    document: document,
    KARMA_IDENTITY_ID: "kid_test",
    karmaRuntimeApi: api,
    sessionStorage: { getItem: function () { return null; }, setItem: function () {} },
    confirm: function () { return true; },
    setInterval: function () { return 0; },
  };
  const sandbox = {
    window: window,
    document: document,
    console: console,
    setTimeout: setTimeout,
    clearTimeout: clearTimeout,
    setInterval: function () { return 0; },
    CustomEvent: function (type) { this.type = type; },
  };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(SRC, "utf8"), sandbox, { filename: SRC });
  return {
    nodes: nodes,
    byId: byId,
    window: window,
    inputAg: inputAg,
    inputSet: inputSet,
    boxAg: boxAg,
    boxSet: boxSet,
    click: function (t) {
      clickHandlers.forEach(function (fn) { fn({ target: t, preventDefault: function () {} }); });
    },
  };
}

function flush() {
  return new Promise(function (resolve) { setTimeout(resolve, 0); });
}

async function main() {
  const state = { polls: 0, confirmed: [], rejected: [] };
  const api = {
    runtimeListPendingBinds: async function () {
      state.polls += 1;
      return {
        requests: [
          {
            key_id: KEY,
            agent_id: "2222",
            agent_name: "2222",
            agent_fingerprint: "ed25519:abc",
            expires_at: "2026-10-12T20:30:08Z",
            attempts_left: 3,
            expired: false,
          },
        ],
      };
    },
    runtimeConfirmBindKey: async function (body) { state.confirmed.push(body); return { agent_fingerprint: "ed25519:abc" }; },
    runtimeRejectBindKey: async function (body) { state.rejected.push(body); return {}; },
  };

  const env = boot(api);
  env.window.KarmaHandoff = {
    normalizeCode: function (v) { return String(v || "").trim().toUpperCase(); },
    buildConfirmBindMsg: function () { return "msg"; },
    buildRejectBindMsg: function () { return "msg"; },
    walletProvider: async function () { return { request: async function (o) { return o.method === "eth_requestAccounts" ? ["0xabc"] : "0xsig"; } }; },
  };
  await flush();
  await flush();

  // ---- 两个宿主都画出来了 --------------------------------------------------
  eq("轮询拿到了待确认请求", state.polls >= 1, true);
  const agBody = env.byId("ag-activate-requests").innerHTML;
  const setBody = env.byId("bind-requests").innerHTML;
  check("Agent 接入页第 ③ 步画出码框", agBody.indexOf('data-bind-code="' + KEY + '"') >= 0, agBody);
  check("设置页那张卡片也画出码框", setBody.indexOf('data-bind-code="' + KEY + '"') >= 0, setBody);
  eq("两处内容一致（同一份实现）", agBody, setBody);

  // ---- 两张卡片都亮、两个侧栏入口都挂红点 -----------------------------------
  eq("第 ③ 步卡片高亮", env.byId("ag-activate").classList.contains("attention"), true);
  eq("设置页卡片高亮", env.byId("ag-bind-requests").classList.contains("attention"), true);
  eq("侧栏 Agent 接入挂红点", env.byId("nav-agents").classList.contains("has-pending"), true);
  eq("侧栏 设置挂红点", env.byId("nav-settings").classList.contains("has-pending"), true);

  // ---- 点哪张卡片的「确认绑定」，就读哪张卡片的码 ---------------------------
  env.inputAg.value = "";            // 主入口那个还是空的
  env.inputSet.value = CODE;         // 用户是在设置页那张卡片里填的
  const setConfirm = makeNode("set-confirm");
  setConfirm.setAttribute("data-bind-confirm", KEY);
  // 真 DOM 里这颗按钮就在那张卡片里：closest(".ag-snippet") 得回到同一张卡。
  setConfirm.closest = function (sel) { return sel === ".ag-snippet" ? env.boxSet : null; };
  env.click(target({ "[data-bind-confirm]": setConfirm }));
  await flush();
  await flush();
  eq("读到的是同一张卡片里的码", state.confirmed.length, 1);
  if (state.confirmed.length) eq("提交的匹配码就是那张卡片里填的", state.confirmed[0].activation_code, CODE);
  check("没有误判成「匹配码不是 8 位」",
    env.byId("bind-requests").innerHTML.indexOf("匹配码是 8 位") < 0,
    env.byId("bind-requests").innerHTML);

  // ---- 第 ③ 步那张卡片也能就地确认 + 拒绝 ----------------------------------
  state.confirmed.length = 0;
  state.rejected.length = 0;
  env.inputAg.value = CODE;
  env.inputSet.value = "";
  const agConfirm = makeNode("ag-confirm");
  agConfirm.setAttribute("data-bind-confirm", KEY);
  agConfirm.closest = function (sel) { return sel === ".ag-snippet" ? env.boxAg : null; };
  env.click(target({ "[data-bind-confirm]": agConfirm }));
  await flush();
  await flush();
  eq("第 ③ 步卡片能就地确认绑定", state.confirmed.length, 1);
  if (state.confirmed.length) eq("第 ③ 步提交的是它自己框里的码", state.confirmed[0].activation_code, CODE);

  const agReject = makeNode("ag-reject");
  agReject.setAttribute("data-bind-reject", KEY);
  env.click(target({ "[data-bind-reject]": agReject }));
  await flush();
  await flush();
  eq("第 ③ 步卡片也能就地把这次接入拒掉", state.rejected.length, 1);

  // ---- 第 ③ 步的「刷新待确认请求」重新取数 ---------------------------------
  const before = state.polls;
  const refresh = makeNode("activate-refresh");
  env.click(target({ "#btn-activate-refresh": refresh }));
  await flush();
  await flush();
  check("第 ③ 步的刷新按钮会重新取数", state.polls > before, "polls=" + state.polls + " before=" + before);

  console.log((failures ? "FAILED " : "ok  ") + "console bind requests hosts: " + (checks - failures) + "/" + checks + " checks passed");
  process.exit(failures ? 1 : 0);
}

main().catch(function (e) {
  console.error(e);
  process.exit(2);
});
