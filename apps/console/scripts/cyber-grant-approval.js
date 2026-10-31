/**
 * 官方域 · 消费授权审批页（设备码式握手）。
 *
 * 主人在官方域独立页面打开 agent 给的 approval_uri：
 *   1. 核对 agent 名称 / 公钥指纹 / 币种 / 总额 / 单笔 / 有效期 / 用途；
 *   2. 输入 agent 在对话里展示的那串核对码（双向核对）；
 *   3. 连接钱包，对服务端返回的 canonical 授权文本 personal_sign；
 *   4. 服务端验码 + 验签 + 反查钱包绑定身份，三者都过才落 grant。
 *
 * 安全边界：只调 eth_requestAccounts / eth_accounts / personal_sign，
 * 从不索要私钥 / 助记词；签名文本由服务端重建，前端不自己拼额度。
 */
(function (global) {
  "use strict";

  function apiBase() {
    var raw = global.KARMA_API_BASE;
    if (raw === undefined || raw === null || String(raw).trim() === "") {
      try {
        if (global.location && /^https?:$/.test(global.location.protocol)) {
          return global.location.origin;
        }
      } catch (_) {}
      return "http://127.0.0.1:8000";
    }
    return String(raw).trim().replace(/\/$/, "");
  }

  function byId(id) { return document.getElementById(id); }
  function param(name) {
    try { return new URLSearchParams(global.location.search).get(name) || ""; } catch (_) { return ""; }
  }
  function node(tag, cls, text) {
    var el = document.createElement(tag);
    if (cls) el.className = cls;
    if (text !== undefined && text !== null) el.textContent = text;
    return el;
  }

  var challengeId = param("challenge");
  var data = null;
  var countdownTimer = null;

  function applyI18n() {
    try { if (global.CYBER_I18N) global.CYBER_I18N.applyCyberI18n(); } catch (_) {}
  }

  function clearBody() {
    var body = byId("grantBody");
    while (body && body.firstChild) body.removeChild(body.firstChild);
    return body;
  }

  function mount(root) {
    var body = clearBody();
    if (body) body.appendChild(root);
    applyI18n();
  }

  function humanTimeLeft() {
    if (!data || !data.expires_at) return "00:00";
    var end = Date.parse(data.expires_at);
    if (!isFinite(end)) return "00:00";
    var left = Math.max(0, Math.floor((end - Date.now()) / 1000));
    var mm = Math.floor(left / 60);
    var ss = left % 60;
    return (mm < 10 ? "0" + mm : String(mm)) + ":" + (ss < 10 ? "0" + ss : String(ss));
  }

  function startCountdown(el) {
    if (countdownTimer) clearInterval(countdownTimer);
    var tick = function () {
      el.textContent = humanTimeLeft();
      if (humanTimeLeft() === "00:00") {
        clearInterval(countdownTimer);
        if (data && data.status === "pending") renderExpired();
      }
    };
    tick();
    countdownTimer = setInterval(tick, 1000);
  }

  function kvRow(label, value) {
    var row = node("div", "grant-kv");
    row.appendChild(node("div", "grant-kv-label", label));
    row.appendChild(node("div", "grant-kv-value", value));
    return row;
  }

  function title(text) {
    return node("div", "grant-title", text);
  }
  function sub(text) {
    return node("div", "grant-sub", text);
  }

  function renderView() {
    var root = node("div", "grant-root");
    root.appendChild(title("授权审批"));
    root.appendChild(sub("请核对 agent 请求的消费授权，确认无误后再签名。"));

    var grid = node("div", "grant-grid");
    grid.appendChild(kvRow("Agent 名称", data.agent_name || ""));
    grid.appendChild(kvRow("公钥指纹", data.agent_public_key_fingerprint || "—"));
    grid.appendChild(kvRow("币种", data.currency || "USDC"));
    grid.appendChild(kvRow("总额上限", String(data.total_limit)));
    grid.appendChild(kvRow("单笔上限", String(data.per_tx_limit)));
    grid.appendChild(kvRow("有效期至", data.grant_expires_at || "长期有效"));
    grid.appendChild(kvRow("用途范围", (data.purpose_scope || []).join(", ") || "—"));
    root.appendChild(grid);

    var code = node("div", "grant-code");
    var label = node("label", "grant-code-label", "请输入 agent 在对话里展示的核对码");
    label.setAttribute("for", "grantCode");
    code.appendChild(label);
    var input = document.createElement("input");
    input.id = "grantCode";
    input.className = "grant-input";
    input.maxLength = 16;
    input.autocomplete = "off";
    input.placeholder = "K4QP-3M2X";
    code.appendChild(input);
    var codeError = node("div", "grant-error");
    codeError.id = "grantCodeError";
    codeError.hidden = true;
    code.appendChild(codeError);
    root.appendChild(code);

    var meta = node("div", "grant-meta");
    var item1 = node("span", "grant-meta-item");
    item1.appendChild(node("span", "", "剩余时间"));
    var cd = node("b", "", "00:00");
    cd.id = "grantCountdown";
    item1.appendChild(cd);
    meta.appendChild(item1);
    var item2 = node("span", "grant-meta-item");
    item2.appendChild(node("span", "", "剩余尝试次数"));
    var attempts = node("b", "", String(data.attempts_left));
    attempts.id = "grantAttempts";
    item2.appendChild(attempts);
    meta.appendChild(item2);
    root.appendChild(meta);

    root.appendChild(node("div", "grant-note", "批准后，agent 将只能在额度内消费，超出自动停止。"));

    var actions = node("div", "grant-actions");
    var cancel = node("button", "btn", "取消并返回");
    cancel.type = "button";
    cancel.id = "grantCancel";
    actions.appendChild(cancel);
    var approve = node("button", "btn primary", "连接钱包并签名");
    approve.type = "button";
    approve.id = "grantApprove";
    actions.appendChild(approve);
    root.appendChild(actions);

    var status = node("div", "api-status");
    status.id = "grantStatus";
    root.appendChild(status);

    mount(root);
    cancel.addEventListener("click", renderCancelled);
    approve.addEventListener("click", signAndApprove);
    startCountdown(cd);
  }

  function renderExpired() {
    var root = node("div", "grant-root");
    root.appendChild(title("授权请求已过期"));
    root.appendChild(sub("这次授权已经超时，请让 agent 重新发起一次。"));
    mount(root);
  }

  function renderHandled() {
    var root = node("div", "grant-root");
    root.appendChild(title("该授权请求已经处理过了"));
    root.appendChild(sub("这次授权已经生效或已被撤销，无需重复操作。"));
    mount(root);
  }

  function renderDone() {
    var root = node("div", "grant-root");
    root.appendChild(title("授权已生效"));
    root.appendChild(sub("agent 已获得消费授权，可在额度内自主花钱。"));
    root.appendChild(node("div", "grant-note", "你随时可以在操作台里查看、暂停或撤销这份授权。"));
    mount(root);
  }

  function renderCancelled() {
    var root = node("div", "grant-root");
    root.appendChild(title("你已终止本次接入，未产生任何资金划转。"));
    root.appendChild(sub("授权未创建，agent 仍不能替你花钱。"));
    mount(root);
  }

  function renderFault(detail) {
    var root = node("div", "grant-root");
    root.appendChild(title("加载失败，请刷新重试"));
    root.appendChild(sub(detail || ""));
    mount(root);
  }

  function setStatus(label, detail, isErr) {
    var status = byId("grantStatus");
    if (!status) return;
    status.textContent = "";
    status.classList.toggle("err", !!isErr);
    if (label) status.appendChild(node("span", "", label));
    if (detail) status.appendChild(node("span", "", detail));
  }

  function setBusy(busy) {
    var btn = byId("grantApprove");
    if (btn) btn.disabled = !!busy;
  }

  function setCodeMessage(text) {
    var el = byId("grantCodeError");
    if (!el) return;
    el.hidden = !text;
    if (text) el.textContent = text;
  }

  function readCode() {
    var input = byId("grantCode");
    return input ? input.value.trim() : "";
  }

  async function ensureWallet() {
    var wallet = global.KarmaOnboardingWallet;
    if (!wallet) throw new Error("wallet sign adapter not loaded");
    try {
      var acct = await wallet.currentAccount();
      if (acct) return acct;
    } catch (_) {}
    var provider = await wallet.resolveProvider();
    var accounts = await provider.request({ method: "eth_requestAccounts" });
    if (!accounts || !accounts.length) throw new Error("wallet not connected");
    return accounts[0];
  }

  async function signAndApprove() {
    var code = readCode();
    if (!code) {
      setCodeMessage("请输入 agent 在对话里展示的核对码");
      return;
    }
    setCodeMessage("");
    setBusy(true);
    setStatus("正在连接钱包…", "", false);
    try {
      var wallet = await ensureWallet();
      setStatus("正在获取待签文本…", "", false);
      var signRes = await fetch(
        apiBase() + "/v1/spending-grants/approval/" + encodeURIComponent(challengeId) +
        "/sign-message?wallet_address=" + encodeURIComponent(wallet)
      );
      if (!signRes.ok) throw new Error("could not fetch signing message");
      var signBody = await signRes.json();
      if (!signBody.message) throw new Error("server did not return a signing message");

      setStatus("请在钱包里签名", "", false);
      var signer = global.KarmaOnboardingWallet;
      if (!signer || typeof signer.sign !== "function") throw new Error("wallet sign adapter not loaded");
      signer.sign(
        signBody.message,
        function (signed) {
          submitApproval(code, signed.address, signed.signature);
        },
        function (err) {
          setBusy(false);
          setStatus("签名失败", ": " + (err && err.message ? err.message : String(err)), true);
        }
      );
    } catch (e) {
      setBusy(false);
      setStatus("连接失败", ": " + (e && e.message ? e.message : String(e)), true);
    }
  }

  async function submitApproval(code, wallet, signature) {
    try {
      var res = await fetch(
        apiBase() + "/v1/spending-grants/approval/" + encodeURIComponent(challengeId) + "/approve",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            confirmation_code: code,
            wallet_address: wallet,
            wallet_signature: signature,
          }),
        }
      );
      if (res.status === 403) {
        var errBody = null;
        try { errBody = await res.json(); } catch (_) {}
        var detail = (errBody && errBody.detail) || "";
        if (String(detail).indexOf("confirmation code") >= 0) {
          setCodeMessage("核对码不匹配，请重新输入");
          await reload();
          setBusy(false);
          return;
        }
        setStatus("批准失败", ": " + detail, true);
        setBusy(false);
        return;
      }
      if (!res.ok) {
        var body = null;
        try { body = await res.json(); } catch (_) {}
        if (res.status === 410) { renderExpired(); return; }
        if (res.status === 409) { renderHandled(); return; }
        setStatus("批准失败", ": " + ((body && body.detail) || ("HTTP " + res.status)), true);
        setBusy(false);
        return;
      }
      renderDone();
    } catch (e) {
      setBusy(false);
      setStatus("提交失败", ": " + (e && e.message ? e.message : String(e)), true);
    }
  }

  async function reload() {
    try {
      var res = await fetch(apiBase() + "/v1/spending-grants/approval/" + encodeURIComponent(challengeId));
      if (res.status === 404) { renderFault("授权请求不存在"); return; }
      if (!res.ok) { renderFault("HTTP " + res.status); return; }
      data = await res.json();
      if (data.status === "approved") { renderDone(); return; }
      if (data.status === "expired") { renderExpired(); return; }
      if (data.status !== "pending") { renderHandled(); return; }
      renderView();
    } catch (e) {
      renderFault(e && e.message ? e.message : String(e));
    }
  }

  function bindLang() {
    var sel = byId("grantLang");
    var i18n = global.CYBER_I18N;
    if (!sel || !i18n) return;
    var langs = i18n.SHIPPED_LANGS || [];
    var labels = i18n.LANG_LABELS || {};
    if (langs.length) {
      sel.innerHTML = "";
      langs.forEach(function (code) {
        var opt = document.createElement("option");
        opt.value = code;
        opt.textContent = labels[code] || code;
        sel.appendChild(opt);
      });
    }
    sel.value = i18n.getLang();
    sel.addEventListener("change", function () {
      i18n.setLang(sel.value);
      i18n.ensureExt(sel.value, function () { applyI18n(); });
    });
  }

  function init() {
    bindLang();
    if (!challengeId) {
      renderFault("缺少授权请求编号");
      return;
    }
    reload();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window);