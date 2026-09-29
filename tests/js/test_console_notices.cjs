/**
 * 站内提醒这一行的文字（apps/console/scripts/cyber-unbind-keys.js 里的 noticeText）。
 *
 * 两条都要钉住：
 *
 *   1. **切了语言就不许留中文**。「部署后的资金回归没通过：{0}」是带变量的整句，
 *      DOM 翻译引擎只认整句，所以这句必须落在五份词表里（en/ja/ko/es-AR/es-SV），
 *      而且渲染出来不能再是那句中文（真机踩过：红点亮了，点开还是中文）。
 *   2. 提醒要真的画进卡片。文案对、没接线，用户照样看不见。
 *
 * 跑法：node tests/js/test_console_notices.cjs
 */
"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(__dirname, "..", "..");
const SRC = path.join(ROOT, "apps", "console", "scripts", "cyber-unbind-keys.js");
const CODE = fs.readFileSync(SRC, "utf8");
const SRC_TEXT = "部署后的资金回归没通过：{0}";
const SUMMARY = "dispute=2 fail";
//: 不含中文书写系统的语言：画面上一个汉字/假名/谚文都不该出现。
const LATIN = ["en", "es-AR", "es-SV"];
const ALL = ["en", "ja", "ko", "es-AR", "es-SV"];

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

function hasCjk(text) {
  return /[\u2e80-\u303f\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uff00-\uffef]/.test(text);
}

function loadPhrase(lang) {
  const file = path.join(ROOT, "apps", "console", "scripts", "i18n-phrase", lang + ".js");
  const sandbox = { window: {} };
  vm.runInNewContext(fs.readFileSync(file, "utf8"), sandbox, { filename: file });
  return (sandbox.window.CYBER_I18N_PHRASE || {})[lang] || {};
}

function liText(html) {
  const m = /<li>([\s\S]*?)<\/li>/.exec(html);
  return m ? m[1] : "";
}

function el() {
  return {
    innerHTML: "",
    attrs: {},
    cls: {},
    classList: {
      toggle: function (name, on) {
        this._c = this._c || {};
        this._c[name] = !!on;
      },
    },
    setAttribute: function (k, v) {
      this.attrs[k] = v;
    },
    removeAttribute: function (k) {
      delete this.attrs[k];
    },
    getAttribute: function (k) {
      return this.attrs[k];
    },
    closest: function () {
      return null;
    },
  };
}

function makeEnv(lang, phrase) {
  const nodes = { "bound-keys": el(), "ag-bound-keys": el() };
  const nav = el();
  const sandbox = {
    KARMA_IDENTITY_ID: "kid_test",
    KARMA_ACCESS_TOKEN: "tok",
    console: console,
    setTimeout: setTimeout,
    setInterval: function () {
      return 0;
    },
    confirm: function () {
      return false;
    },
    document: {
      readyState: "complete",
      addEventListener: function () {},
      querySelector: function (sel) {
        return sel.indexOf("settings") >= 0 ? nav : null;
      },
      getElementById: function (id) {
        return nodes[id] || null;
      },
    },
    karmaRuntimeApi: {
      runtimeListBoundKeys: function () {
        return Promise.resolve({ keys: [] });
      },
      runtimeListNotices: function () {
        return Promise.resolve({
          unread: 1,
          notices: [{ kind: "money_regression_failed", read: false, payload: { summary: SUMMARY } }],
        });
      },
    },
  };
  sandbox.window = sandbox;
  sandbox.CYBER_I18N = {
    getLang: function () {
      return lang === "zh" ? "zh-CN" : lang;
    },
    T: function (zh) {
      if (lang === "zh") return zh;
      return Object.prototype.hasOwnProperty.call(phrase, zh) ? phrase[zh] : zh;
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
  return { sandbox: sandbox, nodes: nodes, nav: nav };
}

async function rendered(lang) {
  const env = makeEnv(lang, lang === "zh" ? {} : loadPhrase(lang));
  await env.sandbox.KarmaUnbindKeys.refresh();
  const html = env.nodes["bound-keys"].innerHTML;
  return { env: env, html: html, line: liText(html) };
}

async function main() {
  // (1) 中文页面：整句带着 summary 落下来，未读有标记
  const zh = await rendered("zh");
  check("中文页面画出这一条提醒", zh.line.indexOf("部署后的资金回归没通过：" + SUMMARY) >= 0, zh.html.slice(0, 300));
  check("未读会有标记", zh.line.indexOf("未读") >= 0, zh.line);

  // (2) 五份词表都要有这句，而且都不是那句中文
  ALL.forEach(function (lang) {
    const pack = loadPhrase(lang);
    check(lang + " 词表里有这句", Object.prototype.hasOwnProperty.call(pack, SRC_TEXT), "缺 " + SRC_TEXT);
    const translated = pack[SRC_TEXT] || "";
    check(lang + " 不是原句照抄", translated !== "" && translated !== SRC_TEXT, translated);
  });

  // (3) 每种语言渲染出来：占位符被换成 summary，且不留中文
  const expect = {
    en: "The post-deploy money-path regression failed: " + SUMMARY,
    ja: "デプロイ後の資金パス回帰テストが失敗しました：" + SUMMARY,
    ko: "배포 후 자금 경로 회귀 테스트가 실패했습니다: " + SUMMARY,
    "es-AR": "La regresión de la ruta del dinero tras el despliegue falló: " + SUMMARY,
    "es-SV": "La regresión de la ruta del dinero tras el despliegue falló: " + SUMMARY,
  };
  for (const lang of ALL) {
    const out = await rendered(lang);
    check(lang + " 页面画出译文", out.line.indexOf(expect[lang]) >= 0, out.line);
    check(lang + " 不再出现那句中文", out.line.indexOf(SRC_TEXT.replace("{0}", "")) < 0, out.line);
    if (LATIN.indexOf(lang) >= 0) {
      check(lang + " 页面不留中文", !hasCjk(out.line), out.line);
    }
  }

  // (4) 红点：未读时要挂到侧栏「设置」上
  eq("侧栏红点挂上了", !!(zh.env.nav.classList._c || {})["has-notice"], true);

  console.log((failures ? "FAILED " : "ok  ") + "console notices: " + (checks - failures) + "/" + checks + " checks passed");
  process.exit(failures ? 1 : 0);
}

main().catch(function (e) {
  console.error(e);
  process.exit(2);
});
