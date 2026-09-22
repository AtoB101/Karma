/*
 * 操作台节点层 · 真机验证。
 *
 * 单元测试只证明「函数按预期工作」；这一支开一个真实浏览器，把用户真正会走的路
 * 从头走一遍：首屏探活 → 下拉测速 → 切节点 → 设置页卡片 → 添加自定义节点 →
 * 六门语言都不留中文 → 当前节点挂掉自动换下一台 → 交给 agent 的地址跟着变。
 *
 * 它自带一个静态服务器（不需要额外起进程），并把除 127.0.0.1 以外的请求全部
 * 本地应答 —— 跑的时候不碰外网。
 *
 * 跑法：
 *   npm i -D playwright && npx playwright install chromium
 *   node tests/playwright/console_nodes_live.cjs
 *
 * 环境变量：
 *   KARMA_CHROME       指定 Chromium 可执行文件（默认用 playwright 自带那个）
 *   KARMA_LIVE_PORT    静态服务器端口（默认 8787）
 *   KARMA_LIVE_SHOTS   截图输出目录；不设就不截图
 */
"use strict";

const fs = require("fs");
const http = require("http");
const path = require("path");
const vm = require("vm");

const REPO = path.resolve(__dirname, "..", "..");
const CONSOLE_DIR = path.join(REPO, "apps", "console");
const PACK_DIR = path.join(CONSOLE_DIR, "scripts", "i18n-phrase");
const PORT = Number(process.env.KARMA_LIVE_PORT || 8787);
const PAGE = "http://127.0.0.1:" + PORT + "/pages/cyber/index.html";
const SHOTS = process.env.KARMA_LIVE_SHOTS || "";
const ID = "kid_5f0aa8ccf7483983a8a2a5a9";
const LANGS = ["en", "ja", "ko", "es-AR", "es-SV"];

// 节点层里出现过的中文原文。「有没有漏翻」不能拿「有没有汉字」当标准 ——
// 日文里全是汉字。只比对这些整句原文还在不在。
const NODE_SOURCES = [
  "节点", "接入节点（去中心化）",
  "操作台只是界面，账本与资金都在链上。这里决定它跟哪台节点要数据 —— 能上链读的一律链上读，节点只做索引与转发。",
  "当前站点（同源）", "本机 API（127.0.0.1:8000）", "当前", "未测速", "不可用", "自定义",
  "切换到它", "当前节点", "测速", "管理节点", "测速完成", "没有可用的备用节点", "正在测速…",
  "已切换节点", "节点已添加", "已移除该节点", "复制接入地址", "接入地址已复制",
  "复制失败，请手动选中下面的地址", "连不上时自动换节点",
  "开启后，当前节点探活失败会自动切到下一个可用节点，并记住选择。",
  "添加自定义节点", "名称（可选）", "节点地址（http:// 或 https://）", "添加",
  "把接入地址交给你的 agent：", "当前节点连不上，已自动切到",
  "节点地址必须以 http:// 或 https:// 开头", "这个地址已经在列表里了",
];

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
};

let failures = 0;
let checks = 0;
function check(name, cond, extra) {
  checks += 1;
  if (cond) {
    console.log("  ok   " + name);
    return;
  }
  failures += 1;
  console.log("  FAIL " + name + (extra === undefined ? "" : " -> " + JSON.stringify(extra).slice(0, 320)));
}

function serveConsole(root) {
  const server = http.createServer((req, res) => {
    let rel = decodeURIComponent(req.url.split("?")[0]);
    if (rel.endsWith("/")) rel += "index.html";
    const file = path.join(root, rel);
    if (!file.startsWith(root) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
      res.writeHead(404, { "content-type": "text/plain" });
      res.end("not found");
      return;
    }
    res.writeHead(200, { "content-type": MIME[path.extname(file)] || "application/octet-stream" });
    fs.createReadStream(file).pipe(res);
  });
  return new Promise((resolve) => server.listen(PORT, "127.0.0.1", () => resolve(server)));
}

function loadPack(lang) {
  const box = { window: {} };
  vm.createContext(box);
  vm.runInContext(fs.readFileSync(path.join(PACK_DIR, lang + ".js"), "utf8"), box);
  return box.window.CYBER_I18N_PHRASE[lang];
}

function chineseResidue(texts) {
  const blob = texts.join(" ");
  for (const src of NODE_SOURCES) {
    if (blob.indexOf(src) >= 0) return src;
  }
  return null;
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
    chunk: [g("#node-chip"), g("#node-menu"), box ? box.textContent : "", g("#node-toast")]
      .map((s) => String(s || "").replace(/\s+/g, " ").trim())
      .filter(Boolean),
  };
};

async function switchLang(page, lang) {
  // 走真控件：用户怎么切，脚本就怎么切（setLang + ensureExt + 全页重翻）。
  await page.evaluate((l) => {
    const sel = document.querySelector("#cyberLang");
    sel.value = l;
    sel.dispatchEvent(new Event("change", { bubbles: true }));
  }, lang);
  await page.waitForFunction((l) => window.CYBER_I18N.getLang() === l, lang, { timeout: 15000 });
  await page.waitForTimeout(700);
}

(async () => {
  let chromium;
  try {
    ({ chromium } = require("playwright"));
  } catch (e) {
    console.error("需要 playwright：npm i -D playwright && npx playwright install chromium");
    process.exit(2);
  }
  if (SHOTS) fs.mkdirSync(SHOTS, { recursive: true });

  const staticServer = await serveConsole(CONSOLE_DIR);
  const launchOpts = process.env.KARMA_CHROME ? { executablePath: process.env.KARMA_CHROME } : {};
  const browser = await chromium.launch(launchOpts);
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 980 } });

  await ctx.addInitScript((id) => {
    try {
      sessionStorage.setItem("karma_console_wallet", "0x1111111111111111111111111111111111111111");
      sessionStorage.setItem("karma_console_identity", id);
      sessionStorage.setItem("karma_console_access_token", "test-token");
      localStorage.setItem("karma_cyber_api_base", "http://127.0.0.1:8099");
    } catch (e) {}
  }, ID);

  const page = await ctx.newPage();
  const seen = [];
  page.on("pageerror", (e) => seen.push("pageerror: " + e.message));

  const CORS = {
    "access-control-allow-origin": "*",
    "access-control-allow-headers": "*",
    "access-control-allow-methods": "GET,POST,PUT,DELETE,OPTIONS",
    "content-type": "application/json",
  };
  await page.route("**/*", async (route) => {
    const req = route.request();
    const url = req.url();
    if (url.startsWith("http://127.0.0.1:" + PORT)) return route.continue();
    if (req.method() === "OPTIONS") return route.fulfill({ status: 204, headers: CORS, body: "" });
    if (/\/health(\?|$)/.test(url)) {
      const u = new URL(url);
      // 8000 这台永远连不上：容灾那一步要靠它。
      if (u.port === "8000") return route.abort("connectionrefused");
      await new Promise((r) => setTimeout(r, u.hostname === "karma-network.ai" ? 40 : 8));
      return route.fulfill({ status: 200, headers: CORS, body: JSON.stringify({ status: "ok", version: "0.1.0" }) });
    }
    return route.fulfill({
      status: 200,
      headers: CORS,
      body: JSON.stringify({ ok: true, identity_id: ID, profiles: [], allocations: [] }),
    });
  });

  await page.goto(PAGE, { waitUntil: "load" });
  await page.waitForTimeout(1200);

  console.log("\n[1] 首屏：节点胶囊");
  let s = await page.evaluate(READ);
  check("胶囊渲染出来了", !!s.chipName, s);
  check("显示的是设置里那台节点", s.chipName === "http://127.0.0.1:8099", s.chipName);
  check("探活后有延迟数字", /\d+ ms/.test(s.chipMs), s.chipMs);
  check("生效地址跟着选中的节点", s.effective === "http://127.0.0.1:8099", s.effective);

  console.log("\n[2] 下拉：列出节点 + 测速");
  await page.click("#node-chip");
  await page.waitForTimeout(1400);
  s = await page.evaluate(READ);
  check("下拉列出了每一台节点", s.menuRows >= 2, s.menuRows);
  const msCells = await page.$$eval("#node-menu .node-row-ms", (ns) => ns.map((n) => n.textContent.trim()));
  check("每台都测出了延迟", msCells.filter((t) => /\d+ ms/.test(t)).length >= 2, msCells);
  const dots = await page.$$eval("#node-menu .node-dot", (ns) => ns.map((n) => n.className));
  check("健康点反映探活结果", dots.filter((c) => /ok|down/.test(c)).length >= 2, dots);
  if (SHOTS) await page.screenshot({ path: path.join(SHOTS, "01-menu.png") });

  console.log("\n[3] 切节点：状态、存储、窗口变量一起变");
  await page.click('#node-menu .node-row[data-node-row="official"] [data-node-action="select"]');
  await page.waitForTimeout(400);
  s = await page.evaluate(READ);
  check("localStorage 的地址更新了", s.lsBase === "https://karma-network.ai", s.lsBase);
  check("选中的节点 id 更新了", s.lsNode === "official", s.lsNode);
  check("window.KARMA_API_BASE 更新了", s.winBase === "https://karma-network.ai", s.winBase);
  check("胶囊跟着变了", /karma-network\.ai/.test(s.chipName), s.chipName);
  check("切完给了回执", /已切换节点/.test(s.menuStatus), s.menuStatus);

  console.log("\n[4] 设置页的节点卡片");
  await page.click('#node-menu [data-node-action="manage"]');
  await page.waitForTimeout(600);
  const onSettings = await page.evaluate(() => ({
    page: document.querySelector("#settings").classList.contains("active"),
    chipOpen: !document.querySelector("#node-menu").hidden,
  }));
  check("跳到了设置页", onSettings.page, onSettings);
  check("下拉自动收起", onSettings.chipOpen === false, onSettings);
  s = await page.evaluate(READ);
  check("卡片渲染了节点列表", s.settingsRows >= 2, s.settingsRows);
  check("给出了交给 agent 的接入地址", /karma-network\.ai/.test(s.endpoint), s.endpoint);
  if (SHOTS) await page.screenshot({ path: path.join(SHOTS, "02-settings.png") });

  console.log("\n[5] 自定义节点：校验 + 添加");
  await page.fill("[data-karma-nodes-settings] [data-node-add-base]", "javascript:alert(1)");
  await page.click('[data-karma-nodes-settings] [data-node-action="add"]');
  await page.waitForTimeout(300);
  s = await page.evaluate(READ);
  check("非 http(s) 的地址被拒", /必须以 http/.test(s.settings), s.settings.slice(-200));
  await page.fill("[data-karma-nodes-settings] [data-node-add-label]", "My Node");
  await page.fill("[data-karma-nodes-settings] [data-node-add-base]", "https://node.example.com/");
  await page.click('[data-karma-nodes-settings] [data-node-action="add"]');
  await page.waitForTimeout(400);
  s = await page.evaluate(READ);
  check("自定义节点进了列表", /My Node/.test(s.settings), s.settings.slice(-260));
  const stored = String(await page.evaluate(() => localStorage.getItem("karma_console_nodes")));
  check("尾部斜杠被规范化", stored.includes("https://node.example.com") && !stored.includes("https://node.example.com/"), stored);

  console.log("\n[6] 六门语言：节点层不许留中文");
  for (const lang of ["zh-CN"].concat(LANGS)) {
    await switchLang(page, lang);
    const selOk = await page.evaluate((l) => document.querySelector("#cyberLang").value === l, lang);
    check(lang + "：语言下拉保持同步", selOk);
    await page.evaluate(() => {
      if (window.KarmaNodePanel) window.KarmaNodePanel.render();
      window.CYBER_I18N.applyCyberI18n();
      window.KarmaNodePanel.open(true);
    });
    await page.waitForTimeout(900);
    const snap = await page.evaluate(READ);
    const residue = chineseResidue(snap.chunk);
    if (lang === "zh-CN") {
      check("zh-CN 保留中文原文", !!residue);
    } else {
      check(lang + "：节点层没有残留中文", !residue, residue);
      const pack = loadPack(lang);
      const mustShow = ["接入节点（去中心化）", "测速", "管理节点", "添加自定义节点", "把接入地址交给你的 agent："];
      const blob = snap.chunk.join(" ");
      const missing = mustShow.filter((x) => blob.indexOf(pack[x]) < 0);
      check(lang + "：文案真的换成了这门语言", missing.length === 0, missing);
    }
    if (SHOTS) await page.screenshot({ path: path.join(SHOTS, "03-node-" + lang + ".png") });
    await page.evaluate(() => window.KarmaNodePanel.open(false));
  }

  console.log("\n[7] 容灾：当前节点挂了自动换一台");
  await switchLang(page, "zh-CN");
  await page.evaluate(() => {
    window.KarmaNodes.setAutofail(true);
    window.KarmaNodes.select("local");
  });
  check("站到了那台挂掉的节点上", (await page.evaluate(() => window.KarmaNodes.effectiveBase())) === "http://127.0.0.1:8000");
  const moved = await page.evaluate(() =>
    window.KarmaNodes.reportFailure("http://127.0.0.1:8000").then((n) => (n ? n.id : null))
  );
  check("自动换到了别的节点", !!moved && moved !== "local", moved);
  const after = await page.evaluate(() => ({
    base: window.KarmaNodes.effectiveBase(),
    ls: localStorage.getItem("karma_cyber_api_base"),
  }));
  check("新地址被记住", after.ls === after.base, after);
  await page.waitForTimeout(300);
  const toast = await page.evaluate(() => {
    const n = document.querySelector("#node-toast");
    return n && !n.hidden ? n.textContent.replace(/\s+/g, " ").trim() : "";
  });
  check("用户被告知了这次切换", /已自动切到/.test(toast), toast);
  if (SHOTS) await page.screenshot({ path: path.join(SHOTS, "04-failover.png") });

  console.log("\n[8] 交给 agent 的地址跟着节点走");
  await page.evaluate(() => window.KarmaNodes.select("custom:https://node.example.com"));
  await page.waitForTimeout(200);
  const handed = await page.evaluate(() => ({
    handoff: window.KarmaHandoff && window.KarmaHandoff.runtimeUrl ? window.KarmaHandoff.runtimeUrl() : "(没导出)",
    authorize: window.KarmaAuthorize && window.KarmaAuthorize.runtimeUrl ? window.KarmaAuthorize.runtimeUrl() : "(没导出)",
  }));
  check("交付包用的是选中的节点", handed.handoff === "https://node.example.com", handed);
  check("SDK env 用的是选中的节点", handed.authorize === "https://node.example.com", handed);

  check("全程没有未捕获的页面错误", seen.length === 0, seen.slice(0, 4));

  await browser.close();
  staticServer.close();
  if (failures) {
    console.log("\n" + failures + "/" + checks + " 项失败");
    process.exit(1);
  }
  console.log("\n全部 " + checks + " 项通过");
  if (SHOTS) console.log("截图: " + SHOTS);
})().catch((e) => {
  console.error("harness crashed:", e);
  process.exit(2);
});
