/*
 * 刷脸即激活 / 追加身份 / 动额度前过 2FA · 真机验证（L3-3）。
 *
 * 为什么单独有一支：这三处的文案与状态都是**脚本异步写进 DOM** 的 ——
 * 静态检查只能证明字符串躺在文件里，真正会翻车的是「切了语言它还挂着中文」。
 * 所以这里开一个真实浏览器，把模块真的跑起来：
 *
 *   [1] 点「开始刷脸激活」→ 状态行显示「已激活（活体 5 个角度）」；
 *   [2] 五门语言逐个切：这一行必须换语言（日文除外，用「中文原文没留」当尺子）；
 *   [3] 设置页那张 2FA 卡渲染出来，五门语言同样逐字比对；
 *   [4] 动额度真的过闸：没带码 → 弹验证码 → 输码 → PUT 带着 X-Karma-2FA-Code 出去；
 *   [5] 追加身份那张卡渲染出来，五门语言不留汉字。
 *
 * 自带静态服务器（127.0.0.1），/v1/* 由它应答。
 *
 * 跑法：
 *   npm i -D playwright && npx playwright install chromium
 *   node tests/playwright/console_2fa_face_live.cjs
 *
 * 环境变量：
 *   KARMA_CHROME    指定 Chromium 可执行文件
 *   KARMA_2FA_PORT  静态服务器端口（默认 8797）
 */
"use strict";

const fs = require("fs");
const http = require("http");
const path = require("path");
const vm = require("vm");

const REPO = path.resolve(__dirname, "..", "..");
const CONSOLE_DIR = path.join(REPO, "apps", "console");
const PACK_DIR = path.join(CONSOLE_DIR, "scripts", "i18n-phrase");
const PORT = Number(process.env.KARMA_2FA_PORT || 8797);
const PAGE = "http://127.0.0.1:" + PORT + "/pages/cyber/index.html";
const ID = "0x5cbdd86a2fa8dc4bddd8a8f69dba48572eec07fb";
const LANGS = ["en", "ja", "ko", "es-AR", "es-SV"];
const CJK = /[\u4e00-\u9fff]/;
const ACTIVATED_ZH = "已激活（活体 5 个角度）";

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
  console.log(
    "  FAIL " + name + (extra === undefined ? "" : " -> " + JSON.stringify(extra).slice(0, 320))
  );
}

function loadPack(lang) {
  const box = { window: {} };
  vm.createContext(box);
  vm.runInContext(fs.readFileSync(path.join(PACK_DIR, lang + ".js"), "utf8"), box);
  return box.window.CYBER_I18N_PHRASE[lang];
}

/** 静态服务器 + 假后端。 */
function serve(state) {
  const server = http.createServer((req, res) => {
    const rel = decodeURIComponent(req.url.split("?")[0]);
    if (rel.startsWith("/v1/")) {
      let status = 200;
      let body = { ok: true, identity_id: ID, profiles: [], allocations: [], items: [] };
      if (/\/console\/2fa$/.test(rel)) {
        body = {
          identity_id: ID,
          enabled: true,
          pending: false,
          recovery_left: 3,
          failures: 0,
          locked: false,
          required_for_funds: false,
        };
      } else if (/\/allocations$/.test(rel) && req.method === "PUT") {
        state.putHeader = req.headers["x-karma-2fa-code"] || null;
        state.putCount += 1;
        body = { allocations: [], locked_usdc: 0, allocated_usdc: 0, available_usdc: 0 };
      } else if (/\/allocations$/.test(rel)) {
        body = {
          allocations: [],
          locked_usdc: 0,
          allocated_usdc: 0,
          available_usdc: 0,
          activation: { activated: false, status: "none" },
        };
      }
      res.writeHead(status, {
        "content-type": "application/json; charset=utf-8",
        "access-control-allow-origin": "*",
        "access-control-allow-headers": "*",
      });
      res.end(JSON.stringify(body));
      return;
    }
    const file = rel.endsWith("/") ? rel + "index.html" : rel;
    const full = path.join(CONSOLE_DIR, file);
    if (!full.startsWith(CONSOLE_DIR) || !fs.existsSync(full) || !fs.statSync(full).isFile()) {
      res.writeHead(404, { "content-type": "text/plain" });
      res.end("not found");
      return;
    }
    res.writeHead(200, { "content-type": MIME[path.extname(full)] || "application/octet-stream" });
    fs.createReadStream(full).pipe(res);
  });
  return new Promise((resolve) => server.listen(PORT, "127.0.0.1", () => resolve(server)));
}

/** 主身份那张卡（含 ② 刷脸激活 / 追加身份）在「身份 · 主体账户」这一页里。 */
async function openIdentityPage(page) {
  await page.evaluate(() => {
    const btn = document.querySelector('.nav-sub[data-page="identity"][data-sub="master"]');
    if (btn) btn.click();
  });
  await page.waitForTimeout(800);
}

/** 2FA 那张卡在设置页（节点列表下面）。 */
async function openSettingsPage(page) {
  await page.evaluate(() => {
    const btn = document.querySelector('.nav-main[data-page="settings"]');
    if (btn) btn.click();
  });
  await page.waitForTimeout(800);
}

async function switchLang(page, lang) {
  await page.evaluate((l) => {
    const sel = document.querySelector("#cyberLang");
    sel.value = l;
    sel.dispatchEvent(new Event("change", { bubbles: true }));
  }, lang);
  await page.waitForFunction((l) => window.CYBER_I18N.getLang() === l, lang, { timeout: 20000 });
}

const READ_ACTIVATE = () => {
  const n = document.querySelector("#mst-activate-status");
  return n ? n.textContent.replace(/\s+/g, " ").trim() : "";
};

const READ_2FA_CARD = () => {
  const n = document.querySelector("#k2fa-card");
  return n ? n.textContent.replace(/\s+/g, " ").trim() : "";
};

const READ_ADD_CARD = () => {
  const n = document.querySelector("#idv-add-identity");
  return n ? n.textContent.replace(/\s+/g, " ").trim() : "";
};

async function main() {
  let chromium;
  try {
    ({ chromium } = require("playwright"));
  } catch (e) {
    console.log("(skip) 没装 playwright");
    return 0;
  }

  const packs = {};
  for (const lang of LANGS) packs[lang] = loadPack(lang);

  // 先静态钉一遍：这四条动态文案每份语言包都得有，缺一条那门语言就会挂中文。
  for (const lang of LANGS) {
    check(lang + "：语言包里有「已激活（活体 {0} 个角度）」", !!packs[lang]["已激活（活体 {0} 个角度）"]);
    check(lang + "：语言包里有 2FA 卡片标题", !!packs[lang]["安全验证 · 2FA"]);
    check(lang + "：语言包里有验证码弹窗标题", !!packs[lang]["安全验证 · {0}"]);
    check(lang + "：语言包里有追加身份那张卡", !!packs[lang]["追加身份 · 再刷一次脸就开通"]);
  }

  const state = { putHeader: null, putCount: 0 };
  const server = await serve(state);
  const browser = await chromium.launch(
    process.env.KARMA_CHROME ? { executablePath: process.env.KARMA_CHROME } : {}
  );
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e && e.message ? e.message : e)));

  try {
    await page.addInitScript((base) => {
      try {
        localStorage.setItem("karma_cyber_api_base", base);
        sessionStorage.setItem("karma_console_access_token", "l33-probe");
        sessionStorage.setItem("karma_console_identity", "0x5cbdd86a2fa8dc4bddd8a8f69dba48572eec07fb");
      } catch (e) {}
    }, "http://127.0.0.1:" + PORT);

    await page.goto(PAGE, { waitUntil: "load" });
    await page.waitForFunction(
      () => !!window.CYBER_I18N && !!window.Karma2FA && !!window.KarmaFaceVault && !!window.KarmaAddIdentity,
      null,
      { timeout: 30000 }
    );

    // 取景框本身要摄像头，真机里不点；把「采集 + 加密 + 提交」那一层换成桩，
    // 这一段要验的是**按钮 → 状态行那句话**（含六门语言的动态拼句）。
    await page.evaluate(() => {
      window.KARMA_IDENTITY_ID = "0x5cbdd86a2fa8dc4bddd8a8f69dba48572eec07fb";
      window.KarmaFaceVault.activateByFace = async () => ({ status: "verified", liveness: { angles: 5 } });
    });

    console.log("[1] 中文页：点「开始刷脸激活」→ 状态行");
    await openIdentityPage(page);
    await page.click("#mst-activate-go");
    await page.waitForFunction(
      (want) => {
        const n = document.querySelector("#mst-activate-status");
        return !!n && n.textContent.replace(/\s+/g, " ").trim() === want;
      },
      ACTIVATED_ZH,
      { timeout: 15000 }
    );
    check("中文页状态行就是原文", (await page.evaluate(READ_ACTIVATE)) === ACTIVATED_ZH);

    console.log("[2] 五门语言：状态行跟着换");
    for (const lang of LANGS) {
      await switchLang(page, lang);
      const want = String(packs[lang]["已激活（活体 {0} 个角度）"]).replace("{0}", "5");
      await page.waitForFunction(
        (w) => {
          const n = document.querySelector("#mst-activate-status");
          return !!n && n.textContent.replace(/\s+/g, " ").trim() === w;
        },
        want,
        { timeout: 20000 }
      );
      const got = await page.evaluate(READ_ACTIVATE);
      check(lang + "：状态行换成这门语言（逐字）", got === want, { got, want });
      if (lang === "ja") {
        check("ja：中文原文没有原样留下", got.indexOf(ACTIVATED_ZH) < 0, got);
      } else {
        check(lang + "：状态行没有残留汉字", !CJK.test(got), got);
      }
    }

    console.log("[3] 设置页那张 2FA 卡：中文原文 + 五门语言");
    await switchLang(page, "zh-CN");
    await openSettingsPage(page);
    await page.evaluate(async () => {
      await window.Karma2FA.refresh();
    });
    let card = await page.evaluate(READ_2FA_CARD);
    check("卡片渲染出来了（不是空的）", card.length > 0, card.slice(0, 80));
    check("中文页有这张卡的标题", card.indexOf("安全验证 · 2FA") >= 0, card.slice(0, 120));

    for (const lang of LANGS) {
      await switchLang(page, lang);
      await page.waitForFunction(
        (w) => {
          const n = document.querySelector("#k2fa-card");
          return !!n && n.textContent.indexOf(w) >= 0;
        },
        packs[lang]["安全验证 · 2FA"],
        { timeout: 20000 }
      );
      card = await page.evaluate(READ_2FA_CARD);
      check(lang + "：卡片标题换语言", card.indexOf(packs[lang]["安全验证 · 2FA"]) >= 0, card.slice(0, 120));
      if (lang === "ja") {
        check("ja：卡片里没有残留中文原句", card.indexOf("安全验证 · 2FA") < 0, card.slice(0, 160));
      } else {
        check(lang + "：卡片没有残留汉字", !CJK.test(card), card.slice(0, 200));
      }
    }

    console.log("[4] 动额度真的过闸：弹码 → 输码 → 请求带 X-Karma-2FA-Code");
    await switchLang(page, "zh-CN");
    await page.evaluate(async () => {
      // 不 await：闸门要等人输码，await 会把整段挂住。
      window.cyberKarmaApi.setAllocations("0x5cbdd86a2fa8dc4bddd8a8f69dba48572eec07fb", {});
    });
    await page.waitForFunction(() => {
      const m = document.querySelector("#k2fa-modal");
      return !!m && m.hidden === false;
    }, null, { timeout: 15000 });
    const title = await page.evaluate(() => {
      const n = document.querySelector("#k2fa-title");
      return n ? n.textContent.trim() : "";
    });
    check("弹窗标题是「安全验证 · 授权额度」", title === "安全验证 · 授权额度", title);

    await page.fill("#k2fa-input", "123456");
    await page.waitForFunction(() => document.querySelector("#k2fa-modal").hidden === true, null, {
      timeout: 15000,
    });
    await page.waitForFunction(() => true, null, { timeout: 2000 });
    check("额度请求带上了验证码", state.putHeader === "123456", state.putHeader);
    check("额度请求只发了一次", state.putCount === 1, state.putCount);

    console.log("[5] 追加身份那张卡：中文原文 + 五门语言");
    await switchLang(page, "zh-CN");
    await page.evaluate(() => window.KarmaAddIdentity.render());
    let add = await page.evaluate(READ_ADD_CARD);
    check("追加身份卡渲染出来了", add.indexOf("追加身份 · 再刷一次脸就开通") >= 0, add.slice(0, 120));

    for (const lang of LANGS) {
      await switchLang(page, lang);
      await page.waitForFunction(
        (w) => {
          const n = document.querySelector("#idv-add-identity");
          return !!n && n.textContent.indexOf(w) >= 0;
        },
        packs[lang]["追加身份 · 再刷一次脸就开通"],
        { timeout: 20000 }
      );
      add = await page.evaluate(READ_ADD_CARD);
      if (lang === "ja") {
        check("ja：追加身份卡没有残留中文原句", add.indexOf("追加身份 · 再刷一次脸就开通") < 0, add.slice(0, 160));
      } else {
        check(lang + "：追加身份卡没有残留汉字", !CJK.test(add), add.slice(0, 200));
      }
    }

    check("整页没有 JS 异常", errors.length === 0, errors.slice(0, 3));
  } finally {
    await browser.close();
    server.close();
  }

  console.log("");
  console.log("checks=" + checks + " failures=" + failures);
  if (failures) {
    process.exitCode = 1;
  }
  return failures;
}

main().catch((e) => {
  console.error("probe crashed: " + (e && e.stack ? e.stack : e));
  process.exitCode = 1;
});
