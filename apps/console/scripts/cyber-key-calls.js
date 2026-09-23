/**
 * 钥匙「最近调用」面板 —— 一份实现，两处挂载。
 *
 * 额度汇总只回答「今天花了多少」，回答不了「哪一次被拒了、为什么被拒」；而后者才是
 * 主人判断「这个 agent 是不是在乱试」的唯一线索。所以这个面板要能在两处展开：
 *   1. 设置页「已授权 · 一键取消绑定」里每把钥匙（宿主 cyber-unbind-keys.js）；
 *   2. 「交给 Agent」交付包里那张密钥清单（宿主 cyber-handoff.js）—— 主人是在那儿
 *      第一次看见自己铸出来的钥匙，也应该在那儿就能看它最近做了什么。
 *
 * 为什么单独成一个模块：两处各拼一套的话，改一处就静默失配 —— 文案、条数上限、
 * 展开状态必须只有一份。取数走会话鉴权（POST /runtime/key-calls），不打钱包签名弹窗：
 * 看一眼记录不该惊动钱包。谁名下的钥匙谁才查得到，别人的一律 404（由服务端把关）。
 */
(function (global) {
  var CALL_LIMIT = 20;

  var state = {
    open: "",
    // 当前展开的那把钥匙是哪个宿主打开的（两处宿主的清单各不相同，
    // 用别人的清单去 prune 会把这边刚展开的面板误关）。
    openHost: "",
    loading: "",
    err: "",
    calls: {},
  };

  /** 宿主卡片：展开状态一变就重画哪一块（各自渲染自己的卡片）。 */
  var hosts = [];
  var attached = false;

  function api() { return global.karmaRuntimeApi; }
  function identity() { return String(global.KARMA_IDENTITY_ID || "").trim(); }
  function i18n() { return global.CYBER_I18N; }
  function T(zh) {
    var t = i18n();
    return t && t.T ? t.T(zh) : zh;
  }
  function Tf(zh) {
    var t = i18n();
    if (t && t.Tf) {
      var args = [zh];
      for (var i = 1; i < arguments.length; i += 1) args.push(arguments[i]);
      return t.Tf.apply(t, args);
    }
    var out = T(zh);
    for (var k = 1; k < arguments.length; k += 1) {
      out = out.split("{" + (k - 1) + "}").join(arguments[k] == null ? "" : String(arguments[k]));
    }
    return out;
  }
  function esc(v) {
    return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function when(iso) {
    return String(iso || "").replace("T", " ").slice(0, 19);
  }

  function register(hostId, rerender) {
    var id = String(hostId || "");
    if (!id || typeof rerender !== "function") return;
    for (var i = 0; i < hosts.length; i += 1) {
      if (hosts[i].id === id) {
        hosts[i].rerender = rerender;
        return;
      }
    }
    hosts.push({ id: id, rerender: rerender });
  }

  function rerenderAll() {
    for (var i = 0; i < hosts.length; i += 1) {
      try {
        hosts[i].rerender();
      } catch (_) {}
    }
  }

  function isOpen(keyId) {
    return !!keyId && state.open === keyId;
  }

  /** 这把钥匙没了（取消绑定 / 停用 / 撤销）：展开状态和缓存一并收掉。 */
  function forget(keyId) {
    delete state.calls[keyId];
    if (state.open === keyId) {
      state.open = "";
      state.openHost = "";
      state.err = "";
    }
  }

  /** 钥匙列表刷新后调用：已经不存在的钥匙别留着展开状态，免得留一张空壳。
   * 只能用自己那份清单去判：交付包里展开的钥匙本来就不在「已绑定钥匙」那份清单里。
   */
  function prune(keyIds, hostId) {
    if (!state.open) return;
    var host = String(hostId || "");
    if (state.openHost && host && state.openHost !== host) return;
    var list = keyIds || [];
    for (var i = 0; i < list.length; i += 1) {
      if (list[i] === state.open) return;
    }
    state.open = "";
    state.openHost = "";
    state.err = "";
  }

  /** 点「刷新」时用：缓存全丢，还开着的那把重新取一次。 */
  function reset() {
    state.calls = {};
    state.err = "";
  }

  function outcomeLabel(outcome, status) {
    if (outcome === "ok") return T("成功");
    if (outcome === "rejected") return Tf("被拒（HTTP {0}）", status);
    return Tf("异常（HTTP {0}）", status == null ? "—" : status);
  }

  function callLine(c) {
    var amount = c && c.amount == null ? "" : c.amount;
    var spare = amount === "" ? "" : Tf(" · 金额 {0} USDC", amount);
    var detail = c && c.detail ? Tf(" · {0}", c.detail) : "";
    var line = Tf(
      "动作 {0} · 结果 {1}{2}{3} · 时间 {4}",
      (c && c.endpoint) || "—",
      outcomeLabel(c && c.outcome, c && c.http_status),
      spare,
      detail,
      when(c && c.created_at) || "—"
    );
    return esc(line);
  }

  /** 没展开就返回空串 —— 宿主卡片直接把它拼进自己的 HTML 就行。 */
  function panelHtml(keyId) {
    if (!isOpen(keyId)) return "";
    if (state.loading === keyId) {
      return '<p class="ag-hint">' + esc(T("正在读取调用记录…")) + "</p>";
    }
    if (state.err) return '<p class="err">' + esc(state.err) + "</p>";
    var list = state.calls[keyId];
    if (!list) return "";
    if (!list.length) {
      return (
        '<p class="ag-hint">' +
        esc(T("还没有调用记录。agent 用这把钥匙发起动作后，这里会逐条留下痕迹。")) +
        "</p>"
      );
    }
    var out =
      '<div class="ag-snippet ag-key-calls" style="margin-top:8px">' +
      '<div class="ag-secret-label">' + esc(T("最近调用记录（最新在前）")) + "</div>" +
      '<ul style="margin:6px 0 0 0;padding-left:18px">';
    for (var i = 0; i < list.length; i += 1) out += "<li>" + callLine(list[i]) + "</li>";
    return out + "</ul></div>";
  }

  function buttonHtml(keyId, hostId) {
    var label = isOpen(keyId) ? T("收起最近调用") : T("查看最近调用");
    return (
      '<button type="button" class="btn" data-key-calls="' + esc(keyId) +
      '" data-key-calls-host="' + esc(hostId || "") + '">' +
      esc(label) +
      "</button>"
    );
  }

  async function toggle(keyId, hostId) {
    var id = String(keyId || "");
    if (!id) return;
    if (state.open === id) {
      state.open = "";
      state.openHost = "";
      state.err = "";
      rerenderAll();
      return;
    }
    state.open = id;
    state.openHost = String(hostId || "");
    state.err = "";
    if (Object.prototype.hasOwnProperty.call(state.calls, id)) {
      rerenderAll();
      return;
    }
    var a = api();
    if (!a || !a.runtimeKeyCalls) {
      state.err = "接口未加载，请刷新页面后再试。";
      rerenderAll();
      return;
    }
    state.loading = id;
    rerenderAll();
    try {
      var r = await a.runtimeKeyCalls({
        karma_identity_id: identity(),
        key_id: id,
        limit: CALL_LIMIT,
      });
      state.calls[id] = (r && r.calls) || [];
      state.err = "";
    } catch (e) {
      state.err = "读取调用记录失败：" + ((e && e.message) || e);
    }
    state.loading = "";
    rerenderAll();
  }

  /**
   * 点击委托 + 语言切换，都只装一次（两处宿主共用）。
   *
   * 切语言时必须自己重画：面板里那一行是拼出来的（动作 + 结果 + 金额 +
   * 时间），DOM 翻译引擎只认得整句，认不出带变量的句子 —— 不重画就会
   * 把上一种语言的行留在那里（切到英文还是中文行），正好犯用户最在意的那一条。
   */
  function attach() {
    if (attached) return;
    attached = true;
    document.addEventListener("click", function (ev) {
      var t = ev.target;
      if (!t || !t.closest) return;
      var btn = t.closest("[data-key-calls]");
      if (!btn) return;
      ev.preventDefault();
      toggle(btn.getAttribute("data-key-calls"), btn.getAttribute("data-key-calls-host"));
    });
    // 切语言：数据不重拉（还是刚才那几条），只把文字重画成新语言。
    // 语言包是懒加载的：真机上见过「事件到了、包还没到」—— 拼出来的那一行就会留上
    // 一种语言。所以再挂一次「包就绪后重画」（就绪了会立刻回调，拉不到也会回调）。
    document.addEventListener("karma-lang-changed", function (ev) {
      var t = i18n();
      var lang = (ev && ev.detail && ev.detail.lang) || (t && t.getLang ? t.getLang() : "");
      rerenderAll();
      if (t && t.ensureExt && lang) {
        try {
          t.ensureExt(lang, function () {
            rerenderAll();
          });
        } catch (_) {}
      }
    });
  }

  attach();

  global.KarmaKeyCalls = {
    CALL_LIMIT: CALL_LIMIT,
    register: register,
    isOpen: isOpen,
    forget: forget,
    prune: prune,
    reset: reset,
    toggle: toggle,
    buttonHtml: buttonHtml,
    panelHtml: panelHtml,
    attach: attach,
  };
})(window);
