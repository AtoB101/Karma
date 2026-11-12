/**
 * 「最近调用」面板（apps/console/scripts/cyber-key-calls.js）的行为测试。
 *
 * 两条都是真机上踩出来的，各写一条钉住：
 *
 *   1. **切语言要跟着走**。面板里那一行是拼出来的（动作 + 结果 + 金额 + 时间），
 *      DOM 翻译引擎只认得整句，认不出带变量的句子 —— 切到英文后按钮翻了、行还是中文。
 *      所以面板必须自己在 karma-lang-changed 上重画。
 *   2. **prune 必须按宿主**。交付包里展开的钥匙本来就不在「已绑定钥匙」那份清单里，
 *      而那边每 60 秒轮询一次 —— 用别人的清单去 prune，就会把人家刚展开的面板关掉。
 *
 * 跑法：node tests/js/test_key_calls_panel.cjs
 */
"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const SRC = path.resolve(__dirname, "..", "..", "apps", "console", "scripts", "cyber-key-calls.js");
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

const EN = {
  "成功": "Succeeded",
  "被拒（HTTP {0}）": "Rejected (HTTP {0})",
  "异常（HTTP {0}）": "Failed (HTTP {0})",
  " · 金额 {0} USDC": " · Amount {0} USDC",
  "动作 {0} · 结果 {1}{2}{3} · 时间 {4}": "Action {0} · Result {1}{2}{3} · Time {4}",
  "最近调用记录（最新在前）": "Recent calls (newest first)",
  "查看最近调用": "Recent calls",
  "收起最近调用": "Hide recent calls",
  "正在读取调用记录…": "Loading call history…",
};

function makeEnv() {
  const listeners = {};
  const calls = [];
  const sandbox = {
    KARMA_IDENTITY_ID: "kid_test",
    LANG: "zh",
    __ext: [],
    setTimeout: setTimeout,
    console: console,
    karmaRuntimeApi: {
      runtimeKeyCalls: function (payload) {
        calls.push(payload);
        return Promise.resolve({
          calls: [
            { endpoint: "place-order", outcome: "ok", http_status: 201, amount: 0.3, detail: "", created_at: "2026-09-20T09:54:18" },
            { endpoint: "place-order", outcome: "rejected", http_status: 403, amount: 5, detail: "amount exceeds runtime key single_limit", created_at: "2026-09-20T09:43:27" },
          ],
        });
      },
    },
    document: {
      addEventListener: function (name, fn) {
        (listeners[name] = listeners[name] || []).push(fn);
      },
    },
  };
  sandbox.CYBER_I18N = {
    // 语言包懒加载：真机上「事件到了、包还没到」也会发生，面板要等它就绪再画一次。
    ensureExt: function (lang, cb) {
      sandbox.__ext.push({ lang: lang, cb: cb });
    },
    getLang: function () {
      return sandbox.LANG === "zh" ? "zh-CN" : sandbox.LANG;
    },
    T: function (zh) {
      if (sandbox.LANG === "zh") return zh;
      return Object.prototype.hasOwnProperty.call(EN, zh) ? EN[zh] : zh;
    },
    Tf: function (zh) {
      let out = sandbox.CYBER_I18N.T(zh);
      for (let i = 1; i < arguments.length; i += 1) {
        out = out.split("{" + (i - 1) + "}").join(arguments[i] == null ? "" : String(arguments[i]));
      }
      return out;
    },
  };
  sandbox.window = sandbox;
  vm.runInNewContext(CODE, sandbox, { filename: SRC });
  return { sandbox, listeners, calls };
}

function fire(listeners, name, ev) {
  (listeners[name] || []).forEach(function (fn) {
    fn(ev || {});
  });
}

async function main() {
  const env = makeEnv();
  const panel = env.sandbox.KarmaKeyCalls;
  check("模块出口 KarmaKeyCalls", !!panel);
  if (!panel) return report();

  let a = 0;
  let b = 0;
  panel.register("ag-handoff", function () {
    a += 1;
  });
  panel.register("ag-bound-keys", function () {
    b += 1;
  });

  // ① 展开：拿到这一把钥匙的记录，面板里要有那一行
  await panel.toggle("k1", "ag-handoff");
  eq("展开后 isOpen", panel.isOpen("k1"), true);
  eq("请求参数", JSON.stringify(env.calls[0]), JSON.stringify({ karma_identity_id: "kid_test", key_id: "k1", limit: 20 }));
  let html = panel.panelHtml("k1");
  check("中文页面出中文行", html.indexOf("动作 place-order · 结果 成功 · 金额 0.3 USDC · 时间 2026-09-20 09:54:18") >= 0, html.slice(0, 200));
  check("被拒的那次也要留痕", html.indexOf("被拒（HTTP 403）") >= 0 && html.indexOf("single_limit") >= 0, html.slice(0, 300));
  eq("按钮带宿主标记", panel.buttonHtml("k1", "ag-handoff").indexOf('data-key-calls-host="ag-handoff"') >= 0, true);

  // ② 别的宿主刷新自己的清单，不能把这边关掉（真机症状：切语言时面板自己塌了）
  panel.prune(["k9", "k8"], "ag-bound-keys");
  eq("别的宿主 prune 不影响这边", panel.isOpen("k1"), true);
  panel.prune(["k9", "k8"], "ag-handoff");
  eq("自己那份清单里没有才收起来", panel.isOpen("k1"), false);

  // ③ 切语言：数据不重拉，文字要变
  await panel.toggle("k1", "ag-handoff");
  env.sandbox.LANG = "en";
  const before = env.calls.length;
  fire(env.listeners, "karma-lang-changed", { detail: { lang: "en" } });
  eq("切语言不重新取数", env.calls.length, before);
  check("两个宿主都被告知重画", a > 1 && b > 0, "handoff=" + a + " bound=" + b);
  html = panel.panelHtml("k1");
  check("切到英文后行也是英文", html.indexOf("Action place-order · Result Succeeded · Amount 0.3 USDC · Time 2026-09-20 09:54:18") >= 0, html.slice(0, 220));
  // 语言包懒加载：包到了得再画一次（否则还是上一种语言）。
  eq("切语言时登记了「包就绪后重画」", env.sandbox.__ext.length, 1);
  const aBefore = a;
  if (env.sandbox.__ext[0]) env.sandbox.__ext[0].cb();
  eq("包就绪后又画了一次", a > aBefore, true);
  eq("包就绪后不重新取数", env.calls.length, before);
  check("英文页面上不留中文", !/[\u4e00-\u9fff]/.test(html.replace(/single_limit/g, "")), html.slice(0, 220));

  // ④ 钥匙没了（取消绑定 / 停用）
  panel.forget("k1");
  eq("forget 之后收起", panel.isOpen("k1"), false);
  eq("forget 之后不再重复请求缓存", Object.prototype.hasOwnProperty.call(env.calls, "k1"), false);

  report();
}

function report() {
  console.log((failures ? "FAILED " : "ok  ") + "key-calls panel: " + (checks - failures) + "/" + checks + " checks passed");
  process.exit(failures ? 1 : 0);
}

main().catch(function (e) {
  console.error(e);
  process.exit(2);
});
