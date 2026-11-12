/**
 * 操作台 · 安全验证（2FA / TOTP）
 * ================================
 *
 * 为什么不记名的钥匙要再加一道验证码：绑在 agent 上的运行时密钥、钱包会话，都是
 * **谁拿到谁能使**。用户按「授权额度」的那一刻给出去的是实打实的支配权，
 * 「取消授权」更是不可逆动作。所以这两类动作在钱包签名之外，再过一道只有本人手机上
 * 那个验证器 App 才有的 6 位口令 —— 偷到钥匙的人到这里就停住了。
 *
 * 这个模块管三件事：
 *   1. **设置页那张卡**：绑定 / 换恢复码 / 解绑，密钥只在绑定的那一刻显示一次；
 *   2. **验证码弹窗**：任何要动钱的动作都从这里过（``Karma2FA.ask``）；
 *   3. **闸门**：``Karma2FA.guard(run, what)`` —— 先要码、再执行、码错了再问一次，
 *      让调用方（karma-public-api.js）一处收口，五个授权入口不用各自记得要码。
 *
 * 密钥从来不回吐给页面：``GET /v1/console/2fa`` 只说「绑没绑、还剩几张恢复码、锁没锁」。
 * 二维码要一个编码库，这里不做 —— 密钥与 otpauth 链接都能一键复制，认证器 App
 * 支持手动输入密钥 / 导入链接，够用且不引入依赖。
 */
(function (global) {
  "use strict";

  var CACHE_MS = 60000;
  var GROUP = 4;

  var state = { status: null, at: 0, busy: "", pending: null, revealed: null, note: "", err: "" };
  var modal = null;

  function api() { return global.cyberKarmaApi; }
  function T(zh) {
    var t = global.CYBER_I18N;
    return t && t.T ? t.T(zh) : zh;
  }
  function Tf(zh) {
    var t = global.CYBER_I18N;
    var args = [zh];
    for (var i = 1; i < arguments.length; i += 1) args.push(arguments[i]);
    if (t && t.Tf) return t.Tf.apply(t, args);
    var out = T(zh);
    for (var k = 1; k < arguments.length; k += 1) {
      out = out.split("{" + (k - 1) + "}").join(arguments[k] == null ? "" : String(arguments[k]));
    }
    return out;
  }
  function byId(id) { return document.getElementById(id); }
  function esc(v) {
    return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function authed() {
    if (String(global.KARMA_IDENTITY_ID || "").trim()) return true;
    var auth = global.KarmaWalletAuth;
    if (auth && typeof auth.readSession === "function") {
      var s = auth.readSession();
      return !!(s && (s.wallet || s.token));
    }
    return false;
  }
  function grouped(secret) {
    var out = [];
    for (var i = 0; i < String(secret || "").length; i += GROUP) {
      out.push(String(secret).substr(i, GROUP));
    }
    return out.join(" ");
  }

  /* ------------------------------------------------------------ 状态 */

  async function loadStatus(force) {
    if (!force && state.status && Date.now() - state.at < CACHE_MS) return state.status;
    var st = await api().getTwoFactor();
    state.status = st;
    state.at = Date.now();
    return st;
  }

  function statusSync() { return state.status; }

  /* ------------------------------------------------------------ 弹窗 */

  function buildModal() {
    if (modal) return modal;
    modal = document.createElement("div");
    modal.id = "k2fa-modal";
    modal.className = "k2fa-modal";
    modal.hidden = true;
    modal.innerHTML =
      '<div class="k2fa-box" role="dialog" aria-modal="true">' +
      '<h3 id="k2fa-title"></h3>' +
      '<p class="k2fa-sub" id="k2fa-sub">' +
      esc(T("输入验证器里的 6 位验证码。手机丢了就输入一张恢复码（形如 A1B2-C3D4），用掉即焚。")) +
      "</p>" +
      '<input id="k2fa-input" inputmode="numeric" autocomplete="one-time-code" maxlength="9" placeholder="123456" />' +
      '<p class="k2fa-err" id="k2fa-err"></p>' +
      '<div class="k2fa-actions">' +
      '<button type="button" class="btn primary" id="k2fa-ok">' + esc(T("确认")) + "</button>" +
      '<button type="button" class="btn" id="k2fa-cancel">' + esc(T("取消")) + "</button>" +
      "</div></div>";
    document.body.appendChild(modal);
    byId("k2fa-cancel").addEventListener("click", function () { closeModal(""); });
    byId("k2fa-ok").addEventListener("click", function () { submitModal(); });
    byId("k2fa-input").addEventListener("keydown", function (ev) {
      if (ev.key === "Enter") submitModal();
    });
    byId("k2fa-input").addEventListener("input", function () {
      // 6 位数字输满就自动提交；恢复码带横线，交给用户按确认。
      var v = byId("k2fa-input").value.replace(/\D/g, "");
      if (v.length === 6) submitModal();
    });
    return modal;
  }

  var modalResolve = null;

  function openModal(title, error) {
    buildModal();
    byId("k2fa-title").textContent = title || T("安全验证");
    var err = byId("k2fa-err");
    err.textContent = error || "";
    err.classList.toggle("on", !!error);
    var input = byId("k2fa-input");
    input.value = "";
    modal.hidden = false;
    try { input.focus(); } catch (_) {}
    return new Promise(function (resolve) { modalResolve = resolve; });
  }

  function closeModal(value) {
    if (modal) modal.hidden = true;
    var resolve = modalResolve;
    modalResolve = null;
    if (resolve) resolve(value || "");
  }

  function submitModal() {
    var input = byId("k2fa-input");
    var value = String(input.value || "").trim();
    if (!value) return;
    closeModal(value);
  }

  /** 要一次验证码。用户取消 → 空串（调用方别执行）。 */
  function ask(what, error) {
    var title = what ? Tf("安全验证 · {0}", T(what)) : T("安全验证");
    return openModal(title, error);
  }

  /* ------------------------------------------------------------ 闸门 */

  /**
   * 先要码，再执行；码被服务端拒了就再问一次（服务端同时记账，连错会被锁）。
   * 返回 run() 的结果；用户取消或没绑且必须绑时返回 null —— 调用方一律当「没做」处理。
   */
  async function guard(run, what) {
    var st;
    try {
      st = await loadStatus();
    } catch (e) {
      st = null;
    }
    if (!st || !st.enabled) {
      if (st && st.required_for_funds) {
        state.err = T("这个操作要过 2FA：请先在设置页绑定验证器。");
        render();
        ask(T("安全验证"), state.err);
        return null;
      }
      // 没绑 2FA：只有钱包签名那道锁（这是默认姿态；运维可以把强制开关打开）。
      return await run("");
    }
    var code = await ask(what);
    if (!code) return null;
    try {
      return await run(code);
    } catch (e) {
      var msg = String((e && e.message) || "");
      if (e && e.status === 401 && /2FA/i.test(msg)) {
        var again = await ask(what, T("验证码不对，再试一次（连着错会被锁一会儿）。"));
        if (!again) throw e;
        return await run(again);
      }
      throw e;
    }
  }

  /* ------------------------------------------------------------ 设置页卡片 */

  function render() {
    var host = byId("k2fa-card");
    if (!host) return;
    var st = state.status;
    var head =
      '<div class="section-header"><div><h3>' + esc(T("安全验证 · 2FA")) + "</h3>" +
      "<p>" +
      esc(
        T(
          "授权额度与取消授权都要过一次 6 位验证码；验证码由你手机上的验证器 App 生成 —— 钥匙被偷了也花不动钱。"
        )
      ) +
      "</p></div></div>";

    var body = "";
    if (!authed()) {
      body = '<p class="k2fa-hint">' + esc(T("连接钱包后，这里可以绑定验证器。")) + "</p>";
    } else if (st && st.enabled) {
      body =
        '<p class="k2fa-state k2fa-on">' +
        esc(
          st.locked
            ? Tf("已绑定 · 剩余恢复码 {0} 张 · 暂时锁定", st.recovery_left)
            : Tf("已绑定 · 剩余恢复码 {0} 张", st.recovery_left)
        ) +
        "</p>" +
        '<p class="k2fa-hint">' +
        esc(
          T(
            "现在每一次「加额 / 减额 / 取消授权」「停用钥匙」「取消绑定」都要过验证码。"
          )
        ) +
        "</p>" +
        '<div class="k2fa-actions">' +
        '<button type="button" class="btn" id="k2fa-rotate">' + esc(T("换一组恢复码")) + "</button>" +
        '<button type="button" class="btn" id="k2fa-off">' + esc(T("解绑 2FA")) + "</button>" +
        "</div>";
    } else if (state.pending) {
      var secret = state.pending.secret || "";
      body =
        '<p class="k2fa-state">' + esc(T("在验证器 App 里手动输入这串密钥：")) + "</p>" +
        '<code class="k2fa-secret" id="k2fa-secret">' + esc(grouped(secret)) + "</code>" +
        '<div class="k2fa-actions">' +
        '<button type="button" class="btn" id="k2fa-copy">' + esc(T("复制密钥")) + "</button>" +
        '<button type="button" class="btn" id="k2fa-copy-uri">' + esc(T("复制 otpauth 链接")) + "</button>" +
        "</div>" +
        '<p class="k2fa-hint">' +
        esc(T("建议同时扫进两台设备；以后换手机就靠它，别只存一台。")) +
        "</p>" +
        '<div class="k2fa-inline">' +
        '<input id="k2fa-code" inputmode="numeric" maxlength="6" placeholder="' + esc(T("验证器上的 6 位数字")) + '" />' +
        '<button type="button" class="btn primary" id="k2fa-confirm">' + esc(T("确认绑定")) + "</button>" +
        '<button type="button" class="btn" id="k2fa-cancel-enroll">' + esc(T("取消")) + "</button>" +
        "</div>";
    } else {
      body =
        '<p class="k2fa-state">' +
        esc(
          st && st.required_for_funds
            ? T("未绑定 · 这台节点要求先绑定，才能动额度")
            : T("未绑定 · 现在只有钱包签名一道锁")
        ) +
        "</p>" +
        '<div class="k2fa-actions">' +
        '<button type="button" class="btn primary" id="k2fa-enroll">' + esc(T("绑定验证器（2FA）")) + "</button>" +
        "</div>";
    }

    if (state.revealed && state.revealed.length) {
      body +=
        '<div class="k2fa-codes"><p class="k2fa-state">' +
        esc(T("恢复码只显示这一次，抄下来收好：")) +
        "</p><ol>" +
        state.revealed.map(function (c) { return "<li><code>" + esc(c) + "</code></li>"; }).join("") +
        "</ol>" +
        '<button type="button" class="btn" id="k2fa-hide">' + esc(T("已抄好，收起来")) + "</button></div>";
    }
    if (state.note) body += '<p class="k2fa-hint k2fa-good">' + esc(state.note) + "</p>";
    if (state.err) body += '<p class="k2fa-hint k2fa-bad">' + esc(state.err) + "</p>";

    host.innerHTML = head + body;
    wire();
  }

  function copy(text, label) {
    try {
      if (global.navigator && global.navigator.clipboard) {
        global.navigator.clipboard.writeText(text);
        state.note = Tf("{0}已复制。", T(label));
        state.err = "";
        render();
      }
    } catch (_) {}
  }

  function wire() {
    var on = function (id, fn) {
      var el = byId(id);
      if (el) el.addEventListener("click", fn);
    };
    on("k2fa-enroll", function () { doEnroll(); });
    on("k2fa-confirm", function () { doConfirm(); });
    on("k2fa-cancel-enroll", function () { state.pending = null; state.err = ""; render(); });
    on("k2fa-copy", function () { copy((state.pending || {}).secret || "", T("密钥")); });
    on("k2fa-copy-uri", function () { copy((state.pending || {}).otpauth_uri || "", T("otpauth 链接")); });
    on("k2fa-hide", function () { state.revealed = null; render(); });
    on("k2fa-rotate", function () { doRotate(); });
    on("k2fa-off", function () { doDisable(); });
  }

  async function doEnroll() {
    state.err = "";
    state.note = "";
    try {
      state.pending = await api().enrollTwoFactor();
      render();
    } catch (e) {
      state.err = String((e && e.message) || e);
      render();
    }
  }

  async function doConfirm() {
    var input = byId("k2fa-code");
    var code = String((input && input.value) || "").trim();
    if (!code) return;
    try {
      var res = await api().activateTwoFactor(code);
      state.pending = null;
      state.revealed = res.recovery_codes || [];
      state.status = res;
      state.at = Date.now();
      state.note = T("已绑定：以后动额度都要过验证码。");
      state.err = "";
      render();
    } catch (e) {
      state.err = String((e && e.message) || e);
      render();
    }
  }

  async function doRotate() {
    var code = await ask(T("换一组恢复码"));
    if (!code) return;
    try {
      var res = await api().rotateTwoFactorRecovery(code);
      state.revealed = res.recovery_codes || [];
      state.status = res;
      state.at = Date.now();
      state.note = T("新的恢复码只显示这一次。");
      state.err = "";
      render();
    } catch (e) {
      state.err = String((e && e.message) || e);
      render();
    }
  }

  async function doDisable() {
    var code = await ask(T("解绑 2FA"));
    if (!code) return;
    try {
      state.status = await api().disableTwoFactor(code);
      state.at = Date.now();
      state.revealed = null;
      state.note = T("已解绑：动额度回到只认钱包签名。");
      state.err = "";
      render();
    } catch (e) {
      state.err = String((e && e.message) || e);
      render();
    }
  }

  async function refresh() {
    if (!byId("k2fa-card")) return;
    if (!authed()) {
      state.status = null;
      state.at = 0;
      render();
      return;
    }
    try {
      await loadStatus(true);
      state.err = "";
    } catch (e) {
      state.err = String((e && e.message) || e);
    }
    render();
  }

  global.Karma2FA = {
    ask: ask,
    guard: guard,
    loadStatus: loadStatus,
    refresh: refresh,
    render: render,
    status: statusSync,
  };
})(window);
