/**
 * Karma Console — 节点层（去中心化的接入面）。
 *
 * 操作台是纯静态页面，谁都能拿一份跑起来；「跟谁说话」必须是用户自己选、
 * 自己换的。这一层只干三件事：
 *
 *   1. 节点表：内置引导节点 + 用户自己添的节点，任何页面共用同一份。
 *   2. 体检：探活 /health 并量一次往返耗时，慢的/挂的当场看得见。
 *   3. 容灾：当前节点连不上时自动切到下一个能用的（可关），并记住选择。
 *
 * 唯一事实来源仍是 localStorage 的 karma_cyber_api_base —— 切节点就是改这个键，
 * 所以 cyber-console.js / karma-public-api.js 不用改口径，老的本地设置也不会失效。
 */
(function (global) {
  "use strict";

  var LS_BASE = "karma_cyber_api_base";
  var LS_NODE_ID = "karma_console_node_id";
  var LS_CUSTOM = "karma_console_nodes";
  var LS_AUTOFAIL = "karma_console_node_autofail";

  var HEALTH_PATH = "/health";
  var PROBE_TIMEOUT_MS = 4000;
  var FAILOVER_TIMEOUT_MS = 2500;
  var FAILOVER_MIN_GAP_MS = 15000;
  var MAX_CUSTOM = 8;

  /** 内置引导节点。base 为空串 = 同源：页面从哪儿来就问哪儿。 */
  var BUILTIN = [
    { id: "same-origin", label: "当前站点（同源）", base: "", official: true },
    { id: "official", label: "karma-network.ai", base: "https://karma-network.ai", official: true },
    { id: "local", label: "本机 API（127.0.0.1:8000）", base: "http://127.0.0.1:8000", dev: true }
  ];

  var listeners = [];
  var probeCache = {};
  var failingOver = false;
  var lastFailoverAt = 0;

  /* ---------------------------------------------------------------- 存储 */

  function lsGet(key) {
    try {
      var s = global.localStorage;
      return s ? s.getItem(key) : null;
    } catch (_) {
      return null;
    }
  }

  function lsSet(key, val) {
    try {
      var s = global.localStorage;
      if (s) s.setItem(key, val);
    } catch (_) {}
  }

  function lsDel(key) {
    try {
      var s = global.localStorage;
      if (s) s.removeItem(key);
    } catch (_) {}
  }

  /* ------------------------------------------------------------ 纯函数 */

  function host() {
    try {
      return (global.location && global.location.hostname) || "";
    } catch (_) {
      return "";
    }
  }

  /** 页面自己就在本机（file:// / localhost / 127.0.0.1）时，本机节点才有意义。 */
  function isLocalPage() {
    var h = host();
    return h === "localhost" || h === "127.0.0.1" || h === "::1" || h === "";
  }

  function trimBase(base) {
    return String(base == null ? "" : base).trim().replace(/\/+$/, "");
  }

  /** 只认 http/https；空串代表同源。挡掉 javascript: / data: 这类塞进配置里的东西。 */
  function isValidBase(base) {
    var b = trimBase(base);
    if (b === "") return true;
    return /^https?:\/\/[^\s]+$/i.test(b);
  }

  /**
   * 把一条配置解析成真正要请求的地址。
   * 空串：本机页面 -> 本机 API；线上页面 -> 同源。
   */
  function resolveBase(base) {
    var b = trimBase(base);
    if (b !== "") return b;
    if (isLocalPage()) return "http://127.0.0.1:8000";
    try {
      return (global.location && global.location.origin) || "";
    } catch (_) {
      return "";
    }
  }

  function officialNodes() {
    return isLocalPage() ? BUILTIN.slice() : BUILTIN.filter(function (n) { return !n.dev; });
  }

  /* ---------------------------------------------------------- 节点表 */

  function readCustom() {
    var raw = lsGet(LS_CUSTOM);
    if (!raw) return [];
    var arr;
    try {
      arr = JSON.parse(raw);
    } catch (_) {
      return [];
    }
    if (!Array.isArray(arr)) return [];
    var out = [];
    arr.forEach(function (n) {
      if (!n || !n.id) return;
      if (!isValidBase(n.base)) return;
      if (trimBase(n.base) === "") return;
      out.push({ id: String(n.id), label: String(n.label || ""), base: trimBase(n.base), custom: true });
    });
    return out.slice(0, MAX_CUSTOM);
  }

  function writeCustom(arr) {
    lsSet(LS_CUSTOM, JSON.stringify(arr.slice(0, MAX_CUSTOM)));
  }

  /**
   * 老设置里那份手填/历史地址（karma_cyber_api_base 有值但不在节点表里）。
   *
   * 必须把它显出来，不能让它悄悄落到「当前站点（同源）」上：
   * 用户在「连接设置」里手填过一台自建节点，划到这儿就变成另一台机器了。
   * 所以合成一个条目挂进列表，用户能看见、能切走、也能删。
   */
  function legacyNode() {
    var raw = lsGet(LS_BASE);
    if (raw === null) return null;
    var base = trimBase(raw);
    if (base === "" || !isValidBase(base)) return null;
    var known = officialNodes().concat(readCustom());
    for (var i = 0; i < known.length; i += 1) {
      if (normalizeForCompare(known[i].base) === normalizeForCompare(base)) return null;
    }
    return { id: "legacy:" + base.toLowerCase(), label: base, base: base, custom: true, legacy: true };
  }

  function allNodes() {
    var builtin = officialNodes().map(function (n) {
      return { id: n.id, label: n.label, base: n.base, official: !!n.official, dev: !!n.dev, custom: false };
    });
    var out = builtin.concat(readCustom());
    var legacy = legacyNode();
    if (legacy) out.push(legacy);
    return out;
  }

  function normalizeForCompare(base) {
    return trimBase(base).toLowerCase();
  }

  /** 当前选中的节点：先看显式 id，再按 base 反查，最后回落到条目表第一条。 */
  function currentId() {
    var nodes = allNodes();
    var id = lsGet(LS_NODE_ID) || "";
    var base = lsGet(LS_BASE);
    var want = normalizeForCompare(base == null ? "" : base);
    var byId = null;
    for (var i = 0; i < nodes.length; i += 1) {
      if (nodes[i].id === id) {
        byId = nodes[i];
        break;
      }
    }
    // base 才是事实来源：id 与它对不上时以 base 为准 ——
    // 「连接设置」里手填过地址、或另一个标签页切过节点，都会出现这种错位。
    if (byId && normalizeForCompare(byId.base) === want) return byId.id;
    for (var j = 0; j < nodes.length; j += 1) {
      if (normalizeForCompare(nodes[j].base) === want) return nodes[j].id;
    }
    if (byId) return byId.id;
    return nodes.length ? nodes[0].id : "";
  }

  function findNode(id) {
    var nodes = allNodes();
    for (var i = 0; i < nodes.length; i += 1) {
      if (nodes[i].id === id) return nodes[i];
    }
    return null;
  }

  function current() {
    var node = findNode(currentId());
    if (node) return node;
    return { id: "", label: "", base: "", official: true, custom: false };
  }

  /** 列表 + 每条的健康快照，UI 直接渲染这个。 */
  function list() {
    var selId = currentId();
    return allNodes().map(function (n) {
      var snap = probeCache[n.id] || null;
      return {
        id: n.id,
        label: n.label,
        base: n.base,
        endpoint: resolveBase(n.base),
        official: !!n.official,
        dev: !!n.dev,
        custom: !!n.custom,
        selected: n.id === selId,
        health: snap ? { ok: !!snap.ok, ms: snap.ms, at: snap.at, tested: true } : { tested: false }
      };
    });
  }

  function emit(reason) {
    var detail = { reason: reason || "", node: current() };
    for (var i = 0; i < listeners.length; i += 1) {
      try {
        listeners[i](detail);
      } catch (_) {}
    }
    try {
      if (global.document && typeof global.CustomEvent === "function") {
        global.document.dispatchEvent(new global.CustomEvent("karma:nodes-changed", { detail: detail }));
      }
    } catch (_) {}
  }

  function onChange(fn) {
    if (typeof fn === "function") listeners.push(fn);
    return function () {
      var i = listeners.indexOf(fn);
      if (i >= 0) listeners.splice(i, 1);
    };
  }

  /**
   * 切到某个节点：写 base + 写 id + 同步 window.KARMA_API_BASE，然后广播。
   * 老代码里 displayBase() 先读 localStorage、再读 window —— 两边都写才不会有歧义。
   */
  function select(id, opts) {
    var node = findNode(id);
    if (!node) return null;
    lsSet(LS_BASE, trimBase(node.base));
    lsSet(LS_NODE_ID, node.id);
    try {
      global.KARMA_API_BASE = trimBase(node.base);
    } catch (_) {}
    emit((opts && opts.reason) || "select");
    return node;
  }

  function addCustom(input) {
    var base = trimBase(input && input.base);
    if (!isValidBase(base) || base === "") {
      return { ok: false, error: "节点地址必须以 http:// 或 https:// 开头" };
    }
    var arr = readCustom();
    if (arr.length >= MAX_CUSTOM) {
      return { ok: false, error: "最多只能添加 " + MAX_CUSTOM + " 个自定义节点" };
    }
    var seen = allNodes();
    for (var i = 0; i < seen.length; i += 1) {
      if (normalizeForCompare(seen[i].base) === normalizeForCompare(base)) {
        return { ok: false, error: "这个地址已经在列表里了" };
      }
    }
    var node = {
      id: "custom:" + base.toLowerCase(),
      label: String((input && input.label) || "").trim() || base,
      base: base,
      custom: true
    };
    arr.push(node);
    writeCustom(arr);
    emit("add");
    return { ok: true, node: node };
  }

  function removeCustom(id) {
    // 历史/手填的那一条不在自定义表里：删它 = 把这份设置清掉，回到同源。
    var legacy = legacyNode();
    if (legacy && legacy.id === id) {
      lsDel(LS_BASE);
      lsDel(LS_NODE_ID);
      try {
        global.KARMA_API_BASE = "";
      } catch (_) {}
      select("same-origin", { reason: "remove" });
      return true;
    }
    var arr = readCustom();
    var kept = arr.filter(function (n) {
      return n.id !== id;
    });
    if (kept.length === arr.length) return false;
    writeCustom(kept);
    if (currentId() === id && kept.length) select(kept[0].id, { reason: "remove" });
    else emit("remove");
    return true;
  }

  function autofailOn() {
    return lsGet(LS_AUTOFAIL) === "1";
  }

  function setAutofail(on) {
    if (on) lsSet(LS_AUTOFAIL, "1");
    else lsDel(LS_AUTOFAIL);
    emit("autofail");
    return autofailOn();
  }

  /* -------------------------------------------------------------- 体检 */

  function nowMs() {
    try {
      return typeof performance !== "undefined" && performance.now ? performance.now() : Date.now();
    } catch (_) {
      return Date.now();
    }
  }

  function timeoutFetch(url, ms) {
    if (typeof global.fetch !== "function") {
      // 内部错误串一律用英文：它们只进 probe 的返回值，不进界面 ——
      // 这样「这两个文件里的中文字面量必须都能翻」这条规矩可以机械校验。
      return Promise.resolve({ ok: false, status: 0, error: "fetch unavailable" });
    }
    var ctrl = null;
    var opts = { cache: "no-store" };
    try {
      if (typeof global.AbortController === "function") {
        ctrl = new global.AbortController();
        opts.signal = ctrl.signal;
      }
    } catch (_) {}
    var timer = null;
    var guard = new Promise(function (resolve) {
      timer = setTimeout(function () {
        if (ctrl) {
          try {
            ctrl.abort();
          } catch (_) {}
        }
        resolve({ ok: false, status: 0, error: "timeout" });
      }, ms);
    });
    return Promise.race([
      global.fetch(url, opts).then(function (res) {
        return res;
      }, function (e) {
        return { ok: false, status: 0, error: String((e && e.message) || e) };
      }),
      guard
    ]).then(function (res) {
      if (timer) clearTimeout(timer);
      return res;
    });
  }

  /**
   * 探一个节点：GET /health，量往返耗时。
   * 返回 {ok, ms, version, status, error}。任何异常都当成「不可用」，不往外抛。
   */
  function probe(node, opts) {
    var target = typeof node === "string" ? findNode(node) : node;
    if (!target) return Promise.resolve({ ok: false, ms: 0, error: "unknown node" });
    var url = resolveBase(target.base) + HEALTH_PATH;
    var t0 = nowMs();
    var timeout = (opts && opts.timeoutMs) || PROBE_TIMEOUT_MS;
    return timeoutFetch(url, timeout).then(function (res) {
      var ms = Math.round(nowMs() - t0);
      if (res && res.error) {
        return rememberProbe(target, { ok: false, ms: ms, error: res.error, status: res.status || 0 });
      }
      var status = (res && res.status) || 0;
      var json = res && typeof res.json === "function" ? res.json() : Promise.resolve(null);
      return Promise.resolve(json)
        .catch(function () {
          return null;
        })
        .then(function (body) {
          var ok = !!res.ok && !!body && body.status === "ok";
          return rememberProbe(target, {
            ok: ok,
            ms: ms,
            status: status,
            version: (body && body.version) || "",
            error: ok ? "" : "HTTP " + status
          });
        });
    });
  }

  /** 探完就记住：顶栏胶囊上的延迟点要能直接用，不能只靠 probeAll 才有数。 */
  function rememberProbe(node, result) {
    if (node && node.id) {
      probeCache[node.id] = {
        ok: !!result.ok,
        ms: result.ms,
        at: Date.now(),
        version: result.version || "",
        error: result.error || "",
        // 和 list() 里的形状保持一致：界面按 tested 判断「还没测过」，
        // 少这个字段，胶囊上的延迟就会永远空着。
        tested: true
      };
    }
    return result;
  }

  function probeAll(opts) {
    var nodes = allNodes();
    return Promise.all(
      nodes.map(function (n) {
        return probe(n, opts).then(function (r) {
          return { id: n.id, label: n.label, base: resolveBase(n.base), ok: r.ok, ms: r.ms, error: r.error || "" };
        });
      })
    ).then(function (rows) {
      emit("probe");
      return rows;
    });
  }

  function healthOf(id) {
    return probeCache[id] || null;
  }

  /* ------------------------------------------------------------ 容灾 */

  /**
   * 请求失败时喊一声。开着自动切换、且失败的就是当前节点时，
   * 按顺序探其它节点，第一个能用的就切过去。
   * 有最小间隔（15s）和重入锁：不会因为并发请求把节点来回甩。
   */
  function reportFailure(failedBase) {
    if (!autofailOn()) return Promise.resolve(null);
    var cur = current();
    if (normalizeForCompare(failedBase) !== normalizeForCompare(resolveBase(cur.base))) {
      return Promise.resolve(null);
    }
    var t = Date.now();
    if (failingOver || t - lastFailoverAt < FAILOVER_MIN_GAP_MS) return Promise.resolve(null);
    failingOver = true;
    lastFailoverAt = t;
    var candidates = allNodes().filter(function (n) {
      return n.id !== cur.id;
    });
    var i = 0;
    function next() {
      if (i >= candidates.length) return Promise.resolve(null);
      var cand = candidates[i];
      i += 1;
      return probe(cand, { timeoutMs: FAILOVER_TIMEOUT_MS }).then(function (r) {
        if (r.ok) {
          // probe() 自己会写缓存，这里不用再抄一遍。
          select(cand.id, { reason: "failover" });
          return cand;
        }
        return next();
      });
    }
    return next().then(
      function (hit) {
        failingOver = false;
        return hit;
      },
      function () {
        failingOver = false;
        return null;
      }
    );
  }

  /** 首次加载：老用户只有 base 没有 node id，这里补一次，之后 UI 才认得出来。 */
  function bootstrap() {
    var id = lsGet(LS_NODE_ID);
    if (id && findNode(id)) return current();
    var node = findNode(currentId());
    if (node) lsSet(LS_NODE_ID, node.id);
    return node;
  }

  var api = {
    BUILTIN: BUILTIN,
    bootstrap: bootstrap,
    list: list,
    current: current,
    currentId: currentId,
    effectiveBase: function () {
      return resolveBase(current().base);
    },
    select: select,
    addCustom: addCustom,
    removeCustom: removeCustom,
    autofailOn: autofailOn,
    setAutofail: setAutofail,
    probe: probe,
    probeAll: probeAll,
    healthOf: healthOf,
    reportFailure: reportFailure,
    onChange: onChange,
    /* 给测试和排障用的纯函数 */
    _pure: {
      isLocalPage: isLocalPage,
      trimBase: trimBase,
      isValidBase: isValidBase,
      resolveBase: resolveBase,
      normalizeForCompare: normalizeForCompare
    }
  };

  global.KarmaNodes = api;
})(typeof window !== "undefined" ? window : globalThis);
