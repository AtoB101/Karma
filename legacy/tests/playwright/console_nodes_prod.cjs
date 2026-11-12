/*
 * 操作台节点层 · 线上复验。
 *
 * 本机那支（console_nodes_live.cjs）证明「代码是对的」；这一支证明「发出去的那份是对的」——
 * 它不 stub 任何请求，直接打到正式域名上，所以能把「少推一个文件」「nginx 还在发旧包」
 * 「线上还是上一个版本」这类问题暴露出来。
 *
 * 与 scripts/console_bundle.py remote 的分工：那边逐字节对账（39 个文件一个不落），
 * 这边证明「真浏览器里跑得起来」。
 *
 * 跑法（默认不跑，必须显式给地址）：
 *   KARMA_PROD_URL=https://karma-network.ai/console/pages/cyber/index.html \
 *     node tests/playwright/console_nodes_prod.cjs
 *
 * 环境变量：
 *   KARMA_PROD_URL    操作台线上地址（必填）
 *   KARMA_CHROME      指定 Chromium 可执行文件
 *   KARMA_PROD_SHOTS  截图输出目录；不设就不截图
 *
 * 说明：操作台在未登录时是 gated 的（顶栏要点完身份才会露出来）。这一支塞一个
 * **假身份**把界面打开，因此会看到几条 401 —— 那是预期的，断言里只统计未捕获异常。
 */
"use strict";

const fs = require("fs");
const path = require("path");

const { NODE_SOURCES } = require("./node-layer-sources.cjs");

const RAW = process.env.KARMA_PROD_URL || "";
if (!RAW) {
  console.error("需要 KARMA_PROD_URL，例如：");
  console.error("  KARMA_PROD_URL=https://karma-network.ai/console/pages/cyber/index.html node tests/playwright/console_nodes_prod.cjs");
  process.exit(2);
}

const PAGE = RAW;
const ORIGIN = new URL(PAGE).origin;
const SHOTS = process.env.KARMA_PROD_SHOTS || "";
const LANGS = ["en", "ja", "ko", "es-AR", "es-SV"];
const ID = "kid_5f0aa8ccf7483983a8a2a5a9";
const DEAD_NODE = "https://node.example.invalid";

let checks = 0;
let failures = 0;
function check(name, cond, extra) {
  checks += 1;
  if (cond) {
    console.log("  ok   " + name);
    return;
  }
  failures += 1;
  console.log("  FAIL " + name + (extra === undefined ? "" : " -> " + JSON.stringify(extra).slice(0, 320)));
}

function chineseResidue(texts) {
  const blob = texts.join(" ");
  for (const src of NODE_SOURCES) {
    if (blob.indexOf(src) >= 0) return src;
  }
  return null;
}

function loadPack(lang) {
  const vm = require("vm");
  const packDir = path.join(__dirname, "..", "..", "apps", "console", "scripts", "i18n-phrase");
  const box = { window: {} };
  vm.createContext(box);
  vm.runInContext(fs.readFileSync(path.join(packDir, lang + ".js"), "utf8"), box);
  return box.window.CYBER_I18N_PHRASE[lang];
}

const READ = () => {
  const g = (sel) => {
    const n = document.querySelector(sel);
    return n ? n.textContent.replace(/\s+/g, " ").trim() : "";
  };
  const box = document.querySelector("[data-karma-nodes-settings]");
  return {
    chipName: g("#node-chip [data-node-name]"),
    chipMs: g("#node-chip [data-node-ms]"),
    menu: g("#node-menu"),
    menuRows: document.querySelectorAll("#node-menu .node-row").length,
    menuStatus: g("#node-menu [data-node-status]"),
    settings: box ? box.textContent.replace(/\s+/g, " ").trim() : "",
    settingsRows: document.querySelectorAll("[data-karma-nodes-settings] .node-row").length,
    endpoint: g("[data-karma-nodes-settings] .node-endpoint"),
    lsBase: localStorage.getItem("karma_cyber_api_base"),
    lsNode: localStorage.getItem("karma_console_node_id"),
    winBase: String(window.KARMA_API_BASE),
    effective: window.KarmaNodes.effectiveBase(),
    packs: Object.keys(window.CYBER_I18N_PHRASE || {}).join(","),
    phraseBase: window.CYBER_I18N.getPhraseBase ? window.CYBER_I18N.getPhraseBase() : "(none)",
    pageSample: (document.querySelector("#settings") ? "settings-on" : "settings-off"),
    chunk: [g("#node-chip"), g("#node-menu"), box ? box.textContent : "", g("#node-toast")]
      .map((s) => String(s || "").replace(/\s+/g, " ").trim())
      .filter(Boolean),
  };
};

async function switchLang(page, lang) {
  await page.evaluate((l) => {
    const sel = document.querySelector("#cyberLang");
    sel.value = l;
    sel.dispatchEvent(new Event("change", { bubbles: true }));
  }, lang);
  await page.waitForFunction((l) => window.CYBER_I18N.getLang() === l, lang, { timeout: 20000 });
  await page.waitForTimeout(800);
}

(async () => {
  let chromium;
  try {
    ({ chromium } = require("playwright"));
  } catch (e) {
    console.error("需要 playwright：npm i -D @playwright/test && npx playwright install chromium");
    process.exit(2);
  }
  if (SHOTS) fs.mkdirSync(SHOTS, { recursive: true });

  const launchOpts = process.env.KARMA_CHROME ? { executablePath: process.env.KARMA_CHROME } : {};
  const browser = await chromium.launch(launchOpts);
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 980 } });

  console.log("\n[0] 线上网关");
  const health = await ctx.request.get(ORIGIN + "/health", { timeout: 30000 });
  check(ORIGIN + "/health 返回 200", health.status() === 200, health.status());
  let healthBody = {};
  try {
    healthBody = await health.json();
  } catch (e) {}
  check("健康检查说自己 ok", healthBody.status === "ok", healthBody);
  const served = await ctx.request.get(ORIGIN + "/console/scripts/karma-nodes.js", { timeout: 30000 });
  check("线上真的发上去了节点层脚本", served.status() === 200, served.status());
  const servedText = served.ok() ? await served.text() : "";
  check("发上去的那份是节点层实现", servedText.indexOf("KarmaNodes") >= 0, servedText.slice(0, 80));
  check(
    "线上那份不再写死厂商域名",
    servedText.indexOf('RUNTIME_URL = "https://karma-network.ai"') < 0
  );

  await ctx.addInitScript((id) => {
    try {
      sessionStorage.setItem("karma_console_wallet", "0x1111111111111111111111111111111111111111");
      sessionStorage.setItem("karma_console_identity", id);
      sessionStorage.setItem("karma_console_access_token", "dummy-token");
    } catch (e) {}
  }, ID);

  const page = await ctx.newPage();
  const seen = [];
  page.on("pageerror", (e) => seen.push("pageerror: " + e.message));
  // 线上复验要能自己说明「为什么对不上」：把非 401 的失败响应记下来
  // （401 是假身份带来的，属于预期；404/500 才是真的出事）。
  const failed = [];
  page.on("response", (r) => {
    // 401/403 是假身份带来的，属于预期；404/5xx 才是真的出事。
    if (r.status() === 404 || r.status() >= 500) failed.push(r.status() + " " + r.url());
  });

  await page.goto(PAGE, { waitUntil: "load", timeout: 60000 });
  await page.waitForTimeout(3500);

  console.log("\n[1] 首屏：节点胶囊");
  let s = await page.evaluate(READ);
  check("胶囊渲染出来了", !!s.chipName, s.chipName);
  check("默认站在当前站点（同源）", s.chipName === "当前站点（同源）", s.chipName);
  check("探活后有延迟数字", /\d+ ms/.test(s.chipMs), s.chipMs);
  check("生效地址就是站点自己", s.effective === ORIGIN, s.effective);

  console.log("\n[2] 下拉：列出节点 + 真实测速");
  await page.click("#node-chip");
  await page.waitForTimeout(2500);
  s = await page.evaluate(READ);
  check("下拉列出了每一台节点", s.menuRows >= 2, s.menuRows);
  const msCells = await page.$$eval("#node-menu .node-row-ms", (ns) => ns.map((n) => n.textContent.trim()));
  check("线上节点测得出延迟", msCells.filter((t) => /\d+ ms/.test(t)).length >= 2, msCells);
  const dots = await page.$$eval("#node-menu .node-dot", (ns) => ns.map((n) => n.className));
  check("健康点是绿的（线上节点是活的）", dots.filter((c) => /\bok\b/.test(c)).length >= 2, dots);
  if (SHOTS) await page.screenshot({ path: path.join(SHOTS, "prod-01-menu.png") });

  console.log("\n[3] 切节点：状态、存储、窗口变量一起变");
  await page.click('#node-menu .node-row[data-node-row="official"] [data-node-action="select"]');
  await page.waitForTimeout(600);
  s = await page.evaluate(READ);
  check("localStorage 的地址更新了", s.lsBase === ORIGIN, s.lsBase);
  check("选中的节点 id 更新了", s.lsNode === "official", s.lsNode);
  check("window.KARMA_API_BASE 更新了", s.winBase === ORIGIN, s.winBase);
  check("胶囊跟着变了", s.chipName.indexOf("karma-network.ai") >= 0, s.chipName);
  check("切完给了回执", /已切换节点/.test(s.menuStatus), s.menuStatus);

  console.log("\n[4] 设置页的节点卡片");
  await page.click('#node-menu [data-node-action="manage"]');
  await page.waitForTimeout(800);
  const onSettings = await page.evaluate(() => ({
    page: document.querySelector("#settings").classList.contains("active"),
    chipOpen: !document.querySelector("#node-menu").hidden,
  }));
  check("跳到了设置页", onSettings.page, onSettings);
  check("下拉自动收起", onSettings.chipOpen === false, onSettings);
  s = await page.evaluate(READ);
  check("卡片渲染了节点列表", s.settingsRows >= 2, s.settingsRows);
  check("给出了交给 agent 的接入地址", /karma-network\.ai/.test(s.endpoint), s.endpoint);
  if (SHOTS) await page.screenshot({ path: path.join(SHOTS, "prod-02-settings.png") });

  console.log("\n[5] 自定义节点：危险地址被拒");
  await page.fill("[data-karma-nodes-settings] [data-node-add-base]", "javascript:alert(1)");
  await page.click('[data-karma-nodes-settings] [data-node-action="add"]');
  await page.waitForTimeout(400);
  s = await page.evaluate(READ);
  check("非 http(s) 的地址被拒", /必须以 http/.test(s.settings), s.settings.slice(-200));

  console.log("\n[6] 交给 agent 的地址跟着节点走（没有写死厂商域名）");
  const before = await page.evaluate(() => window.KarmaHandoff.runtimeUrl());
  check("默认交给 agent 的就是站点自己", before === ORIGIN, before);
  await page.fill("[data-karma-nodes-settings] [data-node-add-label]", "Prod Probe");
  await page.fill("[data-karma-nodes-settings] [data-node-add-base]", DEAD_NODE);
  await page.click('[data-karma-nodes-settings] [data-node-action="add"]');
  await page.waitForTimeout(400);
  await page.evaluate((base) => window.KarmaNodes.select("custom:" + base), DEAD_NODE);
  await page.waitForTimeout(400);
  const handed = await page.evaluate(() => ({
    handoff: window.KarmaHandoff.runtimeUrl(),
    authorize: window.KarmaAuthorize.runtimeUrl(),
    effective: window.KarmaNodes.effectiveBase(),
  }));
  check("交付包用的是新选的节点", handed.handoff === DEAD_NODE, handed);
  check("SDK env 用的是新选的节点", handed.authorize === DEAD_NODE, handed);
  if (SHOTS) await page.screenshot({ path: path.join(SHOTS, "prod-03-handoff.png") });

  console.log("\n[7] 容灾：选中的节点不可用时自动换一台");
  const moved = await page.evaluate((base) => {
    window.KarmaNodes.setAutofail(true);
    return window.KarmaNodes.reportFailure(base).then((n) => (n ? n.id : null));
  }, DEAD_NODE);
  check("自动换到了别的节点", !!moved && moved !== "custom:" + DEAD_NODE, moved);
  const after = await page.evaluate(() => ({
    base: window.KarmaNodes.effectiveBase(),
    ls: localStorage.getItem("karma_cyber_api_base"),
  }));
  // 空串就是「当前站点（同源）」的写法，比之前先还原成真实地址。
  check("新地址被记住", (after.ls === "" ? ORIGIN : after.ls) === after.base, after);
  check("换到了能用的节点上", after.base === ORIGIN || after.base.indexOf("karma-network.ai") >= 0, after);
  await page.evaluate(() => window.KarmaNodes.setAutofail(false));

  console.log("\n[8] 六门语言：线上节点层不许留中文");
  for (const lang of ["zh-CN"].concat(LANGS)) {
    await switchLang(page, lang);
    const selOk = await page.evaluate((l) => document.querySelector("#cyberLang").value === l, lang);
    check(lang + "：语言下拉保持同步", selOk);
    await page.evaluate(() => {
      if (window.KarmaNodePanel) window.KarmaNodePanel.render();
      window.CYBER_I18N.applyCyberI18n();
      window.KarmaNodePanel.open(true);
    });
    await page.waitForTimeout(1200);
    const snap = await page.evaluate(READ);
    const residue = chineseResidue(snap.chunk);
    if (lang === "zh-CN") {
      check("zh-CN 保留中文原文", !!residue);
    } else {
      check(lang + "：节点层没有残留中文", !residue, residue);
      const pack = loadPack(lang);
      const mustShow = ["接入节点（去中心化）", "测速", "管理节点", "添加自定义节点", "把接入地址交给你的 agent："];
      const missing = mustShow.filter((x) => snap.chunk.join(" ").indexOf(pack[x]) < 0);
      check(
        lang + "：文案真的换成了这门语言",
        missing.length === 0,
        { missing: missing, packs: snap.packs, base: snap.phraseBase, failed: failed.slice(0, 4) }
      );
    }
    if (SHOTS) await page.screenshot({ path: path.join(SHOTS, "prod-04-node-" + lang + ".png") });
    await page.evaluate(() => window.KarmaNodePanel.open(false));
  }

  console.log("\n[9] 收尾：把选择还原成当前站点");
  await page.evaluate(() => window.KarmaNodes.select("same-origin"));
  await page.waitForTimeout(300);
  s = await page.evaluate(READ);
  check("回到同源", s.effective === ORIGIN, s.effective);
  check("线上没有 404/5xx（401/403 是假身份，属预期）", failed.length === 0, failed.slice(0, 6));
  check("全程没有未捕获的页面异常", seen.length === 0, seen.slice(0, 4));

  await browser.close();
  if (failures) {
    console.log("\n" + failures + "/" + checks + " 项失败");
    process.exit(1);
  }
  console.log("\n线上复验全部 " + checks + " 项通过");
  if (SHOTS) console.log("截图: " + SHOTS);
})().catch((e) => {
  console.error("harness crashed:", e);
  process.exit(2);
});
