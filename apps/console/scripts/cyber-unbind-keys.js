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
  };

  function api() { return global.karmaRuntimeApi; }
  function signer() { return global.KarmaHandoff; }
  function identity() { return String(global.KARMA_IDENTITY_ID || "").trim(); }
  function host() { return document.getElementById("bound-keys"); }
  function T(zh) {
    var i18n = global.CYBER_I18N;
    return i18n && i18n.T ? i18n.T(zh) : zh;
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

  function rowHtml(k) {
    var keyId = esc(k.key_id);
    var name = esc(k.agent_name || k.agent_id || "—");
    var perms = permsText(k.permissions);
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
      button("取消绑定（要钱包签名）", 'data-unbind-key="' + keyId + '"') +
      "</div>" +
      "</div>"
    );
  }

  function bodyHtml() {
    if (state.loading && !state.keys.length) {
      return '<p class="ag-hint">正在读取已绑定的钥匙…</p>';
    }
    if (!state.keys.length) {
      return (
        '<p class="ag-hint">暂时没有绑定 agent 的钥匙。agent 申请接入、你在「接入确认」输码确认之后，它才会出现在这里。</p>'
      );
    }
    var out =
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

  function render() {
    var h = host();
    if (!h) return;
    if (!state.authed && !state.keys.length && !state.loading) {
      h.innerHTML = '<p class="ag-hint">连接钱包后，这里会显示已经绑定 agent 的钥匙。</p>' + noteHtml();
    } else {
      h.innerHTML = bodyHtml() + noteHtml();
    }
  }

  /* ---- 取数（会话鉴权） ---- */

  async function poll() {
    var a = api();
    if (!a || !a.runtimeListBoundKeys) return;
    if (!identity() && !global.KARMA_ACCESS_TOKEN) {
      state.keys = [];
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
    } catch (e) {
      var status = e && e.status;
      if (status === 401 || status === 403) {
        // 还没连钱包 / 会话过期：这不是错误，是「先连接钱包」。
        state.keys = [];
        state.authed = false;
        state.err = "";
      } else {
        state.err = "读取已绑定的钥匙失败：" + ((e && e.message) || e);
      }
    }
    state.loading = false;
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
      var btn = t.closest("[data-unbind-key]");
      if (btn) {
        ev.preventDefault();
        unbind(btn.getAttribute("data-unbind-key"));
        return;
      }
      if (t.closest("#btn-bound-refresh")) {
        ev.preventDefault();
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

  global.KarmaUnbindKeys = { refresh: poll, render: render };
})(window);
