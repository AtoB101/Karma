/**
 * 操作台入口深链：`{操作台}/?view=pairing` 要落到「接入一个 Agent」那张一条龙卡，
 * `?view=agents` 要落到「我的助理 Agent」。
 *
 * 为什么钉这一条：聊天适配器（services/chat_adapters）发给主人的接入链接就是
 * `{KARMA_CONSOLE_BASE_URL}/?view=pairing`。地址栏这一段以前没人读 —— 链接在
 * nginx 那一跳还会把查询串丢掉，主人点开只看得到默认的订单页，得自己在侧栏里翻
 * 「接入一个 Agent」在哪（用户实测口径：「找不到位置」）。
 *
 * 这里把 cyber-console.js 真的跑起来（假 DOM），逐个地址断言「哪一页是 active 的」：
 *   1. 没有 view          -> 订单页（默认页不动）
 *   2. ?view=pairing      -> #agents 页 + agents/connect 子项高亮、父项展开
 *   3. ?view=agents       -> #agents 页 + agents/mine 子项高亮
 *   4. ?view=<认不出的值> -> 订单页（地址栏不是命令通道，不许乱跳）
 *   5. 没有 location 的环境 -> 不炸（模块要在最省事的宿主里也能加载）
 *
 * 跑法：node tests/js/test_console_view_landing.cjs
 */
"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(__dirname, "..", "..");
const BOOT = path.join(ROOT, "apps", "console", "scripts", "cyber-console.js");

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

function makeClassList() {
  const set = new Set();
  return {
    add: function () { for (let i = 0; i < arguments.length; i += 1) set.add(arguments[i]); },
    remove: function () { for (let i = 0; i < arguments.length; i += 1) set.delete(arguments[i]); },
    toggle: function (c, force) {
      const on = force === undefined ? !set.has(c) : !!force;
      if (on) set.add(c); else set.delete(c);
      return on;
    },
    contains: function (c) { return set.has(c); },
  };
}

function makeNode(attrs) {
  const node = {
    textContent: "", innerHTML: "", value: "", checked: false, hidden: false,
    style: {}, children: [], scrollTop: 0, open: false, dataset: {},
    _attrs: Object.assign({}, attrs || {}),
    _handlers: {},
    classList: makeClassList(),
  };
  node.getAttribute = function (k) {
    return Object.prototype.hasOwnProperty.call(node._attrs, k) ? node._attrs[k] : null;
  };
  node.setAttribute = function (k, v) { node._attrs[k] = String(v); };
  node.removeAttribute = function (k) { delete node._attrs[k]; };
  node.hasAttribute = function (k) { return Object.prototype.hasOwnProperty.call(node._attrs, k); };
  node.addEventListener = function (ev, fn) { (node._handlers[ev] = node._handlers[ev] || []).push(fn); };
  node.removeEventListener = function () {};
  node.dispatchEvent = function () { return true; };
  node.appendChild = function (c) { node.children.push(c); return c; };
  node.insertBefore = function (c) { node.children.unshift(c); return c; };
  node.removeChild = function (c) { const i = node.children.indexOf(c); if (i >= 0) node.children.splice(i, 1); return c; };
  node.remove = function () {};
  node.cloneNode = function () { return makeNode(node._attrs); };
  node.focus = function () {};
  node.blur = function () {};
  node.click = function () {
    (node._handlers.click || []).forEach(function (fn) {
      fn({ target: node, stopPropagation: function () {}, preventDefault: function () {} });
    });
  };
  node.scrollIntoView = function () {};
  node.scrollTo = function () {};
  node.getBoundingClientRect = function () { return { top: 0, left: 0, width: 0, height: 0, bottom: 0, right: 0 }; };
  // 组 → 自己的主项 / 子项（openGroupOnly 与 markNav 都要按组取）
  node.querySelector = function (sel) {
    if (sel === ".nav-main") return node._main || null;
    if (sel === ".nav-sub") return (node._subs && node._subs[0]) || null;
    return null;
  };
  node.querySelectorAll = function () { return []; };
  node.closest = function (sel) { return sel === ".nav-group" ? node._group || null : null; };
  return node;
}

function makeStore() {
  const map = {};
  return {
    getItem: function (k) { return Object.prototype.hasOwnProperty.call(map, k) ? map[k] : null; },
    setItem: function (k, v) { map[k] = String(v); },
    removeItem: function (k) { delete map[k]; },
  };
}

/** 侧栏分组：跟 apps/console/pages/cyber/index.html 里的 data-group / data-page 一致。 */
const NAV = [
  ["overview", "overview", [["overview", "buy"], ["overview", "sell"]]],
  ["center", "center", [["center", "out"], ["center", "confirm"]]],
  ["tasks", "tasks", [["tasks", "flow"], ["receipts", null]]],
  ["bills", "bills", []],
  ["disputes", "disputes", []],
  ["identity", "identity", [["identity", "master"], ["identity", "life"]]],
  ["verifier-id", "verifier-id", []],
  ["arbiter-id", "arbiter-id", []],
  ["reviews", "reviews", [["reviews", "all"]]],
  ["agents", "agents", [["agents", "connect"], ["agents", "mine"]]],
  ["arbitration", "arbitration", []],
  ["verifiers", "verifiers", []],
  ["settings", "settings", []],
];
const PAGE_IDS = ["overview", "agents", "identity", "bills", "settings", "center", "tasks", "disputes"];

function makeDom() {
  const ids = {};
  const groups = [];
  const mains = [];
  const subs = [];

  NAV.forEach(function (row) {
    const g = makeNode({ "data-group": row[0] });
    g._subs = [];
    const main = makeNode({ "data-page": row[1] });
    main._group = g;
    g._main = main;
    mains.push(main);
    row[2].forEach(function (pair) {
      const s = makeNode(pair[1] ? { "data-page": pair[0], "data-sub": pair[1] } : { "data-page": pair[0] });
      s._group = g;
      g._subs.push(s);
      subs.push(s);
    });
    groups.push(g);
  });

  const pageNodes = PAGE_IDS.map(function (id) {
    const n = makeNode({});
    n.id = id;
    ids[id] = n;
    return n;
  });

  const body = makeNode({});
  const main = makeNode({});

  function findByPage(list, page, sub) {
    for (let i = 0; i < list.length; i += 1) {
      if (list[i].getAttribute("data-page") !== page) continue;
      if (sub && list[i].getAttribute("data-sub") !== sub) continue;
      return list[i];
    }
    return null;
  }

  const domReady = [];
  const document = {
    readyState: "complete",
    body: body,
    documentElement: makeNode({}),
    head: makeNode({}),
    getElementById: function (id) {
      if (!ids[id]) ids[id] = makeNode({});
      return ids[id];
    },
    createElement: function () { return makeNode({}); },
    addEventListener: function (ev, fn) { if (ev === "DOMContentLoaded") domReady.push(fn); },
    removeEventListener: function () {},
    dispatchEvent: function () { return true; },
    querySelector: function (sel) {
      if (!sel) return null;
      if (sel.charAt(0) === "#") return ids[sel.slice(1)] || null;
      if (sel === ".main") return main;
      let m = /^\.nav-sub\[data-page="([^"]+)"\]\[data-sub="([^"]+)"\]$/.exec(sel);
      if (m) return findByPage(subs, m[1], m[2]);
      m = /^\.nav-main\[data-page="([^"]+)"\]$/.exec(sel);
      if (m) return findByPage(mains, m[1], null);
      return null;
    },
    querySelectorAll: function (sel) {
      if (sel === ".page") return pageNodes;
      if (sel === ".nav-group" || sel === ".nav-group[data-group]") return groups;
      if (sel === ".nav-main, .nav-sub") return mains.concat(subs);
      return [];
    },
  };
  return { document: document, ids: ids, groups: groups, mains: mains, subs: subs, domReady: domReady, main: main };
}

/** 把模块真跑一遍；`search` 就是地址栏那一串（含问号）。 */
function boot(search, opts) {
  const dom = makeDom();
  const doc = dom.document;
  const win = {
    document: doc,
    sessionStorage: makeStore(),
    localStorage: makeStore(),
    CYBER_I18N: {
      PACKS: {},
      SHIPPED_LANGS: ["zh-CN"],
      getLang: function () { return "zh-CN"; },
      t: function (k) { return k; },
      applyCyberI18n: function () {},
      ensureExt: function (lang, cb) { if (cb) cb(); },
    },
    CustomEvent: function (t, o) { this.type = t; this.detail = (o || {}).detail; },
    addEventListener: function () {},
    removeEventListener: function () {},
    setTimeout: setTimeout,
    clearTimeout: clearTimeout,
  };
  if (opts && opts.identityClass) {
    // 侧栏收窄规则（applyNavScope）读的就是档案的 class：主身份 = 账房三张卡，
    // 助理身份 = 一张卡干活的地方（agent 接入就在这一档）。
    win.KarmaIdentitySwitcher = {
      getActiveProfile: function () { return { "class": opts.identityClass }; },
    };
  }
  if (!(opts && opts.noLocation)) {
    win.location = {
      search: search || "", hash: "", pathname: "/console/pages/cyber/index.html",
      hostname: "karma-network.ai", origin: "https://karma-network.ai",
    };
  }
  win.window = win;
  const sandbox = {
    window: win,
    document: doc,
    navigator: { userAgent: "node" },
    console: console,
    setTimeout: setTimeout,
    clearTimeout: clearTimeout,
    URLSearchParams: URLSearchParams,
    CustomEvent: win.CustomEvent,
    sessionStorage: win.sessionStorage,
    localStorage: win.localStorage,
  };
  if (win.location) sandbox.location = win.location;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(BOOT, "utf8"), sandbox, { filename: BOOT });
  dom.domReady.forEach(function (fn) { fn({ type: "DOMContentLoaded" }); });
  return dom;
}

function activePage(dom) {
  const active = PAGE_IDS.filter(function (id) { return dom.ids[id].classList.contains("active"); });
  return active.length === 1 ? active[0] : active.join("+") || "(none)";
}

function subNode(dom, page, sub) {
  return dom.subs.filter(function (s) {
    return s.getAttribute("data-page") === page && s.getAttribute("data-sub") === sub;
  })[0] || null;
}

function groupNode(dom, name) {
  return dom.groups.filter(function (g) { return g.getAttribute("data-group") === name; })[0] || null;
}

// --------------------------------------------------------------------------
// 1. 没有 view：默认页不动
// --------------------------------------------------------------------------
(function () {
  const dom = boot("");
  eq("没有 view 落订单页", activePage(dom), "overview");
  check("没有 view 时 agents 页不 active", !dom.ids["agents"].classList.contains("active"));
})();

// --------------------------------------------------------------------------
// 2. ?view=pairing —— 聊天窗口发出去的那条（主人去批准配对）
// --------------------------------------------------------------------------
(function () {
  const dom = boot("?view=pairing");
  eq("?view=pairing 落 #agents 页", activePage(dom), "agents");
  const connect = subNode(dom, "agents", "connect");
  check("?view=pairing 高亮「接入一个 Agent」子项", !!(connect && connect.classList.contains("active")));
  const g = groupNode(dom, "agents");
  // 主身份口径下侧栏本来就收窄（applyNavScope 不画 agents 组），所以这里不断言
  // 分组展开 —— 深链的落点是「页 + 子项高亮」，跟侧栏可见性是两回事。
  check("?view=pairing 父项标成 parent-active", !!(g && g._main.classList.contains("parent-active")));
  const mine = subNode(dom, "agents", "mine");
  check("?view=pairing 不把「我的助理 Agent」也点亮", !!(mine && !mine.classList.contains("active")));
})();

// 2b. 助理身份口径：侧栏里 agent 接入本来就看得见，分组要跟着展开
(function () {
  const dom = boot("?view=pairing", { identityClass: "individual" });
  eq("助理身份 ?view=pairing 仍落 #agents 页", activePage(dom), "agents");
  const g = groupNode(dom, "agents");
  check("助理身份下 agents 分组没有被人为藏掉", !!(g && !g.classList.contains("nav-scope-hidden")));
  check("助理身份下 agents 分组展开", !!(g && g.classList.contains("open")));
  const connect = subNode(dom, "agents", "connect");
  check("助理身份下「接入一个 Agent」子项高亮", !!(connect && connect.classList.contains("active")));
})();

// --------------------------------------------------------------------------
// 3. ?view=agents —— 我的助理 Agent
// --------------------------------------------------------------------------
(function () {
  const dom = boot("?view=agents");
  eq("?view=agents 落 #agents 页", activePage(dom), "agents");
  const mine = subNode(dom, "agents", "mine");
  check("?view=agents 高亮「我的助理 Agent」子项", !!(mine && mine.classList.contains("active")));
  const connect = subNode(dom, "agents", "connect");
  check("?view=agents 不把「接入一个 Agent」也点亮", !!(connect && !connect.classList.contains("active")));
})();

// --------------------------------------------------------------------------
// 4. 认不出的 view / 别的查询串：一律不跳（地址栏不是命令通道）
// --------------------------------------------------------------------------
(function () {
  eq("认不出的 view 落订单页", activePage(boot("?view=../../etc/passwd")), "overview");
  eq("别的查询串落订单页", activePage(boot("?view=&pair=ABCD-1234")), "overview");
  eq("只有 pair 时落订单页（那条链接由 cyber-pairing.js 自己收）", activePage(boot("?pair=ABCD-1234")), "overview");
  eq("view 大小写不认（只有小写是口径）", activePage(boot("?view=Pairing")), "overview");
})();

// --------------------------------------------------------------------------
// 5. 最省事的宿主：没有 location 也不能炸
// --------------------------------------------------------------------------
(function () {
  let dom = null;
  try {
    dom = boot("", { noLocation: true });
  } catch (e) {
    check("没有 location 时模块仍能加载", false, String(e && e.message ? e.message : e));
    return;
  }
  eq("没有 location 时落订单页", activePage(dom), "overview");
})();

if (failures) {
  console.error("FAILED: " + failures + "/" + checks);
  process.exit(1);
}
console.log("OK   console view landing: " + checks + " checks");
