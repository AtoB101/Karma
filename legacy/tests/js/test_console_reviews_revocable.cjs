/**
 * 复核台「可撤销的认证」这一屏（apps/console/scripts/cyber-reviews.js）。
 *
 * 认证是终态，撤销是唯一出口（复核员两人 / 运维白名单单人）。服务端有 13 条单测
 * 盯着状态机，但**画出来长什么样**没人盯：切了语言还留中文、按钮还是中文、理由
 * 不写就发请求 —— 这三样都只有真跑一遍渲染才看得见。
 *
 * 翻译机制：模板里的中文原文就是查表键。经 T()/Tf() 的当场翻；直接写进 DOM 的
 * （say() 的状态行、placeholder 之类）交给 i18n-cyber.js 的遍历 + MutationObserver
 * 翻（ATTRS 含 placeholder）。所以这里两条都要钉：**原文在页面里** 且 **五份词表
 * 都有这条译文**，少一条非中文页面就会留中文。
 *
 * 跑法：node tests/js/test_console_reviews_revocable.cjs
 */
"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(__dirname, "..", "..");
const SRC = path.join(ROOT, "apps", "console", "scripts", "cyber-reviews.js");
const CODE = fs.readFileSync(SRC, "utf8");
const ALL = ["en", "ja", "ko", "es-AR", "es-SV"];
//: 一个字都不该出现汉字的语言（日语另算 —— 汉字是它自己的书写系统）。
const LATIN = ["en", "ko", "es-AR", "es-SV"];

// 这一屏新加的整句（中文原文 = 查表键）。带 {n} 的按整句模板查。
const K_MODE = "可撤销的认证";
const K_BACK = "返回待办";
const K_START = "发起撤销";
const K_CONFIRM = "确认撤销";
const K_TIME = "认证时间 {0}";
const K_COUNTS = "已认证可撤销 {0} 条（主体 {1} · 子身份 KYC {2}）";
const K_SKIPPED = "已自动跳过本人认证 {0} 条";
const K_REASON = "撤销理由（至少 10 个字，被撤销方与消费者都会看到）";
const K_NEED = "撤销要写理由（至少 10 个字）：被撤销方与消费者都会看到";
const K_RECORDED = "撤销申请已记录：还需要另一名复核员确认";
const K_OK = "撤销成功：认证已降为「已驳回」";
const K_EMPTY = "现在没有可撤销的认证。";
const K_DENY = "没有权限：这个身份还不是复核岗（verifier）。";
//: 新加的整句 —— 五份词表都必须有译文，否则非中文页面留中文。
const NEW_SENTENCES = [K_MODE, K_BACK, K_START, K_CONFIRM, K_TIME, K_COUNTS, K_SKIPPED,
  K_REASON, K_NEED, K_RECORDED, K_OK, K_EMPTY];

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

const HAN = /[\u3400-\u4dbf\u4e00-\u9fff]/;

function hasHan(text) {
  return HAN.test(String(text || ""));
}

function loadPhrase(lang) {
  const file = path.join(ROOT, "apps", "console", "scripts", "i18n-phrase", lang + ".js");
  const sandbox = { window: {} };
  vm.runInNewContext(fs.readFileSync(file, "utf8"), sandbox, { filename: file });
  return (sandbox.window.CYBER_I18N_PHRASE || {})[lang] || {};
}

function makeEl(id) {
  const set = new Set();
  return {
    id: id,
    innerHTML: "",
    textContent: "",
    value: "",
    hidden: false,
    attrs: {},
    listeners: {},
    classList: {
      add: function (n) { set.add(n); },
      remove: function (n) { set.delete(n); },
      contains: function (n) { return set.has(n); },
      toggle: function (n, on) { if (on) set.add(n); else set.delete(n); },
    },
    addEventListener: function (name, fn) {
      this.listeners[name] = this.listeners[name] || [];
      this.listeners[name].push(fn);
    },
    dispatch: function (name, ev) {
      (this.listeners[name] || []).forEach(function (fn) { fn(ev); });
    },
    getAttribute: function (k) { return this.attrs[k]; },
    setAttribute: function (k, v) { this.attrs[k] = v; },
  };
}

function tick(ms) {
  return new Promise(function (r) { setTimeout(r, ms == null ? 30 : ms); });
}

function makeEnv(lang, opts) {
  opts = opts || {};
  const nodes = {};
  ["reviews", "rv-list", "rv-counts", "rv-mode", "rv-state", "rv-deny", "rv-kind", "rv-refresh"].forEach(
    function (id) { nodes[id] = makeEl(id); }
  );
  nodes.reviews.classList.add("active");

  const pack = lang === "zh" ? {} : loadPhrase(lang);
  const calls = { fetch: 0, post: [] };
  const api = {
    headers: function () { return { "Content-Type": "application/json" }; },
    karmaFetch: function () {
      calls.fetch += 1;
      return Promise.resolve(opts.payload || { items: [], counts: {}, skipped_own: 0 });
    },
    jsonPost: function (p, body) {
      calls.post.push({ path: p, body: body });
      return Promise.resolve(opts.postResult || { revoked: false });
    },
  };

  const sandbox = {
    console: console,
    setTimeout: setTimeout,
    clearTimeout: clearTimeout,
    confirm: function () { return opts.confirm === true; },
    document: {
      readyState: "complete",
      addEventListener: function () {},
      getElementById: function (id) { return nodes[id] || null; },
      querySelector: function (sel) { return (opts.query || {})[sel] || null; },
    },
  };
  sandbox.window = sandbox;
  sandbox.KARMA_IDENTITY_ID = "kid_test";
  sandbox.KARMA_ACCESS_TOKEN = "tok";
  sandbox.KarmaConsoleCaps = {
    get: function () { return { can_open_review_queue: opts.canOpen !== false }; },
  };
  sandbox.cyberKarmaApi = api;
  sandbox.CYBER_I18N = {
    T: function (zh) {
      if (lang === "zh") return zh;
      return Object.prototype.hasOwnProperty.call(pack, zh) ? pack[zh] : zh;
    },
    Tf: function (zh) {
      let out = sandbox.CYBER_I18N.T(zh);
      for (let i = 1; i < arguments.length; i += 1) {
        out = out.split("{" + (i - 1) + "}").join(arguments[i] == null ? "" : String(arguments[i]));
      }
      return out;
    },
  };

  vm.runInNewContext(CODE, sandbox, { filename: SRC });
  return { sandbox: sandbox, nodes: nodes, api: api, calls: calls, pack: pack, lang: lang };
}

const ITEMS = {
  items: [
    {
      kind: "entity_verification",
      target_id: "ent_001",
      display_name: "Acme Ltd",
      verified_at: "2026-10-01T00:00:00Z",
      can_confirm: false,
      pending_revocation: {
        proposed_by: "kid_aaaaaaaaaaaa",
        reason: "auditor found a forged business licence",
      },
    },
    {
      kind: "role_profile_kyc",
      target_id: "rp_002",
      display_name: "claw-002",
      verified_at: "2026-10-02T00:00:00Z",
      can_confirm: true,
      pending_revocation: null,
    },
  ],
  counts: { entity_verification: 1, role_profile_kyc: 1 },
  skipped_own: 3,
};

/** 从渲染出来的 HTML 里取某个撤销按钮上的字。 */
function revokeButtonLabel(html, id) {
  const m = new RegExp('data-rv-revoke="' + id + '"[^>]*>([^<]*)<').exec(html);
  return m ? m[1] : "";
}

/** 模拟点第 id 条的撤销按钮：closest 只认撤销选择器。 */
function clickRevoke(env, id, confirming) {
  const btn = {
    getAttribute: function (k) {
      if (k === "data-rv-revoke") return id;
      if (k === "data-rv-confirm") return confirming ? "1" : "0";
      return null;
    },
  };
  env.nodes["rv-list"].dispatch("click", {
    target: {
      closest: function (sel) { return sel === "[data-rv-revoke]" ? btn : null; },
    },
  });
}

async function revocable(env) {
  env.sandbox.KarmaReviewsConsole.state.mode = "revocable";
  await env.sandbox.KarmaReviewsConsole.refresh();
  return env.nodes["rv-list"].innerHTML;
}

async function main() {
  // (0) 新加的整句在五份词表里都有译文，而且都不是原句
  {
    const packs = {};
    ALL.forEach(function (lang) { packs[lang] = loadPhrase(lang); });
    NEW_SENTENCES.forEach(function (src) {
      ALL.forEach(function (lang) {
        const val = packs[lang][src];
        check(lang + " 词表里有「" + src.slice(0, 12) + "…」", typeof val === "string" && val.length > 0, val);
        check(lang + " 不是原句照抄", val && val !== src, val);
        if (LATIN.indexOf(lang) >= 0) {
          check(lang + " 译文不留汉字", val && !hasHan(val), val);
        }
      });
    });
  }

  // (1) 五种语言：切到「可撤销的认证」，按钮 / 计数 / 标题行都跟着语言走
  for (const lang of ALL) {
    const env = makeEnv(lang, { payload: ITEMS });
    const html = await revocable(env);
    const pack = env.pack;
    eq(lang + " 模式按钮 = 返回待办", env.nodes["rv-mode"].textContent, pack[K_BACK]);
    check(lang + " 计数行带条数 2", env.nodes["rv-counts"].textContent.indexOf("2") >= 0, env.nodes["rv-counts"].textContent);
    check(lang + " 画出了两条", (html.match(/data-rv-item=/g) || []).length === 2, html.slice(0, 200));
    eq(lang + " 未确认项的按钮 = 发起撤销", revokeButtonLabel(html, "ent_001"), pack[K_START]);
    eq(lang + " 可确认项的按钮 = 确认撤销", revokeButtonLabel(html, "rp_002"), pack[K_CONFIRM]);
    check(
      lang + " 认证时间翻成整句",
      html.indexOf(pack[K_TIME].replace("{0}", "").trim()) >= 0,
      html.slice(0, 500)
    );
    check(lang + " 模板里带着理由提示的原文（引擎按它查表）", html.indexOf(K_REASON) >= 0, html.slice(0, 600));
    if (LATIN.indexOf(lang) >= 0) {
      check(lang + " 模式按钮不留中文", !hasHan(env.nodes["rv-mode"].textContent), env.nodes["rv-mode"].textContent);
      check(lang + " 计数行不留中文", !hasHan(env.nodes["rv-counts"].textContent), env.nodes["rv-counts"].textContent);
      check(lang + " 按钮上的字不留中文", !hasHan(pack[K_START]) && !hasHan(pack[K_CONFIRM]), pack[K_START] + " / " + pack[K_CONFIRM]);
    }
  }

  // (2) 中文页面：没有语言包时原样是中文（基线）
  {
    const env = makeEnv("zh", { payload: ITEMS });
    await revocable(env);
    eq("zh 模式按钮 = 中文原文", env.nodes["rv-mode"].textContent, K_BACK);
    eq("zh 未确认项的按钮 = 发起撤销", revokeButtonLabel(env.nodes["rv-list"].innerHTML, "ent_001"), K_START);
  }

  // (3) 空列表：给一句人话，不是空白
  {
    const env = makeEnv("en", { payload: { items: [], counts: {}, skipped_own: 0 } });
    const html = await revocable(env);
    check("空列表给出提示", html.indexOf(env.pack[K_EMPTY]) >= 0, html.slice(0, 200));
  }

  // (4) 理由太短：不发请求，给出提示（提示原文落 DOM，译文由词表兜底）
  {
    const status = makeEl("st");
    const reason = makeEl("rs");
    reason.value = "太短";
    const env = makeEnv("en", {
      payload: ITEMS,
      query: {
        '[data-rv-status="ent_001"]': status,
        '[data-rv-reason="ent_001"]': reason,
      },
    });
    await revocable(env);
    clickRevoke(env, "ent_001", false);
    await tick();
    eq("理由太短不发请求", env.calls.post.length, 0);
    eq("理由太短给提示", status.textContent, K_NEED);
    check("理由太短的提示有译文", typeof env.pack[K_NEED] === "string" && env.pack[K_NEED] !== K_NEED, env.pack[K_NEED]);
  }

  // (5) 发起成功：打到主体认证的撤销接口，提示「还要另一名复核员确认」
  {
    const status = makeEl("st");
    const reason = makeEl("rs");
    reason.value = "auditor found a forged business licence";
    const env = makeEnv("en", {
      payload: ITEMS,
      postResult: { revoked: false },
      query: {
        '[data-rv-status="ent_001"]': status,
        '[data-rv-reason="ent_001"]': reason,
      },
    });
    await revocable(env);
    const before = env.calls.fetch;
    clickRevoke(env, "ent_001", false);
    await tick(60);
    eq("发起了 1 次撤销", env.calls.post.length, 1);
    eq(
      "主体认证撤销接口",
      env.calls.post[0].path,
      "/v1/identity/ent_001/entity-verification/revoke"
    );
    eq("带上了理由", env.calls.post[0].body.reason, "auditor found a forged business licence");
    eq("提示要另一名复核员确认", status.textContent, K_RECORDED);
    check("撤销后刷新了列表", env.calls.fetch > before, before + " -> " + env.calls.fetch);
  }

  // (6) 确认成功：走子身份 KYC 的撤销接口，提示已降为「已驳回」
  {
    const status = makeEl("st");
    const reason = makeEl("rs");
    reason.value = "second reviewer confirms the audit finding";
    const env = makeEnv("en", {
      payload: ITEMS,
      postResult: { revoked: true },
      confirm: true,
      query: {
        '[data-rv-status="rp_002"]': status,
        '[data-rv-reason="rp_002"]': reason,
      },
    });
    await revocable(env);
    clickRevoke(env, "rp_002", true);
    await tick(60);
    eq("确认路径发起了 1 次撤销", env.calls.post.length, 1);
    eq(
      "子身份 KYC 撤销接口",
      env.calls.post[0].path,
      "/v1/identity/role-profiles/rp_002/kyc/revoke"
    );
    eq("确认成功的提示", status.textContent, K_OK);
  }

  // (7) 确认框点了「取消」：一个请求都不发
  {
    const status = makeEl("st");
    const reason = makeEl("rs");
    reason.value = "second reviewer confirms the audit finding";
    const env = makeEnv("en", {
      payload: ITEMS,
      postResult: { revoked: true },
      confirm: false,
      query: {
        '[data-rv-status="rp_002"]': status,
        '[data-rv-reason="rp_002"]': reason,
      },
    });
    await revocable(env);
    clickRevoke(env, "rp_002", true);
    await tick(60);
    eq("点了取消就不发请求", env.calls.post.length, 0);
    eq("点了取消给出「已取消」", status.textContent, "已取消");
  }

  // (8) 没有复核岗：不给画列表，给一句人话（不是空白）
  {
    const env = makeEnv("en", { payload: ITEMS, canOpen: false });
    await revocable(env);
    check(
      "非复核岗给出无权限提示",
      env.nodes["rv-state"].textContent.indexOf(env.pack[K_DENY]) >= 0,
      env.nodes["rv-state"].textContent
    );
    eq("非复核岗不发请求", env.calls.fetch, 0);
  }

  console.log((failures ? "FAILED " : "ok  ") + "console reviews revocable: " + (checks - failures) + "/" + checks + " checks passed");
  process.exit(failures ? 1 : 0);
}

main().catch(function (e) {
  console.error(e);
  process.exit(2);
});
