/*
 * 身份核验页 · 线上复验。
 *
 * 本机那支（console_verify_route_live.cjs）证明「源码是对的」；这一支证明
 * 「线上那份是对的」—— 页面、脚本、样式、语言包全部从正式域名取，
 * 只有「服务商现状」这一个接口按脚本给答案（否则没登录就全是 401，
 * 断言就没法确定）。
 *
 * 与 scripts/console_bundle.py remote 的分工：那边逐字节对账（39 个文件一个不落），
 * 这边证明「线上那份在真浏览器里真的这么长」。
 *
 * 跑法（默认不跑，必须显式给地址）：
 *   KARMA_PROD_URL=https://karma-network.ai/console/pages/cyber/index.html \
 *     node tests/playwright/console_verify_route_prod.cjs
 *
 * 环境变量：
 *   KARMA_PROD_URL      操作台线上地址（必填）
 *   KARMA_CHROME        指定 Chromium 可执行文件
 *   KARMA_VERIFY_SHOTS  截图输出目录；不设就不截图
 */
"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const RAW = process.env.KARMA_PROD_URL || "";
if (!RAW) {
  console.error("需要 KARMA_PROD_URL，例如：");
  console.error("  KARMA_PROD_URL=https://karma-network.ai/console/pages/cyber/index.html node tests/playwright/console_verify_route_prod.cjs");
  process.exit(2);
}

const PAGE = RAW;
const ORIGIN = new URL(PAGE).origin;
const SHOTS = process.env.KARMA_VERIFY_SHOTS || "";
const LANGS = ["en", "ja", "ko", "es-AR", "es-SV"];
const CJK = /[\u4e00-\u9fff]/;
const ID = "kid_5f0aa8ccf7483983a8a2a5a9";

/** 「服务商现状」这一个接口按脚本给答案；其余全部打到线上。 */
const stub = { provider: "none" };

function providerPayload() {
  return stub.provider === "none"
    ? {
        provider: "none",
        available: ["mock", "aliyun", "tencent", "persona"],
        configured: false,
        usable: false,
        missing: [],
        callback_ready: false,
        note: "未接入服务商：当前走「本人提交 + 复核台人工核验」。",
      }
    : {
        provider: stub.provider,
        available: ["mock", "aliyun", "tencent", "persona"],
        configured: true,
        usable: true,
        missing: [],
        callback_ready: true,
        supports_pull: true,
      };
}

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

function loadPack(lang) {
  const packDir = path.join(__dirname, "..", "..", "apps", "console", "scripts", "i18n-phrase");
  const box = { window: {} };
  vm.createContext(box);
  vm.runInContext(fs.readFileSync(path.join(packDir, lang + ".js"), "utf8"), box);
  return box.window.CYBER_I18N_PHRASE[lang];
}

/**
 * 中文残留怎么判：日文本来就写汉字，拿 CJK 区间扫日文页只会误报。
 * 日文页改用「语言包里那条中文原文有没有原样留下」，只有三段以上的原文才算
 * —— 两个字的词在日文里可能是巧合（「正面」在日本也写「正面」）。
 * 韩文 / 西班牙文没有汉字，两种尺子一起用。
 */
function packResidue(text, pack) {
  for (const key of Object.keys(pack)) {
    if (key.length >= 3 && text.indexOf(key) >= 0) return key;
  }
  return null;
}

function identityInit(id) {
  try {
    sessionStorage.setItem("karma_console_wallet", "0x1111111111111111111111111111111111111111");
    sessionStorage.setItem("karma_console_identity", id);
    sessionStorage.setItem("karma_console_access_token", "test-token");
  } catch (e) {}
}

const READ = () => {
  const txt = (sel) => {
    const n = document.querySelector(sel);
    return n ? n.textContent.replace(/\s+/g, " ").trim() : "";
  };
  const card = document.querySelector("#idv-verify");
  const provider = document.querySelector("#idv-provider");
  return {
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
    openDisabled: (() => {
      const b = document.querySelector("#idv-provider-open");
      return b ? b.disabled : null;
    })(),
  };
};

async function openPersonalVerification(page) {
  await page.evaluate(() => {
    const btn = document.querySelector('.nav-sub[data-page="identity"][data-sub="personal"]');
    if (btn) btn.click();
  });
  await page.waitForTimeout(1200);
}

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
  await page.waitForFunction((l) => window.CYBER_I18N.getLang() === l, lang, { timeout: 20000 });
  // 翻页是异步的（观察器排队跑），固定 sleep 会量到上一门语言 —— 等它落定再断言。
  // zh-CN 是原文语言，没有自己的语言包；那一门不用等翻译。
  let want = null;
  try {
    want = loadPack(lang)["当前路径"];
  } catch (e) {
    want = null;
  }
  if (want) {
    await page.waitForFunction(
      (w) => {
        const n = document.querySelector("#idv-verify-route");
        return !!n && n.textContent.trim() === w;
      },
      want,
      { timeout: 20000 }
    );
  }
  await page.waitForTimeout(400);
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

  const launchOpts = process.env.KARMA_CHROME ? { executablePath: process.env.KARMA_CHROME } : {};
  const browser = await chromium.launch(launchOpts);
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 980 } });
  await ctx.addInitScript(identityInit, ID);

  const page = await ctx.newPage();
  const seen = [];
  page.on("pageerror", (e) => seen.push("pageerror: " + e.message));
  page.on("console", (m) => {
    if (m.type() === "error" && /page/i.test(m.text())) seen.push("console: " + m.text());
  });

  await page.route("**/*", async (route) => {
    const url = route.request().url();
    if (url.startsWith(ORIGIN) && /\/verification\/provider(\?|$)/.test(url)) {
      return route.fulfill({
        status: 200,
        headers: { "content-type": "application/json", "access-control-allow-origin": "*" },
        body: JSON.stringify({ identity_id: ID, provider: providerPayload(), state: null }),
      });
    }
    return route.continue();
  });

  await page.goto(PAGE, { waitUntil: "load" });
  await page.waitForTimeout(2000);
  await openPersonalVerification(page);

  console.log("\n[1] 线上那份：核验只剩三步");
  let s = await page.evaluate(READ);
  check("核验卡真的显示出来了", s.visible === true, s.visible);
  check("核验是三步", s.steps === 3, s.steps);
  check(
    "三步的名字对得上",
    JSON.stringify(s.heads) === JSON.stringify(["① 证件", "② 刷脸", "③ 本地加密并提交"]),
    s.heads
  );
  const gone = await page.evaluate(() => ({
    enc: !!document.querySelector("#idv-step-enc"),
    send: !!document.querySelector("#idv-step-send"),
    encState: !!document.querySelector("#idv-verify #idv-enc-state"),
    sendState: !!document.querySelector("#idv-verify #idv-send-state"),
  }));
  check("旧的「④ 本地加密」「⑤ 提交」两段已经不在页面上", gone.enc === false && gone.send === false, gone);
  check("两个状态位还在（脚本还在写它们）", gone.encState && gone.sendState, gone);

  console.log("\n[2] 线上那份：没接服务商，那张卡是灰的");
  check("服务商卡带 is-off", s.providerOff === true, s.providerOff);
  check("服务商卡 aria-disabled=true", s.providerAria === "true", s.providerAria);
  check("服务商按钮点不动", s.openDisabled === true, s.openDisabled);
  check("人工复核卡标了「当前路径」", s.routeBadge === "当前路径", s.routeBadge);
  await shoot(page, SHOTS, "prod-01-no-provider");

  console.log("\n[3] 线上那份：六门语言不留中文");
  for (const lang of LANGS) {
    await switchLang(page, lang);
    s = await page.evaluate(READ);
    const pack = loadPack(lang);
    check(lang + "：通道标记跟着语言走", s.routeBadge === pack["当前路径"], [s.routeBadge, pack["当前路径"]]);
    await page
      .waitForFunction(
        (keys) => {
          const card = document.querySelector("#idv-verify");
          const prov = document.querySelector("#idv-provider");
          const blob = (card ? card.textContent : "") + " | " + (prov ? prov.textContent : "");
          return !keys.some((k) => blob.indexOf(k) >= 0);
        },
        Object.keys(pack).filter((k) => k.length >= 3),
        { timeout: 20000 }
      )
      .catch(() => {});
    s = await page.evaluate(READ);
    const shown = s.verifyText + " | " + s.providerText;
    const residue = packResidue(shown, pack) || (lang === "ja" ? null : CJK.test(shown) && "CJK");
    check(lang + "：核验页没有残留中文", !residue, [residue, shown.slice(0, 200)]);
    await shoot(page, SHOTS, "prod-02-" + lang);
  }

  console.log("\n[4] 线上那份：接了服务商之后，通道调换");
  stub.provider = "mock";
  await page.reload({ waitUntil: "load" });
  await page.waitForTimeout(1800);
  await openPersonalVerification(page);
  s = await page.evaluate(READ);
  check("服务商卡不再灰", s.providerOff === false, s.providerOff);
  check("服务商按钮可以点了", s.openDisabled === false, s.openDisabled);
  // 刷新之后页面会沿用上次选的语言，所以「备用路径」要按当前语言去比。
  const langNow = await page.evaluate(() => window.CYBER_I18N.getLang());
  let wantAlt = "备用路径";
  try {
    wantAlt = loadPack(langNow)["备用路径"] || wantAlt;
  } catch (e) {}
  check("人工复核卡退成「备用路径」", s.routeBadge === wantAlt, [s.routeBadge, wantAlt, langNow]);
  await shoot(page, SHOTS, "prod-03-provider-on");

  check("没有被脚本异常打断", seen.length === 0, seen.slice(0, 3));

  await browser.close();
  console.log("\n" + checks + " checks, " + failures + " failed");
  process.exit(failures === 0 ? 0 : 1);
})();
