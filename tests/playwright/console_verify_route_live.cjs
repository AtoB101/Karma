/*
 * 身份核验页 · 真机验证（两条通道 + 三步核验）。
 *
 * 单元测试只证明字符串还在文件里；这一支开一个真实浏览器，把它当用户看：
 * 走进「身份 · 认证」页，数一数核验到底几步，看服务商那张卡在没接入时
 * 是不是真的灰着、人工复核那张卡是不是真的标了「当前路径」，
 * 再把六门语言逐个切一遍 —— 英文页里不该看见一个汉字。
 *
 * 自带静态服务器，除 127.0.0.1 以外的请求全部本地应答（不碰外网）。
 *
 * 跑法：
 *   npm i -D playwright && npx playwright install chromium
 *   node tests/playwright/console_verify_route_live.cjs
 *
 * 环境变量：
 *   KARMA_CHROME       指定 Chromium 可执行文件
 *   KARMA_LIVE_PORT    静态服务器端口（默认 8790，避开节点层那份）
 *   KARMA_VERIFY_SHOTS 截图输出目录；不设就不截图
 */
"use strict";

const fs = require("fs");
const http = require("http");
const path = require("path");
const vm = require("vm");

const REPO = path.resolve(__dirname, "..", "..");
const CONSOLE_DIR = path.join(REPO, "apps", "console");
const PACK_DIR = path.join(CONSOLE_DIR, "scripts", "i18n-phrase");
const PORT = Number(process.env.KARMA_LIVE_PORT || 8790);
const PAGE = "http://127.0.0.1:" + PORT + "/pages/cyber/index.html";
const SHOTS = process.env.KARMA_VERIFY_SHOTS || "";
const ID = "kid_5f0aa8ccf7483983a8a2a5a9";
const LANGS = ["en", "ja", "ko", "es-AR", "es-SV"];
const CJK = /[\u4e00-\u9fff]/;

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
};

/** 服务端现状：默认「没接服务商」，中途可改成 mock 演「接入之后」。 */
const stub = { provider: "none" };

function providerPayload() {
  if (stub.provider === "none") {
    return {
      provider: "none",
      available: ["mock", "aliyun", "tencent", "persona"],
      configured: false,
      usable: false,
      missing: [],
      callback_ready: false,
      note: "未接入服务商：当前走「本人提交 + 复核台人工核验」。",
    };
  }
  return {
    provider: stub.provider,
    available: ["mock", "aliyun", "tencent", "persona"],
    configured: true,
    usable: true,
    missing: [],
    callback_ready: true,
    supports_pull: true,
  };
}

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

/**
 * 中文残留怎么判：日文本来就是用汉字写的（「認証」「書類」都在同一个码位区间），
 * 拿 CJK 区间去扫日文页只会误报。所以日文页改用另一把尺子 ——
 * 语言包里那条中文原文要是**原样**出现在页面上，就是没翻过去。
 * 韩文 / 西班牙文没有汉字，两种尺子一起用。
 */
function packResidue(text, pack) {
  for (const key of Object.keys(pack)) {
    // 两个字的中文词在日文里可能是巧合（「正面」在日本也写「正面」），
    // 所以只认三段以上的原文 —— 用户看得见的那句中文不会只有两个字。
    if (key.length >= 3 && text.indexOf(key) >= 0) return key;
  }
  return null;
}

function loadPack(lang) {
  const box = { window: {} };
  vm.createContext(box);
  vm.runInContext(fs.readFileSync(path.join(PACK_DIR, lang + ".js"), "utf8"), box);
  return box.window.CYBER_I18N_PHRASE[lang];
}

const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-headers": "*",
  "access-control-allow-methods": "GET,POST,PUT,DELETE,OPTIONS",
  "content-type": "application/json",
};

function identityInit(id) {
  try {
    sessionStorage.setItem("karma_console_wallet", "0x1111111111111111111111111111111111111111");
    sessionStorage.setItem("karma_console_identity", id);
    sessionStorage.setItem("karma_console_access_token", "test-token");
    localStorage.setItem("karma_cyber_api_base", "http://127.0.0.1:8099");
  } catch (e) {}
}

function makeStub() {
  return async function (route) {
    const req = route.request();
    const url = req.url();
    if (url.startsWith("http://127.0.0.1:" + PORT)) return route.continue();
    if (req.method() === "OPTIONS") return route.fulfill({ status: 204, headers: CORS, body: "" });
    if (/\/health(\?|$)/.test(url)) {
      return route.fulfill({ status: 200, headers: CORS, body: JSON.stringify({ status: "ok", version: "0.1.0" }) });
    }
    if (/\/verification\/provider(\?|$)/.test(url)) {
      return route.fulfill({
        status: 200,
        headers: CORS,
        body: JSON.stringify({ identity_id: ID, provider: providerPayload(), state: null }),
      });
    }
    return route.fulfill({
      status: 200,
      headers: CORS,
      body: JSON.stringify({ ok: true, identity_id: ID, profiles: [], allocations: [], items: [] }),
    });
  };
}

/** 读一眼核验页当前长什么样（全部来自真 DOM）。 */
const READ = () => {
  const txt = (sel) => {
    const n = document.querySelector(sel);
    return n ? n.textContent.replace(/\s+/g, " ").trim() : "";
  };
  const card = document.querySelector("#idv-verify");
  const provider = document.querySelector("#idv-provider");
  return {
    onIdentity: !!document.querySelector("#identity.page.active"),
    visible: (() => {
      const n = document.querySelector("#idv-verify");
      return !!n && n.getBoundingClientRect().height > 0;
    })(),
    steps: card ? card.querySelectorAll("ol.idv-pipeline > li").length : -1,
    heads: card
      ? Array.from(card.querySelectorAll("ol.idv-pipeline > li > .idv-step-head > b")).map((b) => b.textContent.trim())
      : [],
    verifyText: card ? card.textContent.replace(/\s+/g, " ").trim() : "",
    routeBadge: txt("#idv-verify-route"),
    providerOff: provider ? provider.classList.contains("is-off") : null,
    providerAria: provider ? provider.getAttribute("aria-disabled") : null,
    providerText: provider ? provider.textContent.replace(/\s+/g, " ").trim() : "",
    providerBadge: txt("#idv-provider-badge"),
    openDisabled: (() => {
      const b = document.querySelector("#idv-provider-open");
      return b ? b.disabled : null;
    })(),
  };
};

/** 核验卡在「身份 · 认证 → 个人助理认证」这一页里；不点进去读到的是一张隐藏的卡。 */
async function openPersonalVerification(page) {
  await page.evaluate(() => {
    const btn = document.querySelector('.nav-sub[data-page="identity"][data-sub="personal"]');
    if (btn) btn.click();
  });
  await page.waitForTimeout(1000);
}

/**
 * 拍两张卡：先滚到服务商那张，再滚到核验那张。
 * 元素截图在这里会拍到顶栏（卡片上有动画、滚动位置又会被拉回去），
 * 所以走「滚到它 → 拍视口」这条稳的路。
 */
async function shoot(page, dir, name) {
  if (!dir) return;
  const at = async (sel, file) => {
    await page.evaluate((s) => {
      const n = document.querySelector(s);
      if (n) n.scrollIntoView({ block: "center" });
    }, sel);
    await page.waitForTimeout(500);
    await page.screenshot({ path: path.join(dir, file), animations: "disabled" });
  };
  await at("#idv-provider", name + "-provider.png");
  await at("#idv-verify", name + "-verify.png");
}

async function switchLang(page, lang) {
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
  await ctx.addInitScript(identityInit, ID);

  const page = await ctx.newPage();
  const seen = [];
  page.on("pageerror", (e) => seen.push("pageerror: " + e.message));
  await page.route("**/*", makeStub());

  await page.goto(PAGE, { waitUntil: "load" });
  await page.waitForTimeout(1200);
  await openPersonalVerification(page);

  console.log("\n[1] 核验只剩三步");
  let s = await page.evaluate(READ);
  check("走到了「身份 · 认证」页", s.onIdentity, s.onIdentity);
  check("核验卡是真的显示出来了（不是读的隐藏节点）", s.visible === true, s.visible);
  check("核验是三步", s.steps === 3, s.steps);
  check(
    "三步的名字对得上",
    JSON.stringify(s.heads) === JSON.stringify(["① 证件", "② 刷脸", "③ 本地加密并提交"]),
    s.heads
  );
  const hasEnc = await page.evaluate(() => !!document.querySelector("#idv-verify #idv-enc-state"));
  const hasSend = await page.evaluate(() => !!document.querySelector("#idv-verify #idv-send-state"));
  check("加密 / 提交的状态位还在（脚本要写它们）", hasEnc && hasSend, [hasEnc, hasSend]);

  console.log("\n[2] 没接服务商：那张卡是灰的，另一张是「当前路径」");
  check("服务商卡带 is-off", s.providerOff === true, s.providerOff);
  check("服务商卡 aria-disabled=true", s.providerAria === "true", s.providerAria);
  check("服务商按钮点不动", s.openDisabled === true, s.openDisabled);
  check("服务商卡直说「未接入」", s.providerText.indexOf("未接入") >= 0, s.providerText.slice(0, 160));
  check("人工复核卡标了「当前路径」", s.routeBadge === "当前路径", s.routeBadge);
  await shoot(page, SHOTS, "01-no-provider");

  console.log("\n[3] 六门语言：切过去不留中文");
  for (const lang of LANGS) {
    await switchLang(page, lang);
    s = await page.evaluate(READ);
    const pack = loadPack(lang);
    check(lang + "：通道标记跟着语言走", s.routeBadge === pack["当前路径"], [s.routeBadge, pack["当前路径"]]);
    const shown = s.verifyText + " | " + s.providerText;
    const residue = packResidue(shown, pack) || (lang === "ja" ? null : CJK.test(shown) && "CJK");
    check(lang + "：核验页没有残留中文", !residue, [residue, shown.slice(0, 220)]);
    await shoot(page, SHOTS, "02-" + lang);
  }
  await switchLang(page, "zh-CN");
  s = await page.evaluate(READ);
  check("zh-CN 保留中文原文", s.routeBadge === "当前路径", s.routeBadge);

  console.log("\n[4] 接入服务商之后：换成官方核验优先，人工复核退成备用");
  stub.provider = "mock";
  await page.reload({ waitUntil: "load" });
  await page.waitForTimeout(1000);
  await openPersonalVerification(page);
  s = await page.evaluate(READ);
  check("服务商卡不再灰", s.providerOff === false, s.providerOff);
  check("服务商卡 aria-disabled=false", s.providerAria === "false", s.providerAria);
  check("按钮可以点了", s.openDisabled === false, s.openDisabled);
  check("人工复核卡退成「备用路径」", s.routeBadge === "备用路径", s.routeBadge);
  check("服务商卡说清了把证件直连服务商", s.providerText.indexOf("服务商") >= 0, s.providerText.slice(0, 160));
  await shoot(page, SHOTS, "03-provider-on");

  check("没有被脚本异常打断", seen.length === 0, seen.slice(0, 3));

  await browser.close();
  staticServer.close();
  console.log("\n" + checks + " checks, " + failures + " failed");
  process.exit(failures === 0 ? 0 : 1);
})();
