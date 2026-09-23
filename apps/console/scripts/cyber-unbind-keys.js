/**
 * 已授权 · 一键取消绑定（操作台侧）。
 *
 * 「接入确认」管的是 agent 能不能接进来；这个模块管的是接进来之后主人反悔。
 * 钥匙一旦绑上 agent 公钥，它就一直在代表主人花钱，所以设置页必须有一个随时能按的
 * 出口：点「取消绑定」+ 钱包签名，服务端立刻把公钥摘掉，钥匙回到「未激活」。
 *
 * 为什么不顺手退回托管（service）状态：那等于把钥匙变回不记名令牌 —— 谁抄到谁能花，
 * 而用户点这个按钮的意思恰恰是「别再让那个 agent 代表我花钱」。摘掉公钥之后这把钥匙
 * 谁都花不了；agent 想再用得重新申请一次接入，主人再输一次匹配码。
 *
 * 取数走会话鉴权（POST /runtime/list-bound-keys），不打钱包签名弹窗 —— 列一下有哪些
 * 钥匙不该惊动钱包。真正的签名只发生在点「取消绑定」的时候，消息由 cyber-handoff.js
 * 出口（KarmaHandoff.buildUnbindKeyMsg），这里绝不自己再拼一套，否则两边改一处就静默失配。
 *
 * 卡片里还有两件事：
 *   1. 展开某把钥匙看「最近调用」—— 面板本身在 cyber-key-calls.js（交付包那张密钥清单
 *      用同一份实现），这里只负责把按钮和面板摆到每把钥匙下面。
 *   2. 站内提醒（POST /runtime/list-notices）—— 取消绑定是不可逆动作，闪一行提示关掉就
 *      没了；落库留痕 + 要点过才消，才担得起「不记名令牌的出口」这个位置。
 */
(function (global) {
  var POLL_MS = 60000;

  var state = {
    keys: [],
    loading: false,
    note: "",
    err: "",
    authed: false,
    busy: "",
    notices: [],
    unread: 0,
    ackBusy: false,
  };

  function api() { return global.karmaRuntimeApi; }
  function signer() { return global.KarmaHandoff; }
  /** 「最近调用」面板：和交付包的密钥清单共用一份实现（cyber-key-calls.js）。 */
  function calls() { return global.KarmaKeyCalls; }
  function identity() { return String(global.KARMA_IDENTITY_ID || "").trim(); }
  function host() { return document.getElementById("bound-keys"); }
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
  function button(label, attr, cls) {
    return (
      '<button type="button" class="btn' + (cls ? " " + cls : "") + '" ' + attr + ">" +
      esc(label) +
      "</button>"
    );
  }
  function stamp(iso) {
    return String(iso || "").slice(0, 10);
  }
  function permsText(p) {
    if (!p) return "";
    if (Array.isArray(p)) return p.join(", ");
    return String(p);
  }
  function num(v) {
    return v == null || v === "" ? "—" : String(v);
  }
  function who(payload) {
    var p = payload || {};
    return String(p.agent_name || p.agent_id || p.key_id || "—");
  }

  /* ---- 站内提醒 ---- */

  function noticeText(n) {
    var kind = (n && n.kind) || "";
    if (kind === "key_unbound") {
      return Tf("取消绑定已完成：{0} 不能再代表你花钱，这把钥匙谁都花不了。", who(n && n.payload));
    }
    if (kind === "key_bound") {
      return Tf("接入已确认：{0} 现在可以在额度与权限内代表你花钱。", who(n && n.payload));
    }
    return Tf("钥匙事件：{0}", kind || "—");
  }

  function noticesHtml() {
    if (!state.notices.length) return "";
    var items = "";
    for (var i = 0; i < state.notices.length; i += 1) {
      var n = state.notices[i];
      items += "<li>" + esc(noticeText(n)) + (n && n.read ? "" : " · " + esc(T("未读"))) + "</li>";
    }
    var unreadLabel = state.unread
      ? Tf("站内提醒（{0} 条未读）", state.unread)
      : T("站内提醒");
    return (
      '<div class="ag-snippet" style="margin-top:10px;border-left:3px solid #7c5cff">' +
      '<div class="ag-secret-label">' + esc(unreadLabel) + "</div>" +
      '<ul style="margin:6px 0 0 0;padding-left:18px">' + items + "</ul>" +
      '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px">' +
      button(state.ackBusy ? T("正在标记…") : T("知道了（不再提醒）"), "data-ack-notices") +
      "</div></div>"
    );
  }

  function rowHtml(k) {
    var keyId = esc(k.key_id);
    var name = esc(k.agent_name || k.agent_id || "—");
    var perms = permsText(k.permissions);
    var panel = calls();
    return (
      '<div class="ag-snippet" style="margin-top:10px">' +
      '<div class="ag-secret-label">正在代表你花钱的 agent：' + name + "</div>" +
      '<p class="ag-hint">公钥指纹：' + esc(k.agent_fingerprint || "—") +
      " · 单笔上限 " + esc(num(k.single_limit)) + " USDC" +
      " · 每日上限 " + esc(num(k.daily_limit)) + " USDC" +
      " · 到期 " + esc(stamp(k.expire_time) || "—") + "</p>" +
      (perms ? '<p class="ag-hint">权限：' + esc(perms) + "</p>" : "") +
      '<p class="ag-hint">钥匙 ID：' + keyId + "</p>" +
      '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px">' +
      (panel ? panel.buttonHtml(k.key_id) : "") +
      button("取消绑定（要钱包签名）", 'data-unbind-key="' + keyId + '"') +
      "</div>" +
      (panel ? panel.panelHtml(k.key_id) : "") +
      "</div>"
    );
  }

  function bodyHtml() {
    var head = noticesHtml();
    if (state.loading && !state.keys.length) {
      return head + '<p class="ag-hint">正在读取已绑定的钥匙…</p>';
    }
    if (!state.keys.length) {
      return (
        head +
        '<p class="ag-hint">暂时没有绑定 agent 的钥匙。agent 申请接入、你在「接入确认」输码确认之后，它才会出现在这里。</p>'
      );
    }
    var out =
      head +
      '<p class="ag-secret-label">已绑定 agent、正在代表你花钱的钥匙：' + esc(state.keys.length) + " 把</p>";
    for (var i = 0; i < state.keys.length; i += 1) out += rowHtml(state.keys[i]);
    return out;
  }

  function noteHtml() {
    var out = "";
    if (state.busy) out += '<p class="ag-hint">等待钱包签名…</p>';
    if (state.note) out += '<p class="ag-hint">' + esc(state.note) + "</p>";
    if (state.err) out += '<p class="err">' + esc(state.err) + "</p>";
    return out;
  }

  /** 侧栏「设置」挂红点：取消绑定这类事不点开页面也要看得见。 */
  function paintNoticeDot(unread) {
    var nav = document.querySelector('.nav-main[data-page="settings"]');
    if (!nav) return;
    nav.classList.toggle("has-notice", unread > 0);
    if (unread > 0) nav.setAttribute("title", T("有未读的钥匙提醒"));
    else nav.removeAttribute("title");
  }

  function render() {
    var h = host();
    if (!h) return;
    if (!state.authed && !state.keys.length && !state.loading) {
      h.innerHTML = '<p class="ag-hint">连接钱包后，这里会显示已经绑定 agent 的钥匙。</p>' + noteHtml();
    } else {
      h.innerHTML = bodyHtml() + noteHtml();
    }
    var card = document.getElementById("ag-bound-keys");
    if (card) card.classList.toggle("attention", state.unread > 0);
    paintNoticeDot(state.unread);
  }

  /* ---- 取数（会话鉴权） ---- */

  async function loadNotices() {
    var a = api();
    if (!a || !a.runtimeListNotices) return;
    try {
      var n = await a.runtimeListNotices({ karma_identity_id: identity(), limit: 20 });
      state.notices = (n && n.notices) || [];
      state.unread = (n && n.unread) || 0;
    } catch (e) {
      var status = e && e.status;
      if (status === 401 || status === 403) {
        state.notices = [];
        state.unread = 0;
      }
    }
  }

  async function poll() {
    var a = api();
    if (!a || !a.runtimeListBoundKeys) return;
    if (!identity() && !global.KARMA_ACCESS_TOKEN) {
      state.keys = [];
      state.notices = [];
      state.unread = 0;
      state.authed = false;
      state.loading = false;
      render();
      return;
    }
    state.loading = true;
    if (state.keys.length) render();
    try {
      var r = await a.runtimeListBoundKeys({ karma_identity_id: identity() });
      state.keys = (r && r.keys) || [];
      state.authed = true;
      state.err = "";
      await loadNotices();
    } catch (e) {
      var status = e && e.status;
      if (status === 401 || status === 403) {
        // 还没连钱包 / 会话过期：这不是错误，是「先连接钱包」。
        state.keys = [];
        state.notices = [];
        state.unread = 0;
        state.authed = false;
        state.err = "";
      } else {
        state.err = "读取已绑定的钥匙失败：" + ((e && e.message) || e);
      }
    }
    state.loading = false;
    // 展开中的钥匙如果被取消绑定 / 停用了，记录一并收起来，别留着一张空壳。
    var c = calls();
    if (c && c.prune) {
      c.prune(
        state.keys.map(function (k) {
          return k.key_id;
        })
      );
    }
    render();
  }

  async function ackNotices() {
    var a = api();
    if (!a || !a.runtimeAckNotice || state.ackBusy) return;
    state.ackBusy = true;
    render();
    try {
      await a.runtimeAckNotice({ karma_identity_id: identity() });
      state.notices = [];
      state.unread = 0;
    } catch (e) {
      state.err = "标记已读失败：" + ((e && e.message) || e);
    }
    state.ackBusy = false;
    render();
  }

  /* ---- 动作：取消绑定 ---- */

  async function unbind(keyId) {
    var s = signer();
    if (!s || !s.buildUnbindKeyMsg || !s.walletProvider) {
      state.err = "签名模块未加载，请刷新页面后再试。";
      render();
      return;
    }
    if (!global.confirm(T("取消绑定后，这个 agent 立刻不能再代表你花钱（这把钥匙谁都花不了）。要用就让 agent 重新申请一次接入。确定吗？"))) {
      return;
    }
    var prov = await s.walletProvider();
    if (!prov) {
      state.err = "未检测到可用钱包，请先用右上角「连接钱包」认证";
      render();
      return;
    }
    state.err = "";
    state.note = "";
    state.busy = keyId;
    render();
    try {
      var accounts = await prov.request({ method: "eth_requestAccounts" });
      var wallet = accounts[0];
      var nonce = "console-" + Date.now().toString(36);
      var msg = s.buildUnbindKeyMsg({
        key_id: keyId,
        karma_identity_id: identity(),
        wallet_address: wallet,
        client_nonce: nonce,
      });
      var sig = await prov.request({ method: "personal_sign", params: [msg, wallet] });
      await api().runtimeUnbindKey({
        key_id: keyId,
        karma_identity_id: identity(),
        wallet_address: wallet,
        wallet_signature: sig,
        client_nonce: nonce,
      });
      state.note = "已取消绑定：这把钥匙回到「未激活」，agent 想再花钱得重新申请一次接入。";
      var cc = calls();
      if (cc && cc.forget) cc.forget(keyId);
    } catch (e) {
      state.note = "";
      state.err = "取消绑定失败：" + ((e && e.message) || e);
    }
    state.busy = "";
    await poll();
  }

  /* ---- 接线 ---- */

  function init() {
    document.addEventListener("click", function (ev) {
      var t = ev.target;
      if (!t || !t.closest) return;
      // 「最近调用」的点击由 cyber-key-calls.js 的文档级委托接手：两处宿主共用一份。
      if (t.closest("[data-ack-notices]")) {
        ev.preventDefault();
        ackNotices();
        return;
      }
      var btn = t.closest("[data-unbind-key]");
      if (btn) {
        ev.preventDefault();
        unbind(btn.getAttribute("data-unbind-key"));
        return;
      }
      if (t.closest("#btn-bound-refresh")) {
        ev.preventDefault();
        var c = calls();
        if (c && c.reset) c.reset();
        poll();
      }
    });
    ["karma-wallet-connected", "karma-session-restored", "karma-page-shown", "karma-lang-changed"].forEach(
      function (name) {
        document.addEventListener(name, function () { poll(); });
      }
    );
    render();
    poll();
    try {
      global.setInterval(poll, POLL_MS);
    } catch (_) {}
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();

  global.KarmaUnbindKeys = {
    refresh: poll,
    render: render,
    // 老名字留着：面板现在归 cyber-key-calls.js，这里转过去。
    toggleCalls: function (keyId) {
      var c = calls();
      return c && c.toggle ? c.toggle(keyId) : undefined;
    },
  };

  // 展开状态一变就重画这张卡片（面板由 cyber-key-calls.js 管，这里只管画）。
  if (calls() && calls().register) calls().register("ag-bound-keys", render);
})(window);
