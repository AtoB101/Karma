/**
 * 接入确认 · 操作台侧（匹配码激活的入口）。
 *
 * agent 首次接入 Runtime Key 时申请绑定公钥，拿到一串 8 位匹配码；这串码只在 agent
 * 手里 —— 服务端只存 HMAC。所以「绑定生效」这件事只能由主人在操作台完成：输码 + 钱包签名。
 *
 * 这一模块解决的是「主人去哪儿看见它」：
 *   1. 「设置」页常驻一张「接入确认」卡片，列出所有待确认请求，就地输码；
 *   2. 侧栏「设置」挂红点，切到别的页也不会漏；
 *   3. 新请求出现时弹一次提示框，一键跳到输码框。
 *
 * 取数走会话鉴权（POST /runtime/list-pending-binds），不打钱包签名弹窗 ——
 * 看一眼提示不该惊动钱包。真正的签名只发生在点「确认绑定 / 拒绝这次接入」的时候。
 *
 * 签名消息与 cyber-handoff.js 共用一份实现（服务端按同一格式重建）：这里只调
 * KarmaHandoff，绝不自己再拼一套，否则两边改一处就静默失配。
 */
(function (global) {
  var POLL_MS = 60000;

  var NOTIFIED_KEY = "karma_bind_notified";

  var state = {
    requests: [],
    loading: false,
    note: "",
    err: "",
    authed: false,
    busy: "",
    notified: readNotified(),
  };

  /**
   * 已经提示过的 key 记在 sessionStorage 里：弹窗只负责「把人叫过来一次」，
   * 常驻提醒交给卡片和侧栏红点 —— 每次开页面都弹就是噪音了。
   */
  function readNotified() {
    try {
      var raw = global.sessionStorage.getItem(NOTIFIED_KEY);
      var list = raw ? JSON.parse(raw) : [];
      var out = {};
      for (var i = 0; i < (list || []).length; i += 1) out[list[i]] = true;
      return out;
    } catch (_) { return {}; }
  }

  function saveNotified() {
    try {
      global.sessionStorage.setItem(NOTIFIED_KEY, JSON.stringify(Object.keys(state.notified)));
    } catch (_) {}
  }

  function api() { return global.karmaRuntimeApi; }
  function signer() { return global.KarmaHandoff; }
  function identity() { return String(global.KARMA_IDENTITY_ID || "").trim(); }
  function host() { return document.getElementById("bind-requests"); }
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
    return String(iso || "").slice(0, 16).replace("T", " ");
  }

  function live() {
    return (state.requests || []).filter(function (r) { return !r.expired; });
  }
  function stale() {
    return (state.requests || []).filter(function (r) { return !!r.expired; });
  }
  function inputFor(keyId) {
    var nodes = document.querySelectorAll("[data-bind-code]");
    for (var i = 0; i < nodes.length; i += 1) {
      if (nodes[i].getAttribute("data-bind-code") === keyId) return nodes[i];
    }
    return null;
  }

  /* ---- 渲染：设置页那张卡片 ---- */

  function rowHtml(r) {
    var keyId = esc(r.key_id);
    var name = esc(r.agent_name || r.agent_id || "—");
    return (
      '<div class="ag-snippet" style="margin-top:10px">' +
      '<div class="ag-secret-label">申请接入的 agent：' + name + "</div>" +
      '<p class="ag-hint">agent 公钥指纹：' + esc(r.agent_fingerprint || "—") +
      " · 匹配码有效至 " + esc(stamp(r.expires_at)) +
      " · 还能试 " + esc(r.attempts_left == null ? "—" : r.attempts_left) + " 次</p>" +
      '<input type="text" inputmode="latin" autocomplete="off" spellcheck="false" maxlength="9"' +
      ' placeholder="输入 agent 显示的匹配码" data-bind-code="' + keyId + '" value="" />' +
      '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px">' +
      button("确认绑定（要钱包签名）", 'data-bind-confirm="' + keyId + '"', "primary") +
      button("拒绝这次接入", 'data-bind-reject="' + keyId + '"') +
      "</div>" +
      "</div>"
    );
  }

  function listHtml() {
    var rows = live();
    var out = '<p class="ag-secret-label">有 ' + esc(rows.length) + " 个 agent 正在申请接入这把密钥（还没生效）</p>";
    for (var i = 0; i < rows.length; i += 1) out += rowHtml(rows[i]);
    var old = stale();
    if (old.length) {
      out +=
        '<p class="ag-hint" style="margin-top:10px">有 ' + esc(old.length) +
        " 个接入申请已经过期（匹配码 3 分钟有效）：让 agent 重新申请一次，会把新的匹配码给你。</p>";
    }
    return out;
  }

  function bodyHtml() {
    if (state.loading && !state.requests.length) {
      return '<p class="ag-hint">正在读取待确认请求…</p>';
    }
    if (!live().length) {
      var empty = '<p class="ag-hint">暂无待确认的接入请求。agent 申请接入后会出现在这里。</p>';
      var old = stale();
      if (old.length) {
        empty +=
          '<p class="ag-hint">有 ' + esc(old.length) +
          " 个接入申请已经过期（匹配码 3 分钟有效）：让 agent 重新申请一次，会把新的匹配码给你。</p>";
      }
      return empty;
    }
    return listHtml();
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
    if (!state.authed && !state.requests.length && !state.loading) {
      h.innerHTML = '<p class="ag-hint">连接钱包后，这里会显示待确认的接入请求。</p>' + noteHtml();
    } else {
      h.innerHTML = bodyHtml() + noteHtml();
    }
    var card = document.getElementById("ag-bind-requests");
    if (card) card.classList.toggle("attention", live().length > 0);
    paintNavDot(live().length);
  }

  /** 侧栏「设置」挂红点：主人不在设置页时也要看得见。 */
  function paintNavDot(count) {
    var nav = document.querySelector('.nav-main[data-page="settings"]');
    if (!nav) return;
    nav.classList.toggle("has-pending", count > 0);
    if (count > 0) nav.setAttribute("title", T("有待确认的接入请求"));
    else nav.removeAttribute("title");
  }

  /* ---- 弹窗：新请求出现时提示一次 ---- */

  function modal() { return document.getElementById("bind-modal"); }

  function ensureModal() {
    if (modal()) return;
    var wrap = document.createElement("div");
    wrap.id = "bind-modal";
    wrap.className = "bind-modal";
    wrap.hidden = true;
    wrap.innerHTML =
      '<div class="bind-modal-box" role="dialog" aria-modal="true">' +
      "<h4>有 agent 在申请接入</h4>" +
      "<p>它拿到了一串 8 位匹配码。你在操作台输入并签名确认之后，这个 agent 才能用这把密钥；确认之前，它花钱的请求一律被拒。</p>" +
      '<p class="ag-hint" id="bind-modal-meta"></p>' +
      '<div class="bind-modal-actions">' +
      button("去输入匹配码", 'id="bind-modal-go"', "primary") +
      button("稍后处理", 'id="bind-modal-later"') +
      "</div>" +
      "</div>";
    document.body.appendChild(wrap);
  }

  function announce() {
    var rows = live();
    if (!rows.length) return;
    var fresh = rows.filter(function (r) { return !state.notified[r.key_id]; });
    if (!fresh.length) return;
    for (var i = 0; i < rows.length; i += 1) state.notified[rows[i].key_id] = true;
    saveNotified();
    ensureModal();
    var box = modal();
    var meta = document.getElementById("bind-modal-meta");
    if (meta) {
      var first = fresh[0];
      meta.textContent = "申请接入的 agent：" + (first.agent_name || first.agent_id || "—");
    }
    if (box) box.hidden = false;
  }

  function closeModal() {
    var box = modal();
    if (box) box.hidden = true;
  }

  function gotoCode() {
    closeModal();
    if (global.cyberSwitchPage) {
      try { global.cyberSwitchPage("settings"); } catch (_) {}
    }
    var card = document.getElementById("ag-bind-requests");
    if (card && card.scrollIntoView) card.scrollIntoView({ behavior: "smooth", block: "center" });
    var rows = live();
    var input = rows.length ? inputFor(rows[0].key_id) : null;
    if (input && input.focus) input.focus();
  }

  /* ---- 取数 ---- */

  async function poll() {
    var a = api();
    if (!a || !a.runtimeListPendingBinds) return;
    if (!identity() && !global.KARMA_ACCESS_TOKEN) {
      state.requests = [];
      state.authed = false;
      state.loading = false;
      render();
      return;
    }
    state.loading = true;
    if (state.requests.length) render();
    try {
      var r = await a.runtimeListPendingBinds({ karma_identity_id: identity() });
      state.requests = (r && r.requests) || [];
      state.authed = true;
      state.err = "";
    } catch (e) {
      var status = e && e.status;
      if (status === 401 || status === 403) {
        // 还没连钱包 / 会话过期：这不是错误，是「先连接钱包」。
        state.requests = [];
        state.authed = false;
        state.err = "";
      } else {
        state.err = "读取待确认请求失败：" + ((e && e.message) || e);
      }
    }
    state.loading = false;
    render();
    announce();
  }

  /* ---- 动作：输码确认 / 拒绝 ---- */

  async function confirmBind(keyId) {
    var s = signer();
    if (!s || !s.buildConfirmBindMsg || !s.walletProvider) {
      state.err = "签名模块未加载，请刷新页面后再试。";
      render();
      return;
    }
    var input = inputFor(keyId);
    var code = s.normalizeCode(input ? input.value : "");
    if (!/^[0-9A-Z]{4}-[0-9A-Z]{4}$/.test(code)) {
      state.err = "匹配码是 8 位（形如 XXXX-XXXX），请照 agent 显示的原样抄一遍";
      render();
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
      var msg = s.buildConfirmBindMsg({
        key_id: keyId,
        karma_identity_id: identity(),
        wallet_address: wallet,
        activation_code: code,
        client_nonce: nonce,
      });
      var sig = await prov.request({ method: "personal_sign", params: [msg, wallet] });
      await api().runtimeConfirmBindKey({
        key_id: keyId,
        karma_identity_id: identity(),
        wallet_address: wallet,
        wallet_signature: sig,
        activation_code: code,
        client_nonce: nonce,
      });
      state.note = "已确认绑定，这个 agent 之后每个请求都要私钥签名。";
    } catch (e) {
      state.note = "";
      state.err = "确认失败：" + ((e && e.message) || e);
    }
    state.busy = "";
    await poll();
  }

  async function rejectBind(keyId) {
    var s = signer();
    if (!s || !s.buildRejectBindMsg || !s.walletProvider) {
      state.err = "签名模块未加载，请刷新页面后再试。";
      render();
      return;
    }
    if (!global.confirm(T("拒绝这次接入？这个 agent 拿到的匹配码会作废，密钥本身不受影响。"))) return;
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
      var msg = s.buildRejectBindMsg({
        key_id: keyId,
        karma_identity_id: identity(),
        wallet_address: wallet,
        client_nonce: nonce,
      });
      var sig = await prov.request({ method: "personal_sign", params: [msg, wallet] });
      await api().runtimeRejectBindKey({
        key_id: keyId,
        karma_identity_id: identity(),
        wallet_address: wallet,
        wallet_signature: sig,
        client_nonce: nonce,
      });
      state.note = "已拒绝这次接入。要重新接入，让 agent 再申请一次。";
    } catch (e) {
      state.note = "";
      state.err = "拒绝失败：" + ((e && e.message) || e);
    }
    state.busy = "";
    await poll();
  }

  /* ---- 接线 ---- */

  function init() {
    ensureModal();
    document.addEventListener("click", function (ev) {
      var t = ev.target;
      if (!t || !t.closest) return;
      var confirmBtn = t.closest("[data-bind-confirm]");
      if (confirmBtn) {
        ev.preventDefault();
        confirmBind(confirmBtn.getAttribute("data-bind-confirm"));
        return;
      }
      var rejectBtn = t.closest("[data-bind-reject]");
      if (rejectBtn) {
        ev.preventDefault();
        rejectBind(rejectBtn.getAttribute("data-bind-reject"));
        return;
      }
      if (t.closest("#btn-bind-refresh")) {
        ev.preventDefault();
        poll();
        return;
      }
      if (t.closest("#bind-modal-go")) { ev.preventDefault(); gotoCode(); return; }
      if (t.closest("#bind-modal-later")) { ev.preventDefault(); closeModal(); return; }
      // 只有点遮罩本身才关；点弹窗正文里的字不该把它关掉。
      if (t === modal()) closeModal();
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

  global.KarmaBindRequests = { refresh: poll, render: render };
})(window);
