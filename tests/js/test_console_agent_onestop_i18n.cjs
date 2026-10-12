/**
 * 操作台 · Agent 接入一条龙（授权向导 / 接入一个 Agent / 输匹配码 / 配对码接入）
 * 的运行期文案：五门语言下不许再冒中文。
 *
 * 为什么单独立一条门禁
 * --------------------
 * 这条链（cyber-pairing / cyber-bind-requests / cyber-handoff / cyber-key-calls /
 * cyber-unbind-keys / karma-service-spec）的文案大半是**运行期拼出来**的：
 *
 *     left.textContent = "剩余 " + mm + ":" + ss + " · 交给 agent 后它就能领凭据了";
 *     note.textContent = "确认邮件已发到 " + (ec.email_masked || "你的邮箱") + "。把这串码报给 agent…";
 *
 * 整句在源码里根本不存在，只 grep 中文串查不到；而它又只在「走到那个状态」时才渲染，
 * 逐页点过去的成本很高 —— 上一轮就是这么漏掉了整块「邮箱回执（第三把锁）」的文案，
 * 非中文界面上直接冒出一段中文。
 *
 * 这一条门禁按**两种口径**同时钉住：
 *   A. 静态：把六个脚本里所有中文字面量按「+ 拼接」还原成运行时那句（占位符 -> {n}），
 *      再照 i18n-cyber.js 的规则查五门语言 —— 覆盖走不到的分支（如各类「XX失败：」）。
 *   B. 真跑：在 vm 沙箱里真的加载这六个脚本、真的把状态推到「有待确认 / 已批准 +
 *      邮箱回执 / 交接码 / 已绑定钥匙」，再抽渲染出来的每一句查一遍 —— 拼出来的
 *      那句话真的成形了才算数。
 *
 * 判定口径跟渲染器 translateTextNode 完全一致：先 lookup，查不到再 lookupLoose 兜底。
 *
 * 跑法：node tests/js/test_console_agent_onestop_i18n.cjs
 */
"use strict";

const fs = require("fs");
const path = require("path");
const H = require("./lib/console_i18n_harness.cjs");

const ROOT = path.resolve(__dirname, "..", "..");
const SCRIPTS = path.join(ROOT, "apps", "console", "scripts");
const LANGS = ["en", "ja", "ko", "es-AR", "es-SV"];

/** 这条链上的六个脚本：接入确认两个宿主 + 交付包 + 配对 + 调用面板 + 硬指标表单。 */
const CHAIN_FILES = [
  "cyber-pairing.js",
  "cyber-bind-requests.js",
  "cyber-handoff.js",
  "cyber-key-calls.js",
  "cyber-unbind-keys.js",
  "karma-service-spec.js",
];

const HAN = /[\u4e00-\u9fff]/;
const ATTR_RE = /(placeholder|title|aria-label|alt)\s*=\s*"([^"]*)"/g;
const ATTR_ONLY_RE = /^\s*(placeholder|title|aria-label|alt)\s*=/;
const STOP = "+;,=?:" + String.fromCharCode(38) + "|";

let failures = 0;
let checks = 0;

function check(name, cond, extra) {
  checks += 1;
  if (cond) return;
  failures += 1;
  console.error("FAIL: " + name + (extra ? " -- " + extra : ""));
}

/* ------------------------------------------------------------------ 源码切片 */

function stripComments(s) {
  let out = s.replace(/\/\*[\s\S]*?\*\//g, function (m) { return " ".repeat(m.length); });
  out = out.replace(/(^|[^:\\])\/\/[^\n]*/g, function (m, p1) { return p1 + " ".repeat(m.length - p1.length); });
  return out;
}

function unq(raw) {
  const body = raw.slice(1, -1);
  let out = "";
  for (let i = 0; i < body.length; i += 1) {
    const c = body[i];
    if (c !== "\\") { out += c; continue; }
    const n = body[++i];
    if (n === "n") out += "\n";
    else if (n === "t") out += "\t";
    else if (n === "r") out += "\r";
    else if (n === "u") { out += String.fromCharCode(parseInt(body.substr(i + 1, 4), 16)); i += 4; }
    else out += n;
  }
  return out;
}

function literals(s) {
  const re = /"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'|`(?:[^`\\]|\\.)*`/g;
  const out = [];
  let m;
  while ((m = re.exec(s))) out.push({ start: m.index, end: m.index + m[0].length, value: unq(m[0]) });
  return out;
}

function prevIsPlus(src, start) {
  let p = start - 1;
  while (p >= 0 && /\s/.test(src[p])) p -= 1;
  return src[p] === "+";
}

function nextIsPlus(src, end) {
  let q = end;
  while (q < src.length && /\s/.test(src[q])) q += 1;
  return src[q] === "+";
}

/** 一次 + 拼接 = 若干「操作数」：字面量，或一段表达式（括号里的整体算一段）。 */
function operandsOf(src, lits, byStart, i) {
  const ops = [{ lit: lits[i].value }];
  let pos = lits[i].end;
  let last = i;
  for (let guard = 0; guard < 300; guard += 1) {
    const m = /^\s*\+/.exec(src.slice(pos));
    if (!m) break;
    pos += m[0].length;
    while (pos < src.length && /\s/.test(src[pos])) pos += 1;
    const li = byStart.get(pos);
    if (li != null) { ops.push({ lit: lits[li].value }); pos = lits[li].end; last = li; continue; }
    const startPos = pos;
    let depth = 0;
    while (pos < src.length) {
      const ch = src[pos];
      const lj = byStart.get(pos);
      if (lj != null) { pos = lits[lj].end; continue; }
      if (ch === "(" || ch === "[" || ch === "{") { depth += 1; pos += 1; continue; }
      if (ch === ")" || ch === "]" || ch === "}") {
        if (depth === 0) break;
        depth -= 1; pos += 1; continue;
      }
      if (depth === 0 && STOP.indexOf(ch) >= 0) break;
      pos += 1;
    }
    if (pos === startPos) break;
    ops.push({ expr: src.slice(startPos, pos) });
    if (src[pos] !== "+") break;
  }
  return { ops: ops, last: last };
}

function buildKey(ops) {
  let out = "";
  let n = 0;
  ops.forEach(function (o) {
    if (o.lit != null) out += o.lit;
    else out += "{" + n++ + "}";
  });
  return out;
}

/**
 * 把源码拼出来的串，按浏览器实际形成的文本节点切开：
 * 一个 <tag> 就是一条边界；{n} 若「前后都是标签」（'<td>' + x + '</td>'），
 * 它自己就是一个独立文本节点 —— 丢掉；否则它跟旁边的字拼在同一句里，必须留着
 * （'<span>' + title + " · 共 " + n + " 项" 就是一句）。
 */
function segmentsOf(cand) {
  const out = [];
  let buf = "";
  const flush = function () {
    const t = buf.replace(/\s+/g, " ").trim();
    if (t) out.push(t);
    buf = "";
  };
  let i = 0;
  while (i < cand.length) {
    const ch = cand[i];
    if (ch === "<") {
      const gt = cand.indexOf(">", i);
      if (gt < 0) { i += 1; continue; }
      flush();
      i = gt + 1;
      continue;
    }
    const m = /^\{\d+\}/.exec(cand.slice(i));
    if (m) {
      const prev = i > 0 ? cand[i - 1] : "";
      const next = cand[i + m[0].length] || "";
      if (prev === ">" && next === "<") { flush(); i += m[0].length; continue; }
      buf += m[0];
      i += m[0].length;
      continue;
    }
    buf += ch;
    i += 1;
  }
  flush();
  return out;
}

/* ------------------------------------------------------------------ 语言引擎 */

const ENGINES = {};

async function engine(lang) {
  if (!ENGINES[lang]) {
    const env = H.boot(lang, {});
    const I = env.window.CYBER_I18N;
    await new Promise(function (r) { I.ensureExt(lang, r); });
    ENGINES[lang] = I;
  }
  return ENGINES[lang];
}

/**
 * 判一句：译文缺失 / 译文里还留汉字（日语除外）/ 日语里留着简体中文词 —— 都算漏。
 * 返回 null 表示这一句过关。
 */
/**
 * 这一句是不是「已经就是目标语言」了？
 *
 * 有些脚本不是等引擎兜底翻，而是直接 T()/Tf() 把译文写进 DOM（比如「查看最近调用」）。
 * 那种句子在沙箱里拿到的就是日语/韩语，再拿它去查表当然查不到 —— 那不是漏译。
 * 判据用假名/谚文：中文原文里不会有这些字符。
 */
function looksTargetLang(lang, text) {
  if (lang === "ja") return /[\u3040-\u30ff]/.test(text);
  if (lang === "ko") return /[\uac00-\ud7af]/.test(text);
  return false;
}

function verdict(lang, out) {
  if (out == null) return "无译文";
  if (lang !== "ja" && HAN.test(out)) return "译文里还留汉字：" + out.slice(0, 60);
  if (lang === "ja" && (out.indexOf("激活") >= 0 || out.indexOf("额度") >= 0)) return "日语里留着简体词：" + out.slice(0, 60);
  return null;
}

/* ------------------------------------------------------------------ A. 静态扫描 */

async function staticAudit(report) {
  for (const f of CHAIN_FILES) {
    const src = stripComments(fs.readFileSync(path.join(SCRIPTS, f), "utf8"));
    const lits = literals(src);
    const byStart = new Map(lits.map(function (l, i) { return [l.start, i]; }));
    const consumed = new Set();
    const cands = [];
    for (let i = 0; i < lits.length; i += 1) {
      if (!HAN.test(lits[i].value)) continue;
      if (nextIsPlus(src, lits[i].end) && !prevIsPlus(src, lits[i].start)) {
        const c = operandsOf(src, lits, byStart, i);
        for (let j = i; j <= c.last; j += 1) consumed.add(j);
        cands.push({ kind: "chain", text: buildKey(c.ops) });
        continue;
      }
      if (prevIsPlus(src, lits[i].start) || consumed.has(i)) continue;
      cands.push({ kind: "lit", text: lits[i].value });
    }
    for (const cand of cands) {
      let list;
      if (ATTR_ONLY_RE.test(cand.text)) {
        // 「 placeholder="如 3.50（必须是字符串）"」这种属性串：引擎翻的是属性值本身，
        // 拿带 placeholder= 的外壳去查必然查不到（那是包装，不是文案）。
        list = [];
        ATTR_RE.lastIndex = 0;
        let am;
        while ((am = ATTR_RE.exec(cand.text))) list.push(am[2]);
      } else {
        list = segmentsOf(cand.text);
      }
      for (const rawPiece of list) {
        const piece = rawPiece.replace(/\s+/g, " ").trim();
        if (!HAN.test(piece)) continue;
        for (const lang of LANGS) {
          if (looksTargetLang(lang, piece)) continue;
          const I = await engine(lang);
          const r = H.resolveIn(I, lang, piece.replace(/\{\d+\}/g, "X9"));
          const bad = verdict(lang, r.out);
          check(
            "静态 " + f + " [" + lang + "] " + piece.slice(0, 60),
            !bad,
            (bad || "") + (bad && /引擎抛错/.test(bad) ? "" : "  <= " + piece.slice(0, 90))
          );
        }
      }
    }
  }
  report("A. 静态扫描：" + CHAIN_FILES.length + " 个脚本 × " + LANGS.length + " 门语言");
}

/* ------------------------------------------------------------------ B. 真跑渲染 */

const KEY = "40dd572ce5491bd0077b48ce147acbce";

function apiBag() {
  const bag = {
    KARMA_IDENTITY_ID: "kid_test",
    sessionStorage: { getItem: function () { return null; }, setItem: function () {} },
    confirm: function () { return true; },
    KarmaWalletAuth: {
      activeProvider: function () {
        return {
          request: async function (o) {
            return o.method === "eth_requestAccounts" ? ["0xabc"] : "0xsig";
          },
        };
      },
    },
    KarmaAuthorize: {
      buildCreateKeyMsg: function () { return "msg"; },
      pyUtcIso: function () { return "2026-01-01T00:00:00Z"; },
      PERMS: [{ id: "place_order", label_zh: "下单" }],
      DEFAULT_PERMS: ["place_order"],
    },
    cyberKarmaApi: {
      listMyAgents: async function () {
        return {
          agents: [{
            agent_id: "agent-1", name: "sh-kitchen-01", p1_ready: false,
            owner_identity_id: "kid_test", agent_class: "merchant", vertical: "food",
            p1_missing: ["连接钱包", "证件正面"],
          }],
        };
      },
      listRoleProfiles: async function () { return { profiles: [] }; },
      listOnboardingIndustries: async function () {
        return {
          industries: [{
            industry_id: "food", vertical: "food", title_zh: "餐饮配送", title_en: "Food delivery",
            spec: [{ path: "max_price", type: "price", description_zh: "单笔最高价（USDC）", description_en: "Max price per order (USDC)", required: true }],
            example: { max_price: "12.00" },
          }],
        };
      },
      getOnboardingIndustry: async function () {
        return { industry: { industry_id: "food", title_zh: "餐饮配送", title_en: "Food delivery", spec: [] } };
      },
      lookupPairing: async function () {
        return {
          status: "pending", agent_id: "agent-1", agent_name: "sh-kitchen-01",
          public_key_fingerprint: "ed25519:abc", activation_mode: "pairing",
          vertical: "food", requested_spec: { max_price: "1.00" },
        };
      },
      issuePairingHandoff: async function () {
        return { handoff_code: "HANDOFF-9", handoff_state: "active", handoff_expires_at: new Date(Date.now() + 150000).toISOString() };
      },
      approvePairing: async function () {
        return {
          agent: { agent_id: "agent-1", name: "sh-kitchen-01" },
          email_confirm: { required: true, state: "pending", match_code: "384756", email_masked: "h***@x" },
        };
      },
      denyPairing: async function () { return {}; },
      attachPairingRuntimeKey: async function () { return {}; },
      resendPairingEmail: async function () {
        return { match_code: "111222", email_masked: "h***@x", expires_at: "2026-10-12T21:00:00Z" };
      },
      putAutomationPolicy: async function () { return {}; },
      getAutomationPolicy: async function () {
        return { permissions: ["place_order"], single_limit: 1, daily_limit: 2 };
      },
      ownerRevokeAgent: async function () { return {}; },
      karmaFetch: async function () { return { p1_ready: false, gaps: ["连接钱包"] }; },
    },
    karmaRuntimeApi: {
      runtimeListPendingBinds: async function () {
        return {
          requests: [
            { key_id: KEY, agent_id: "agent-1", agent_name: "sh-kitchen-01", agent_fingerprint: "ed25519:abc",
              expires_at: "2026-10-12T20:30:08Z", attempts_left: 3, expired: false, key_binding: "service" },
            { key_id: "k-old", agent_id: "agent-2", agent_name: "old-agent",
              expires_at: "2026-10-12T19:00:00Z", attempts_left: 0, expired: true },
          ],
        };
      },
      runtimeListKeys: async function () {
        return {
          keys: [
            { key_id: KEY, status: "active", key_binding: "service", single_limit: "1.00", daily_limit: "2.00",
              expires_at: "2026-09-30T00:00:00Z", agent_id: "agent-1",
              pending_binding: { agent_fingerprint: "ed25519:abc", expires_at: "2026-10-12T20:30:08Z", attempts_left: 3, expired: false } },
            { key_id: "k3", status: "active", key_binding: "agent", single_limit: "5.00", daily_limit: "9.00",
              agent_id: "agent-1", pending_binding: { expired: true } },
          ],
        };
      },
      runtimeListBoundKeys: async function () {
        return {
          keys: [{
            key_id: "k3", key_binding: "agent", status: "active", single_limit: "5.00", daily_limit: "9.00",
            expires_at: "2026-11-01T00:00:00Z", agent_id: "agent-1", agent_name: "sh-kitchen-01",
            agent_fingerprint: "ed25519:abc",
          }],
        };
      },
      runtimeKeyCalls: async function () {
        return { calls: [{ at: "2026-10-12T20:00:00Z", method: "POST", path: "/runtime/bind-key", status: 403, detail: "waiting for the code" }] };
      },
      runtimeCreateKey: async function () { return { runtime_key: "rk_test", key_id: "k1", expire_time: "" }; },
      runtimeConfirmBindKey: async function () { return {}; },
      runtimeRejectBindKey: async function () { return {}; },
      runtimeUnbindKey: async function () { return {}; },
      runtimeAckNotice: async function () { return {}; },
    },
  };
  return bag;
}

const flush = function () { return new Promise(function (r) { setTimeout(r, 0); }); };

function collect(env) {
  const parts = [];
  Object.keys(env.nodes).forEach(function (id) {
    const n = env.nodes[id];
    if (n.innerHTML) parts.push(n.innerHTML);
    if (String(n.textContent || "").trim()) parts.push(String(n.textContent));
    Object.keys(n.attrs).forEach(function (k) {
      if (/^(placeholder|title|aria-label|alt)$/.test(k)) parts.push(n.attrs[k]);
    });
  });
  return parts;
}

async function drive(env) {
  const w = env.window;
  env.run("karma-service-spec.js");
  env.run("cyber-key-calls.js");
  env.run("cyber-handoff.js");
  env.run("cyber-bind-requests.js");
  env.run("cyber-pairing.js");
  env.run("cyber-unbind-keys.js");

  // ① 接入确认：空态 -> 有待确认（含过期那条）-> 设置页兜底宿主
  await w.KarmaBindRequests.refresh();
  await flush();
  // ② 交付包：三把钥匙（一把待绑 + 一把已绑）+ 找不到 agent
  await w.KarmaHandoff.open("agent-1", true);
  await flush();
  w.cyberKarmaApi.listMyAgents = async function () { return { agents: [] }; };
  await w.KarmaHandoff.open("nope", false);
  await flush();
  w.cyberKarmaApi.listMyAgents = async function () {
    return { agents: [{ agent_id: "agent-1", name: "sh-kitchen-01", owner_identity_id: "kid_test" }] };
  };
  // ③ 配对：没填码 -> 待批准 -> 已批准（交接码 + 邮箱回执待点）-> 已确认 -> 已过期
  await w.KarmaPairing.reload();
  await flush();
  env.byId("pair-code").value = "K4QP-3M2X";
  await w.KarmaPairing.reload();
  await flush();
  w.cyberKarmaApi.lookupPairing = async function () {
    return {
      status: "approved", agent_id: "agent-1", agent_name: "sh-kitchen-01",
      public_key_fingerprint: "ed25519:abc",
      handoff_code: "HANDOFF-9", handoff_state: "active",
      handoff_expires_at: new Date(Date.now() + 150000).toISOString(),
      email_confirm: { required: true, state: "pending", match_code: "384756", email_masked: "h***@x" },
    };
  };
  await w.KarmaPairing.reload();
  await flush();
  // 重发：填一次通知邮箱，点「重新发一封确认邮件」
  env.byId("pair-notify-email").value = "me@example.com";
  if (env.byId("pair-email-resend").handlers.click) {
    env.byId("pair-email-resend").handlers.click[0]();
    await flush();
    await flush();
  }
  env.byId("pair-notify-email").value = "not-an-email";
  if (env.byId("pair-email-resend").handlers.click) {
    env.byId("pair-email-resend").handlers.click[0]();
    await flush();
  }
  // 回执已确认 / 已过期两条分支
  w.cyberKarmaApi.lookupPairing = async function () {
    return {
      status: "approved", agent_id: "agent-1", agent_name: "sh-kitchen-01",
      email_confirm: { required: true, state: "confirmed", match_code: "384756", email_masked: "h***@x" },
    };
  };
  await w.KarmaPairing.reload();
  await flush();
  w.cyberKarmaApi.lookupPairing = async function () {
    return {
      status: "approved", agent_id: "agent-1", agent_name: "sh-kitchen-01",
      email_confirm: { required: true, state: "expired", match_code: "384756", email_masked: "h***@x" },
    };
  };
  await w.KarmaPairing.reload();
  await flush();
  // 查询报错（配对码过期）
  w.cyberKarmaApi.lookupPairing = async function () { throw new Error("pairing code expired"); };
  await w.KarmaPairing.reload();
  await flush();
  // ④ 已绑定钥匙清单 + 钥匙事件计数
  await w.KarmaUnbindKeys.refresh();
  await flush();
  await w.KarmaUnbindKeys.refresh();
  await flush();
}

async function renderAudit(report) {
  for (const lang of LANGS) {
    const env = H.boot(lang, apiBag());
    const I = env.window.CYBER_I18N;
    await new Promise(function (r) { I.ensureExt(lang, r); });
    await drive(env);
    let seen = 0;
    let bad = 0;
    collect(env).forEach(function (html) {
      H.harvest(html).forEach(function (piece) {
        if (!HAN.test(piece)) return;
        if (looksTargetLang(lang, piece)) return;
        seen += 1;
        const r = H.resolveIn(I, lang, piece);
        const why = verdict(lang, r.out);
        if (why) {
          bad += 1;
          check("渲染 [" + lang + "] " + piece.slice(0, 60), false, why);
        }
      });
    });
    check("渲染 [" + lang + "] 真的渲染出了带中文的句子（不是空跑）", seen > 0, "seen=" + seen);
    report("B. 真跑渲染 [" + lang + "]：抽到 " + seen + " 句，漏译 " + bad + " 句");
  }
}

/* ------------------------------------------------------------------ main */

async function main() {
  const lines = [];
  const report = function (s) { lines.push(s); };
  await staticAudit(report);
  await renderAudit(report);
  lines.forEach(function (l) { console.log(l); });
  console.log((failures ? "FAILED " : "ok  ") + "console agent one-stop i18n: " + (checks - failures) + "/" + checks + " checks passed");
  process.exit(failures ? 1 : 0);
}

main().catch(function (e) {
  console.error(e);
  process.exit(2);
});
