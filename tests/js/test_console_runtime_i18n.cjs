/**
 * 操作台 · 全站「运行期拼出来的中文」门禁。
 *
 * 为什么单独立一条
 * ----------------
 * 操作台有四十来个脚本，文案大半不是写在 HTML 里的，是运行期拼出来的：
 *
 *     say(node, "已加入 " + dev.materials.length + " 份", null);
 *     sub += ' · <span class="err">待补齐：' + esc(gaps) + "</span>";
 *     "<li>· 承诺 #" + x.bill_id + " · 未使用 " + fmtNum(x.free) + " USDC</li>"
 *
 * 整句在源码里根本不存在，只 grep 中文串查不到；而它又只在走到那个状态时才渲染。
 * 后果就是「切了英文界面，某一块还是中文」—— 用户已经踩过好几轮。
 *
 * 这一条跟 tests/js/test_console_agent_onestop_i18n.cjs 用**同一份**静态口径
 * （tests/js/lib/console_i18n_static.cjs），但覆盖范围从「一条龙 6 个脚本」扩到
 * **整个操作台**：任何脚本里拼出来的中文，五门语言下都不许再冒出来。
 *
 * 口径（跟渲染器 translateTextNode 一致）
 * --------------------------------------
 *   · 中文字面量按「+ 拼接」还原成运行时那句，再按浏览器实际形成的文本节点切开；
 *   · 先 lookup、查不到再 lookupLoose 兜底；
 *   · 译文里还留汉字（日语除外）、日语里留着简体中文词，都算漏；
 *   · indexOf / split / startsWith 这类「拿去比对的串」不算文案，跳过；
 *   · tr(key, "中文兜底") / addHead / addPickerHead 走核心包：key 得有译文，
 *     中文兜底也得在词表里（核心包查不到时界面就回落到它）。
 *
 * 跑法：node tests/js/test_console_runtime_i18n.cjs
 */
"use strict";

const fs = require("fs");
const path = require("path");
const S = require("./lib/console_i18n_static.cjs");

const ROOT = path.resolve(__dirname, "..", "..");
const SCRIPTS = path.join(ROOT, "apps", "console", "scripts");
const LANGS = S.LANGS;

/**
 * 这三个不是界面文案宿主：
 *   i18n-cyber.js        —— 引擎本身（词表就在里面）
 *   lang-select.js       —— 语言下拉（原生 <select>，文案由核心包管）
 *   background-globe.js  —— 纯 canvas / WebGL 背景，没有文案
 * 其余脚本一个不落，全是运行期往 DOM 里写句子的人。
 */
const SKIP = { "i18n-cyber.js": 1, "lang-select.js": 1, "background-globe.js": 1 };

const FILES = fs.readdirSync(SCRIPTS)
  .filter(function (f) { return f.endsWith(".js") && !SKIP[f]; })
  .sort();

/** 扫到的句数下限：扫描器一旦被改坏（正则不匹配了 → 一句都扫不到 → 「全都过」），这条会先炸。 */
const MIN_PIECES = 1200;

async function main() {
  const seen = new Set();
  const bad = new Map();
  let checks = 0;

  const res = await S.scanFiles(FILES, S.createEngine(), function (hit) {
    const id = hit.file + " [" + hit.lang + "] " + hit.piece;
    if (seen.has(id)) return;
    seen.add(id);
    checks += 1;
    if (!hit.bad) return;
    bad.set(id, hit.bad);
    console.error("FAIL: 全站静态 " + hit.file + " [" + hit.lang + "] "
      + hit.piece.slice(0, 60) + " -- " + hit.bad + "  <= " + hit.piece.slice(0, 90));
  });

  console.log("全操作台静态扫描：" + res.files + " 个脚本 × " + LANGS.length + " 门语言，"
    + "检查 " + checks + " 句（去重后），扫到 " + res.pieces + " 句");

  let failures = bad.size;
  if (res.pieces < MIN_PIECES) {
    failures += 1;
    console.error("FAIL: 扫描真的扫到了东西（不是空跑）-- pieces=" + res.pieces + " < " + MIN_PIECES);
  }

  console.log((failures ? "FAILED " : "ok  ") + "console runtime i18n: "
    + (checks - bad.size) + "/" + checks + " checks passed，漏译 " + bad.size + " 句");
  process.exit(failures ? 1 : 0);
}

main().catch(function (e) {
  console.error(e);
  process.exit(2);
});
