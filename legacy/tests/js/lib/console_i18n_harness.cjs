/**
 * 操作台 i18n 审计用的小沙箱（tests/js/test_console_agent_onestop_i18n.cjs 专用）。
 *
 * 为什么要自己起一手 DOM：这条链上的文案大半不是写在 HTML 里的，是运行期拼出来的
 * （"剩余 " + mm + ":" + ss + " · 交给 agent 后它就能领凭据了"）。
 * 只看源码里的整句字面量，会漏掉「拼出来才成形」的那些 —— 漏一条，非中文界面上就是一句中文。
 *
 * 做法：用 vm 起一个沙箱 + 假 DOM，head.appendChild(<script src>)
 * 真的去读本地脚本并执行，这样跑的就是上线的那份代码。
 */
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(__dirname, "..", "..", "..");
const CONSOLE = path.join(ROOT, "apps", "console");
const SCRIPTS = path.join(CONSOLE, "scripts");
const LANGS = ["en", "ja", "ko", "es-AR", "es-SV"];

function makeEl(tag) {
  const el = {
    tagName: (tag || "div").toUpperCase(), id: "", textContent: "", value: "", hidden: false,
    attrs: {}, handlers: {}, children: [], style: {},
    addEventListener(e, f) { (this.handlers[e] = this.handlers[e] || []).push(f); },
    removeEventListener() {},
    setAttribute(k, v) { this.attrs[k] = String(v); },
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; },
    removeAttribute(k) { delete this.attrs[k]; },
    hasAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k); },
    classList: { _s: {}, toggle(c, on) { this._s[c] = !!on; }, add(c) { this._s[c] = true; }, remove(c) { this._s[c] = false; }, contains(c) { return !!this._s[c]; } },
    querySelector() { return null; }, querySelectorAll() { return []; },
    appendChild(c) { this.children.push(c); return c; }, insertBefore(c) { return c; }, removeChild(c) { return c; },
    closest() { return null; }, focus() {}, scrollIntoView() {}, dispatchEvent() { return true; },
  };
  let html = "";
  Object.defineProperty(el, "innerHTML", { get() { return html; }, set(v) { html = String(v); } });
  return el;
}

function boot(lang, bag) {
  const nodes = {};
  const byId = (id) => (nodes[id] = nodes[id] || makeEl("div"));
  const head = makeEl("head"), body = makeEl("body");
  let cur = lang;
  const localStorage = {
    getItem: (k) => (k === "karma_cyber_lang" ? cur : null),
    setItem: (k, v) => { if (k === "karma_cyber_lang") cur = String(v); },
    removeItem() {},
  };
  const document = {
    readyState: "complete", getElementById: byId, createElement: (t) => makeEl(t),
    querySelector: () => null, querySelectorAll: () => [],
    addEventListener: () => {}, removeEventListener: () => {},
    head, body, documentElement: makeEl("html"), dispatchEvent: () => true,
  };
  const window = Object.assign({
    document, localStorage, navigator: { languages: [lang], language: lang }, location: { search: "" },
  }, bag);
  window.window = window;
  const sandbox = {
    window, document, localStorage, console, setTimeout, clearTimeout, queueMicrotask,
    setInterval: () => 0, clearInterval: () => {},
    CustomEvent: function (t) { this.type = t; },
    navigator: window.navigator,
    NodeFilter: { SHOW_TEXT: 4 },
    MutationObserver: function () { this.observe = () => {}; this.disconnect = () => {}; },
  };
  sandbox.globalThis = sandbox;
  head.appendChild = function (tag) {
    if (tag && tag.src) {
      const p = path.join(CONSOLE, String(tag.src).split("?")[0]);
      vm.runInContext(fs.readFileSync(p, "utf8"), sandbox, { filename: p });
      if (typeof tag.onload === "function") tag.onload();
    }
    return tag;
  };
  vm.createContext(sandbox);
  const run = (f) => vm.runInContext(fs.readFileSync(path.join(SCRIPTS, f), "utf8"), sandbox, { filename: f });
  run("i18n-cyber.js");
  return { sandbox, window, byId, nodes, run, document, head, body };
}
/* ---------------------------------------------------------------- 抽句与判定 */

const SKIP_TAGS = { SCRIPT: 1, STYLE: 1, NOSCRIPT: 1, TEXTAREA: 1, CODE: 1, PRE: 1 };
const ATTRS = ["placeholder", "title", "aria-label", "alt"];

function unescapeHtml(s) {
  return s
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&");
}

/**
 * 按 i18n 引擎的规矩，从一段 HTML 里抽出「会被翻的那几句」：
 * SCRIPT/STYLE/NOSCRIPT/TEXTAREA/CODE/PRE 里的不算（里面是数据），
 * 带 data-i18n* 的交给核心包、phrase 引擎不看；placeholder/title/aria-label/alt 照收。
 */
function harvest(html) {
  const out = [];
  const stack = [];
  let i = 0;
  const push = (t) => {
    if (!t) return;
    if (stack.some((f) => f.skipCore || (SKIP_TAGS[f.name] && !f.phrase))) return;
    const s = t.replace(/\s+/g, " ").trim();
    if (s) out.push(unescapeHtml(s));
  };
  while (i < html.length) {
    const lt = html.indexOf("<", i);
    if (lt < 0) { push(html.slice(i)); break; }
    push(html.slice(i, lt));
    const gt = html.indexOf(">", lt);
    if (gt < 0) break;
    const raw = html.slice(lt + 1, gt);
    if (raw[0] === "/") {
      const name = raw.slice(1).trim().toUpperCase();
      for (let k = stack.length - 1; k >= 0; k -= 1) {
        if (stack[k].name === name) { stack.length = k; break; }
      }
    } else if (raw && raw[0] !== "!") {
      const name = raw.split(/[\s/>]/)[0].toUpperCase();
      const selfClose = /\/\s*$/.test(raw) || ATTRS.concat(["br", "img", "input", "hr", "meta", "link"]).indexOf(name.toLowerCase()) >= 0;
      const attrs = {};
      const re = /([a-zA-Z-]+)\s*=\s*"([^"]*)"/g;
      let m;
      while ((m = re.exec(raw))) attrs[m[1].toLowerCase()] = m[2];
      if (attrs["data-i18n"] || attrs["data-i18n-skip"] || attrs["data-i18n-placeholder"]) {
        stack.push({ name, skipCore: true });
      } else {
        ATTRS.forEach((a) => { if (attrs[a]) push(attrs[a]); });
        if (!selfClose) stack.push({ name, phrase: !!attrs["data-i18n-phrase"] });
      }
    }
    i = gt + 1;
  }
  return out;
}

/**
 * 「这句话在界面上到底翻没翻」—— 口径必须跟渲染器一致（translateTextNode）：
 * 先整串 lookup，查不到再走 lookupLoose 兜底。少了那条兜底，会把
 * 「读取失败：boom」这种「词表里有『读取失败』、尾巴是动态数据」的句子误判成漏译。
 */
function resolveIn(I, lang, text) {
  let out = null;
  try {
    out = I.lookup(text);
    if (out == null) out = I.lookupLoose(text);
  } catch (e) {
    return { bad: "引擎抛错：" + e.message, out: null };
  }
  return { bad: null, out };
}

module.exports = { boot, makeEl, LANGS, CONSOLE, SCRIPTS, harvest, resolveIn, unescapeHtml };
