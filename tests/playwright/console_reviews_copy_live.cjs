/*
 * 复核台「打不开队列」那句提示 · 真机验证（L3-2 之后重写的文案）。
 *
 * 为什么单独有一支：这句话是**脚本写进 DOM** 的，静态检查只能证明字符串在文件里；
 * 真正会翻车的地方是「切了语言它还挂着中文」—— 正是核验页那条通道标记踩过的坑。
 * 所以这里开一个真实浏览器：把服务端打成 403，让页面真的走到那句提示，
 * 再把五门语言逐个切一遍，一句一句比对语言包。
 *
 * 文案本身是从 cyber-reviews.js 里**取出来**的（不是抄一份），
 * 免得哪天改了源码、测试还在拿旧句子自证。
 *
 * 自带静态服务器（127.0.0.1），/v1/* 由它应答：复核队列 403，其余给空壳 200。
 *
 * 跑法：
 *   npm i -D playwright && npx playwright install chromium
 *   node tests/playwright/console_reviews_copy_live.cjs
 *
 * 环境变量：
 *   KARMA_CHROME       指定 Chromium 可执行文件
 *   KARMA_REVIEWS_PORT 静态服务器端口（默认 8795）
 */
"use strict";

const fs = require("fs");
const http = require("http");
const path = require("path");
const vm = require("vm");

const REPO = path.resolve(__dirname, "..", "..");
const CONSOLE_DIR = path.join(REPO, "apps", "console");
const PACK_DIR = path.join(CONSOLE_DIR, "scripts", "i18n-phrase");
const REVIEWS_JS = path.join(CONSOLE_DIR, "scripts", "cyber-reviews.js");
const PORT = Number(process.env.KARMA_REVIEWS_PORT || 8795);
const PAGE = "http://127.0.0.1:" + PORT + "/pages/cyber/index.html";
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

/** 从 cyber-reviews.js 里取出那句提示（拼接表达式原样求值）。 */
function readDenyCopy() {
  const src = fs.readFileSync(REVIEWS_JS, "utf8");
  const m = src.match(/deny\.textContent\s*=\s*([\s\S]*?);/);
  if (!m) throw new Error("cyber-reviews.js 里找不到那句打不开队列的提示");
  return String(vm.runInNewContext("(" + m[1] + ")"));
}

function loadPack(lang) {
  const box = { window: {} };
  vm.createContext(box);
  vm.runInContext(fs.readFileSync(path.join(PACK_DIR, lang + ".js"), "utf8"), box);
  return box.window.CYBER_I18N_PHRASE[lang];
}

/**
 * 静态服务器 + 假后端。
 * 复核队列回 403（页面就会走到那句提示），其余 /v1/* 给一个空壳 ——
 * 不然操作台引导阶段会拿到一堆 404，页面还没走到复核台就先报错。
 */
function serve() {
  const server = http.createServer((req, res) => {
    const rel = decodeURIComponent(req.url.split("?")[0]);
    if (rel.startsWith("/v1/")) {
      const body = /\/reviews\/pending$/.test(rel)
        ? { detail: "only a verifier-class profile can open the review queue" }
        : { ok: true, identity_id: ID, profiles: [], allocations: [], items: [], notifications: [] };
      res.writeHead(rel.endsWith("/reviews/pending") ? 403 : 200, {
        "content-type": "application/json; charset=utf-8",
        "access-control-allow-origin": "*",
      });
      res.end(JSON.stringify(body));
      return;
    }
    let file = rel.endsWith("/") ? rel + "index.html" : rel;
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

/**
 * 把复核台那一页叫起来：先装一个会话，再按页面自己的事件把队列拉一次。
 *
 * 注意 api_base：操作台默认打 http://127.0.0.1:8000（线上靠同源反代兜住），
 * 不把它指到本机这台静态服务器，请求根本走不到我们准备好的那个 403。
 */
async function openReviewsQueue(page) {
  await page.evaluate((id) => {
    window.KARMA_ACCESS_TOKEN = "reviews-copy-probe";
    window.KARMA_IDENTITY_ID = id;
    document.dispatchEvent(new CustomEvent("karma-page-shown", { detail: { page: "reviews", sub: "all" } }));
  }, ID);
}

const READ_DENY = () => {
  const n = document.querySelector("#rv-deny");
  return {
    hidden: !n || n.hidden,
    text: n ? n.textContent.replace(/\s+/g, " ").trim() : "",
    html: n ? n.innerHTML : "",
  };
};

async function switchLang(page, lang) {
  await page.evaluate((l) => {
    const sel = document.querySelector("#cyberLang");
    sel.value = l;
    sel.dispatchEvent(new Event("change", { bubbles: true }));
  }, lang);
  await page.waitForFunction((l) => window.CYBER_I18N.getLang() === l, lang, { timeout: 20000 });
}

async function main() {
  let chromium;
  try {
    ({ chromium } = require("playwright"));
  } catch (e) {
    console.log("(skip) 没装 playwright");
    return 0;
  }

  const COPY = readDenyCopy();
  console.log("文案（取自 cyber-reviews.js）: " + COPY.slice(0, 40) + "…");

  const packs = {};
  for (const lang of LANGS) packs[lang] = loadPack(lang);

  // 先静态钉一遍：每份语言包都得有这一整句（缺一条那门语言就会挂中文）。
  for (const lang of LANGS) {
    check(lang + "：语言包里有这一整句", !!packs[lang][COPY]);
  }

  const server = await serve();
  const browser = await chromium.launch(
    process.env.KARMA_CHROME ? { executablePath: process.env.KARMA_CHROME } : {}
  );
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e && e.message ? e.message : e)));

  try {
    // 页面还没跑起来就把「跟谁说话」和会话摆好（否则请求会打到 127.0.0.1:8000）。
    await page.addInitScript((base) => {
      try {
        localStorage.setItem("karma_cyber_api_base", base);
        sessionStorage.setItem("karma_console_access_token", "reviews-copy-probe");
        sessionStorage.setItem("karma_console_identity", "kid_5f0aa8ccf7483983a8a2a5a9");
      } catch (e) {}
    }, "http://127.0.0.1:" + PORT);

    await page.goto(PAGE, { waitUntil: "load" });
    await page.waitForFunction(() => !!window.CYBER_I18N && !!window.KarmaReviewsConsole, null, { timeout: 30000 });

    console.log("[1] 中文页：403 之后那句提示是原文");
    // 页面自己的引导是异步的（会话恢复 → 页面事件），喊一次没响应就再喊一次。
    for (let attempt = 0; attempt < 3; attempt += 1) {
      await openReviewsQueue(page);
      try {
        await page.waitForFunction(() => {
          const n = document.querySelector("#rv-deny");
          return !!n && !n.hidden && n.textContent.trim().length > 0;
        }, null, { timeout: 8000 });
        break;
      } catch (e) {
        if (attempt === 2) throw e;
      }
    }
    let got = await page.evaluate(READ_DENY);
    check("提示真的露出来了", got.hidden === false);
    check("中文页就是这句话的原文", got.text === COPY, got.text);
    check("不再写死 GOVERNANCE_VERIFIER_IDS", got.html.indexOf("GOVERNANCE_VERIFIER_IDS") < 0);

    console.log("[2] 切到五门语言：这句提示不留一个汉字");
    for (const lang of LANGS) {
      await switchLang(page, lang);
      const want = packs[lang][COPY];
      await page.waitForFunction(
        (w) => {
          const n = document.querySelector("#rv-deny");
          return !!n && n.textContent.replace(/\s+/g, " ").trim() === w;
        },
        want,
        { timeout: 20000 }
      );
      got = await page.evaluate(READ_DENY);
      check(lang + "：换成了这门语言（逐字）", got.text === want, { got: got.text, want: want });
      if (lang === "ja") {
        // 日文本来就用汉字：改用「中文原文有没有原样留下」这把尺子。
        check("ja：中文原文没有原样留在页面上", got.text.indexOf(COPY) < 0, got.text);
      } else {
        check(lang + "：没有残留汉字", !CJK.test(got.text), got.text);
      }
    }

    console.log("[3] 切回中文：提示回到原文（不是卡在上一门语言）");
    await switchLang(page, "zh-CN");
    await page.waitForFunction(
      (w) => {
        const n = document.querySelector("#rv-deny");
        return !!n && n.textContent.replace(/\s+/g, " ").trim() === w;
      },
      COPY,
      { timeout: 20000 }
    );
    check("中文页回到原文", (await page.evaluate(READ_DENY)).text === COPY);

    check("全程没有未捕获的页面错误", errors.length === 0, errors.slice(0, 3));
  } finally {
    await page.close();
    await browser.close();
    server.close();
  }

  console.log("");
  console.log(checks + " checks, " + failures + " failed");
  return failures === 0 ? 0 : 1;
}

main()
  .then((code) => process.exit(code))
  .catch((e) => {
    console.error(e);
    process.exit(1);
  });
