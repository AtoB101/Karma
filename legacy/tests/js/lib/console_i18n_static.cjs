/**
 * 操作台 i18n · 静态扫描口径（供 tests/js/test_console_agent_onestop_i18n.cjs 与
 * tests/js/test_console_runtime_i18n.cjs 共用）。
 *
 * 为什么要单独立一份：操作台的文案大半是**运行期拼出来**的 ——
 *
 *     left.textContent = "剩余 " + mm + ":" + ss + " · 交给 agent 后它就能领凭据了";
 *
 * 整句在源码里根本不存在，只 grep 中文串查不到；而它又只在「走到那个状态」时才渲染，
 * 逐页点过去的成本很高。这里把「+ 拼接」按浏览器实际形成的文本节点还原成运行时那句
 * （占位符 -> {n}），再照 i18n-cyber.js 的规则查五门语言，覆盖走不到的分支。
 *
 * 判定口径跟渲染器 translateTextNode 完全一致：先 lookup，查不到再 lookupLoose 兜底。
 */
"use strict";

const fs = require("fs");
const path = require("path");
const H = require("./console_i18n_harness.cjs");

const LANGS = H.LANGS;
const HAN = /[\u4e00-\u9fff]/;
const ATTR_RE = /(placeholder|title|aria-label|alt)\s*=\s*"([^"]*)"/g;
const ATTR_ONLY_RE = /^\s*(placeholder|title|aria-label|alt)\s*=/;
const STOP = "+;,=?:" + String.fromCharCode(38) + "|";
/**
 * 这些名字里塞的串不是文案，是被拿去比对 / 切分的：
 *     entry.title.indexOf("任务结算 · ") !== 0
 * 它们不该当成「界面上会出现的一句」来查译表。
 */
const NON_DISPLAY = /(?:indexOf|lastIndexOf|startsWith|endsWith|includes|split|replace|match|test|search|localeCompare|JSON\.parse|parseFloat|parseInt|Number|String|Boolean|Error)\s*\(\s*$/;

/**
 * 核心包的调用形态：tr("pick.role_agent", "注册代理身份") / addHead / addPickerHead。
 * 这类调用走的是 key（核心包里必须有），中文只是「查不到时」的兜底 —— 两条都得查。
 */
const CORE_CALL = /\b(?:tr|addHead|addPickerHead)\(\s*"[A-Za-z][A-Za-z0-9_.-]*"\s*,\s*"(?:[^"\\]|\\.)*"/g;

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

/**
 * 判一句：译文缺失 / 译文里还留汉字（日语除外）/ 日语里留着简体中文词 —— 都算漏。
 * 返回 null 表示这一句过关。
 */
function verdict(lang, out) {
  if (out == null) return "无译文";
  if (lang !== "ja" && HAN.test(out)) return "译文里还留汉字：" + out.slice(0, 60);
  if (lang === "ja" && (out.indexOf("激活") >= 0 || out.indexOf("额度") >= 0)) return "日语里留着简体词：" + out.slice(0, 60);
  return null;
}

/** 五门语言的翻译引擎（每个语言只起一次沙箱）。 */
function createEngine() {
  const cache = {};
  return async function engine(lang) {
    if (!cache[lang]) {
      const env = H.boot(lang, {});
      const I = env.window.CYBER_I18N;
      await new Promise(function (r) { I.ensureExt(lang, r); });
      cache[lang] = I;
    }
    return cache[lang];
  };
}

/**
 * 扫一组脚本里的中文字面量：每条都还原成运行时那句（含走不到的分支），逐个语言判一遍。
 * on({file, lang, piece, bad}) 对每「句 × 语言」都调一次，bad 为 null 表示过关。
 */
async function scanFiles(files, engine, on) {
  let pieces = 0;
  for (const f of files) {
    const src = stripComments(fs.readFileSync(path.join(H.SCRIPTS, f), "utf8"));
    const lits = literals(src);
    const byStart = new Map(lits.map(function (l, i) { return [l.start, i]; }));
    const byEnd = new Map(lits.map(function (l, i) { return [l.end, i]; }));
    const consumed = new Set();
    const cands = [];
    const coreEntries = [];
    CORE_CALL.lastIndex = 0;
    let cm;
    while ((cm = CORE_CALL.exec(src))) {
      const vi = byEnd.get(cm.index + cm[0].length);
      if (vi == null) continue;
      const keyM = /"([A-Za-z][A-Za-z0-9_.-]*)"/.exec(cm[0]);
      if (keyM) { coreEntries.push({ key: keyM[1], zh: lits[vi].value }); consumed.add(vi); }
    }
    for (let i = 0; i < lits.length; i += 1) {
      if (!HAN.test(lits[i].value)) continue;
      if (consumed.has(i)) continue;
      if (NON_DISPLAY.test(src.slice(0, lits[i].start))) { consumed.add(i); continue; }
      if (nextIsPlus(src, lits[i].end) && !prevIsPlus(src, lits[i].start)) {
        const c = operandsOf(src, lits, byStart, i);
        for (let j = i; j <= c.last; j += 1) consumed.add(j);
        cands.push({ kind: "chain", text: buildKey(c.ops) });
        continue;
      }
      if (prevIsPlus(src, lits[i].start)) continue;
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
        pieces += 1;
        for (const lang of LANGS) {
          if (looksTargetLang(lang, piece)) { on({ file: f, lang: lang, piece: piece, bad: null }); continue; }
          const I = await engine(lang);
          const r = H.resolveIn(I, lang, piece.replace(/\{\d+\}/g, "X9"));
          on({ file: f, lang: lang, piece: piece, bad: verdict(lang, r.out) });
        }
      }
    }
    // 核心包调用：key 必须在核心包里有译文；查不到时会回落到中文兜底，所以兜底那句
    // 也得在词表里 —— 两条都查不到，界面上就是一句中文。
    for (const info of coreEntries) {
      pieces += 1;
      for (const lang of LANGS) {
        const I = await engine(lang);
        let out = null;
        try { out = I.t(info.key); } catch (e) { out = null; }
        if (out && out !== info.key) {
          on({ file: f, lang: lang, piece: info.key, bad: verdict(lang, out) });
          continue;
        }
        if (!HAN.test(info.zh)) { on({ file: f, lang: lang, piece: info.key, bad: null }); continue; }
        let hit = null;
        try { hit = I.lookup(info.zh); if (hit == null) hit = I.lookupLoose(info.zh); } catch (e) { hit = null; }
        let bad = null;
        if (hit == null) bad = "核心包没有这条 key，词表里也没有中文兜底";
        else bad = verdict(lang, hit);
        on({ file: f, lang: lang, piece: info.key, bad: bad });
      }
    }

  }

  return { files: files.length, pieces: pieces };
}

module.exports = {
  LANGS, HAN, STOP, ATTR_RE, ATTR_ONLY_RE,
  stripComments, unq, literals, prevIsPlus, nextIsPlus, operandsOf, buildKey, segmentsOf,
  looksTargetLang, verdict, createEngine, scanFiles,
};
