/**
 * 入口门禁 —— 先连钱包，再进操作台。
 *
 * 为什么单独一个文件：操作台里每个页面都假设「已经有一个 identity_id」。
 * 以前用户可以先进来看一圈、点一堆按钮，每一步都因为没身份而失败，
 * 却始终不知道第一步该做什么。现在进来第一眼只有一件事：连接钱包。
 *
 * 两条设计约束：
 * - 失败开放：脚本没跑起来（被拦 / 报错）时不加 .gated，操作台照常可见，
 *   不会出现「白屏进不去」的死局。
 * - 拿到 access token + identity_id 才算进门；断开或会话过期自动退回门口。
 */
(function (global) {
  "use strict";

  var DEFAULT_HINT = "连上后这里会显示你的主身份 ID 和钱包地址。";

  function gate() { return document.getElementById("entry-gate"); }
  function hint() { return document.getElementById("entry-gate-hint"); }

  function session() {
    var auth = global.KarmaWalletAuth;
    try { return auth && auth.readSession ? auth.readSession() : {}; } catch (_) { return {}; }
  }

  function signedIn() {
    var s = session();
    var auth = global.KarmaWalletAuth;
    if (auth && auth.tokenState && auth.tokenState() === "expired") return false;
    if (!s.accessToken) return false;
    return !!String(s.identityId || global.KARMA_IDENTITY_ID || "").trim();
  }

  function setIdHint() {
    var node = hint();
    if (!node) return;
    var s = session();
    var id = String(s.identityId || global.KARMA_IDENTITY_ID || "").trim();
    var shown = global.KarmaDisplayId && id ? global.KarmaDisplayId.of(id, 0) : "";
    var wallet = String(s.wallet || "");
    if (shown) {
      node.textContent =
        "已认证 · " + shown + (wallet ? " · " + wallet.slice(0, 6) + "…" + wallet.slice(-4) : "");
    } else {
      node.textContent = DEFAULT_HINT;
    }
  }

  function openGate() {
    document.body.classList.add("gated");
    var box = gate();
    if (box) box.removeAttribute("hidden");
    setIdHint();
    /* 门开着的时候，顶栏那两个「连接 / 断开」按钮没意义（它们被盖住了），
       但键盘 Tab 仍然能走到 —— 收起来，避免焦点跑到看不见的控件上。 */
    document.querySelectorAll("[data-wallet-disconnect]").forEach(function (b) {
      b.hidden = true;
    });
  }

  function closeGate() {
    document.body.classList.remove("gated");
    var box = gate();
    if (box) box.setAttribute("hidden", "");
    document.querySelectorAll("[data-wallet-disconnect]").forEach(function (b) {
      b.hidden = false;
    });
    setIdHint();
  }

  function sync() {
    if (signedIn()) closeGate();
    else openGate();
    var box = gate();
    if (box) box.hidden = signedIn();
  }

  function bind() {
    /* 先按「没连上」处理：脚本执行到这里说明 JS 是活的，
       那么没会话就必须先过门。 */
    sync();
    document.addEventListener("karma-wallet-connected", function () { sync(); });
    document.addEventListener("karma-session-restored", function () { sync(); });
    document.addEventListener("karma-wallet-disconnected", function () { sync(); });
    document.addEventListener("karma-session-expired", function () {
      var node = hint();
      if (node) node.textContent = "会话已过期，请重新连接钱包。";
      openGate();
    });
  }

  global.KarmaEntryGate = { sync: sync, isOpen: function () { return document.body.classList.contains("gated"); } };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind);
  } else {
    bind();
  }
})(window);