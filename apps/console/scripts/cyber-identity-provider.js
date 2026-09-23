/**
 * 身份 · 官方实名核验（第三方服务商）—— 操作台里那一个按钮。
 *
 * 红线（和 services/identity_provider 一致）：
 * - 证件影像与人脸影像**直连服务商**：我们只把用户送到服务商那边去，
 *   Karma 既不接收、也不转发、更不保存明文；浏览器里也没有任何服务商密钥。
 * - 页面上写的每一句结论都必须来自服务端：没拿到 applied=true 之前，
 *   绝不说「已通过」。
 * - 没接服务商 / 密钥没配齐时，页面直说「未接入」，并指向人工复核那条路。
 */
(function () {
  "use strict";

  var POLL_MS = 4000;
  var POLL_MAX = 45; // 约三分钟，够了；再多就该让用户自己点「查结果」

  var state = {
    provider: null,
    session: null,
    busy: false,
    polls: 0,
    timer: null,
    loadedFor: "",
  };

  function byId(id) {
    return document.getElementById(id);
  }

  function api() {
    return window.cyberKarmaApi;
  }

  function identity() {
    return String(window.KARMA_IDENTITY_ID || "").trim();
  }

  function say(node, text, ok) {
    if (!node) return;
    node.textContent = text;
    node.style.color =
      ok === true ? "var(--accent,#4ade80)" : ok === false ? "#f87171" : "var(--text-dim)";
  }

  function badge(text, ok) {
    var node = byId("idv-provider-badge");
    if (!node) return;
    node.textContent = text;
    node.classList.toggle("ok", ok === true);
    node.classList.toggle("bad", ok === false);
  }

  function setBusy(flag) {
    state.busy = !!flag;
    var open = byId("idv-provider-open");
    if (open) open.disabled = !!flag || !usable();
  }

  function usable() {
    return !!(state.provider && state.provider.usable);
  }

  /**
   * 「走哪条」要写在脸上：服务商核验与人工复核是两条并排的通道。
   * 服务商没接入时，那张卡必须看得出是灰的；另一张标成「当前路径」，
   * 用户不用猜该从哪儿开始。
   */
  function markRoute() {
    var on = usable();
    var card = byId("idv-provider");
    if (card) {
      card.classList.toggle("is-off", !on);
      card.setAttribute("aria-disabled", on ? "false" : "true");
    }
    var route = byId("idv-verify-route");
    if (route) route.textContent = on ? "备用路径" : "当前路径";
  }

  function stopPolling() {
    if (state.timer) {
      window.clearTimeout(state.timer);
      state.timer = null;
    }
    state.polls = 0;
  }

  /* ------------------------------------------------------------ 渲染 */

  function render() {
    markRoute();
    var provider = state.provider || {};
    var note = byId("idv-provider-note");
    var hint = byId("idv-provider-hint");
    var sync = byId("idv-provider-sync");
    var name = provider.provider || "none";

    if (name === "none") {
      badge("未接入", null);
      if (note) {
        note.textContent =
          "当前没有接入第三方实名 / 活体服务。主身份认证走下面这条路：本机加密证件与刷脸，" +
          "提交后由复核台人工核验 —— 一样能认证，只是多一道人工。";
      }
      if (hint) {
        hint.textContent =
          "接入之后这里会变成一键官方核验（服务商核验通过即自动置位），不用人工等。";
      }
      say(byId("idv-provider-status"), "未接入服务商", null);
      if (sync) sync.hidden = true;
      setBusy(false);
      return;
    }

    if (!provider.usable) {
      badge("未配置", false);
      var missing = (provider.missing || []).join("、");
      if (note) {
        note.textContent =
          "已选择服务商 " + name + "，但服务器上还缺配置：" + (missing || "(未知)");
      }
      if (hint) hint.textContent = "把密钥补齐后刷新本页即可使用；在此之前仍可走下面的人工复核流程。";
      say(byId("idv-provider-status"), "服务商未配置完成", false);
      if (sync) sync.hidden = true;
      setBusy(false);
      return;
    }

    badge("已接入 · " + name, true);
    if (note) {
      note.textContent =
        "已接入服务商 " + name + "：点「开始官方核验」后，证件与人脸会直接交给服务商，" +
        "Karma 只收结论，不经手、也不保存你的证件与人脸明文。";
    }
    if (hint) {
      hint.textContent =
        provider.supports_pull
          ? "做完之后回到本页点「我已做完，查结果」；页面也会自动查。"
          : "做完之后回到本页，服务商会把结果回调给 Karma，页面会自动更新。";
    }
    var active = provider.state && provider.state.active;
    if (active && active.status === "waiting") {
      say(byId("idv-provider-status"), "上一次核验还没出结果（会话 " + short(active.session_id) + "）", null);
      if (sync) sync.hidden = !provider.supports_pull;
    } else {
      say(byId("idv-provider-status"), "可以开始", null);
      if (sync) sync.hidden = true;
    }
    setBusy(false);
  }

  function short(value) {
    var text = String(value || "");
    return text.length > 8 ? text.slice(0, 8) + "…" : text;
  }

  function renderResult(result) {
    if (!result) return;
    var status = result.status;
    if (result.applied && status === "verified") {
      badge("已通过", true);
      say(byId("idv-provider-status"), "服务商核验通过 —— 主身份已激活", true);
    } else if (status === "rejected") {
      badge("未通过", false);
      say(
        byId("idv-provider-status"),
        "服务商判定未通过" + (result.reason && result.reason !== "rejected" ? "（" + result.reason + "）" : "") +
          " —— 可以重新发起一次核验",
        false
      );
    } else if (result.reason === "already_verified") {
      badge("已通过", true);
      say(byId("idv-provider-status"), "这条身份已经是通过状态", true);
    } else if (result.reason === "provider_still_processing") {
      say(byId("idv-provider-status"), "服务商还在处理，稍后自动再查一次…", null);
    } else {
      say(byId("idv-provider-status"), "已收到，等待服务商结论…", null);
    }
    if (result.applied && window.KarmaIdentityVerify && window.KarmaIdentityVerify.refresh) {
      window.KarmaIdentityVerify.refresh();
    }
  }

  /* ------------------------------------------------------------ 动作 */

  async function load(force) {
    var id = identity();
    if (!id) {
      badge("未连接", null);
      say(byId("idv-provider-status"), "先连接钱包", null);
      return;
    }
    if (!api() || !api().getIdentityProvider) return;
    if (!force && state.loadedFor === id && state.provider) {
      render();
      return;
    }
    try {
      var body = await api().getIdentityProvider(id);
      state.provider = (body && body.provider) || { provider: "none" };
      var active = body && body.state && body.state.active;
      if (active) state.provider.state = body.state;
      state.loadedFor = id;
      render();
    } catch (e) {
      badge("查询失败", false);
      say(byId("idv-provider-status"), "查不到服务商状态：" + ((e && e.message) || e), false);
    }
  }

  async function open() {
    if (state.busy) return;
    var id = identity();
    if (!id) {
      say(byId("idv-provider-status"), "先连接钱包", false);
      return;
    }
    setBusy(true);
    say(byId("idv-provider-status"), "正在向服务商开一次核验…", null);
    try {
      var body = await api().openIdentityProviderSession(id, {
        return_url: window.location.origin + "/console/",
      });
      var session = (body && body.session) || {};
      state.session = session;
      if (session.verify_url) {
        // 直连服务商：新开一个窗口去做核验，本页只等结论。
        window.open(session.verify_url, "_blank", "noopener");
        say(byId("idv-provider-status"), "已打开服务商核验页 —— 做完回到本页", null);
      } else {
        say(byId("idv-provider-status"), "已开会话（本地模拟服务商），正在等结论…", null);
      }
      var sync = byId("idv-provider-sync");
      if (sync) sync.hidden = false;
      var provider = state.provider || {};
      if (provider.supports_pull) startPolling();
      setBusy(false);
    } catch (e) {
      setBusy(false);
      say(byId("idv-provider-status"), (e && e.message) || "开核验会话失败", false);
      await load(true);
    }
  }

  async function sync() {
    if (state.busy) return;
    var id = identity();
    if (!id) return;
    setBusy(true);
    try {
      var result = await api().syncIdentityProviderSession(id);
      renderResult(result);
    } catch (e) {
      say(byId("idv-provider-status"), (e && e.message) || "查不到结论", false);
    }
    setBusy(false);
  }

  function startPolling() {
    stopPolling();
    tick();
  }

  async function tick() {
    state.polls += 1;
    await sync();
    if (state.polls >= POLL_MAX) {
      say(byId("idv-provider-status"), "还没出结果 —— 稍后点「我已做完，查结果」再看", null);
      stopPolling();
      return;
    }
    state.timer = window.setTimeout(tick, POLL_MS);
  }

  /* ------------------------------------------------------------ 绑定 */

  function bind() {
    var openBtn = byId("idv-provider-open");
    var syncBtn = byId("idv-provider-sync");
    if (openBtn) openBtn.addEventListener("click", open);
    if (syncBtn) syncBtn.addEventListener("click", sync);

    ["karma-wallet-connected", "karma-session-restored", "karma-identity-switched"].forEach(
      function (name) {
        document.addEventListener(name, function () {
          stopPolling();
          load(true);
        });
      }
    );
    load(false);
  }

  window.KarmaIdentityProvider = {
    refresh: function () {
      load(true);
    },
    state: state,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind);
  } else {
    bind();
  }
})();
