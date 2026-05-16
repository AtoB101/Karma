/**
 * Console Trade — phase 1 traditional payment code + optional preauth.
 */
(function () {
  var LS_BASE = "karma_cyber_api_base";
  var LS_KEY = "karma_cyber_api_key";
  var LS_ID = "karma_cyber_identity_id";
  var LS_PREAUTH = "karma_console_preauth_enabled";

  function $(sel) {
    return document.querySelector(sel);
  }

  function apiBase() {
    return String($("[data-cfg=api_base]")?.value || localStorage.getItem(LS_BASE) || "http://127.0.0.1:8000")
      .trim()
      .replace(/\/$/, "");
  }

  function apiKey() {
    return String($("[data-cfg=api_key]")?.value || localStorage.getItem(LS_KEY) || "").trim();
  }

  function identityId() {
    return String($("[data-cfg=identity_id]")?.value || localStorage.getItem(LS_ID) || "").trim();
  }

  function headers() {
    var h = { Accept: "application/json", "Content-Type": "application/json" };
    var k = apiKey();
    if (k) h["X-Karma-Api-Key"] = k;
    return h;
  }

  function field(name) {
    return $("[data-f=" + name + "]")?.value?.trim() || "";
  }

  function preauthField(name) {
    var el = $("[data-p=" + name + "]");
    if (!el) return null;
    if (el.type === "checkbox") return el.checked;
    return el.value?.trim() || "";
  }

  function saveCfg() {
    try {
      localStorage.setItem(LS_BASE, apiBase());
      localStorage.setItem(LS_KEY, apiKey());
      localStorage.setItem(LS_ID, identityId());
    } catch (_) {}
  }

  function loadCfg() {
    if ($("[data-cfg=api_base]")) $("[data-cfg=api_base]").value = localStorage.getItem(LS_BASE) || "";
    if ($("[data-cfg=api_key]")) $("[data-cfg=api_key]").value = localStorage.getItem(LS_KEY) || "";
    if ($("[data-cfg=identity_id]")) $("[data-cfg=identity_id]").value = localStorage.getItem(LS_ID) || "";
    var pre = localStorage.getItem(LS_PREAUTH) === "1";
    if ($("[data-preauth-toggle]")) $("[data-preauth-toggle]").checked = pre;
    syncPreauthUi(pre);
  }

  function syncPreauthUi(on) {
    var panel = $("[data-preauth-panel]");
    var btnPre = $("[data-create-payment-code-preauth]");
    var sellerOnly = $("[data-seller-only]");
    if (panel) panel.hidden = !on;
    if (btnPre) btnPre.hidden = !on;
    var role = $("[data-trade-role]")?.value || "buyer";
    if (sellerOnly) sellerOnly.hidden = role !== "seller";
  }

  function collectPaymentCodeBody(mode) {
    return {
      buyer_identity_id: identityId(),
      seller_identity_id: field("seller_identity_id"),
      amount: Number(field("amount") || 0),
      bill_credit_amount: Number(field("bill_credit_amount") || field("amount") || 0),
      currency: "USDC",
      task_type: field("task_type") || "api.task",
      task_precision: Number(field("task_precision") || 0),
      task_description_hash: "auto",
      progress_rule_hash: "auto",
      evidence_requirement_hash: "auto",
      buyer_signature: field("buyer_signature") || "0xdev",
      payment_mode: mode,
      chain_anchor_hash: field("chain_anchor_hash") || null,
      ttl_seconds: Number(field("ttl_seconds") || 3600),
    };
  }

  async function createPaymentCode(mode) {
    saveCfg();
    var st = $("[data-buyer-status]");
    if (st) st.textContent = "提交中…";
    try {
      var res = await fetch(apiBase() + "/v1/payment-codes", {
        method: "POST",
        headers: headers(),
        body: JSON.stringify(collectPaymentCodeBody(mode)),
      });
      var body = await res.json();
      if (!res.ok) throw new Error(JSON.stringify(body));
      if ($("[data-f=voucher_id]")) $("[data-f=voucher_id]").value = body.voucher?.voucher_id || "";
      if ($("[data-payment-code-out]")) $("[data-payment-code-out]").textContent = JSON.stringify(body, null, 2);
      if (st) {
        var auto = body.auto_result;
        st.textContent = auto
          ? "已创建 · 自动处理: " + auto.action + " (" + auto.reason + ")"
          : "已创建 · 等待卖方手动接单";
      }
    } catch (e) {
      if (st) st.textContent = "失败: " + (e.message || e);
    }
  }

  async function loadPaymentCode() {
    var vid = field("voucher_id");
    var st = $("[data-seller-status]");
    if (!vid) {
      if (st) st.textContent = "请填写 voucher_id";
      return;
    }
    try {
      var res = await fetch(apiBase() + "/v1/payment-codes/" + encodeURIComponent(vid), { headers: headers() });
      var body = await res.json();
      if (!res.ok) throw new Error(JSON.stringify(body));
      if ($("[data-seller-code-out]")) $("[data-seller-code-out]").textContent = JSON.stringify(body, null, 2);
      if (st) st.textContent = "状态: " + (body.voucher_status || "—");
      await loadEvents(vid);
    } catch (e) {
      if (st) st.textContent = "失败: " + (e.message || e);
    }
  }

  async function loadEvents(vid) {
    var id = identityId();
    var res = await fetch(
      apiBase() + "/v1/vouchers/" + encodeURIComponent(vid) + "/events?identity_id=" + encodeURIComponent(id),
      { headers: headers() }
    );
    var body = await res.json();
    if ($("[data-voucher-events-out]")) $("[data-voucher-events-out]").textContent = JSON.stringify(body, null, 2);
  }

  async function acceptVoucher() {
    var vid = field("voucher_id");
    var st = $("[data-seller-status]");
    try {
      var res = await fetch(apiBase() + "/v1/payment-codes/" + encodeURIComponent(vid) + "/accept", {
        method: "POST",
        headers: headers(),
        body: JSON.stringify({ seller_identity_id: identityId() }),
      });
      var body = await res.json();
      if (!res.ok) throw new Error(JSON.stringify(body));
      if (st) st.textContent = "已接单";
      await loadEvents(vid);
    } catch (e) {
      if (st) st.textContent = "接单失败: " + (e.message || e);
    }
  }

  async function rejectVoucher() {
    var vid = field("voucher_id");
    var st = $("[data-seller-status]");
    try {
      var res = await fetch(apiBase() + "/v1/payment-codes/" + encodeURIComponent(vid) + "/reject", {
        method: "POST",
        headers: headers(),
        body: JSON.stringify({
          seller_identity_id: identityId(),
          reason: field("reject_reason") || "rejected",
        }),
      });
      var body = await res.json();
      if (!res.ok) throw new Error(JSON.stringify(body));
      if (st) st.textContent = "已拒绝并回执买方";
      await loadEvents(vid);
    } catch (e) {
      if (st) st.textContent = "拒绝失败: " + (e.message || e);
    }
  }

  function splitList(s) {
    return String(s || "")
      .split(",")
      .map(function (x) {
        return x.trim();
      })
      .filter(Boolean);
  }

  async function savePreauth() {
    saveCfg();
    var id = identityId();
    var st = $("[data-preauth-status]");
    var role = $("[data-trade-role]")?.value || "buyer";
    var perms = ["submit_receipt", "update_progress", "check_voucher"];
    if (role === "seller") perms.push("verify_voucher");
    var body = {
      auto_enabled: !!preauthField("auto_enabled"),
      single_limit: Number(preauthField("single_limit") || 100),
      daily_limit: Number(preauthField("daily_limit") || 500),
      permissions: perms,
      high_risk_mode: "always",
      responsibility_acknowledged: !!preauthField("responsibility_ack"),
      preauth_enabled: true,
      allowed_task_types: splitList(preauthField("allowed_task_types")),
      task_precision_min: preauthField("task_precision_min") === "" ? null : Number(preauthField("task_precision_min")),
      task_precision_max: preauthField("task_precision_max") === "" ? null : Number(preauthField("task_precision_max")),
      trusted_counterparty_ids: splitList(preauthField("trusted_counterparty_ids")),
      payment_code_ttl_seconds: Number(preauthField("payment_code_ttl_seconds") || 3600),
      responsibility_boundary_id: preauthField("responsibility_boundary_id") || null,
      auto_accept_incoming: role === "seller" && !!preauthField("auto_accept_incoming"),
    };
    try {
      var res = await fetch(apiBase() + "/v1/identities/" + encodeURIComponent(id) + "/automation-policy", {
        method: "PUT",
        headers: headers(),
        body: JSON.stringify(body),
      });
      var data = await res.json();
      if (!res.ok) throw new Error(JSON.stringify(data));
      if (st) st.textContent = "预授权：已保存 v" + (data.policy_version || "?");
    } catch (e) {
      if (st) st.textContent = "保存失败: " + (e.message || e);
    }
  }

  function bind() {
    loadCfg();
    $("[data-save-cfg]")?.addEventListener("click", saveCfg);
    $("[data-create-payment-code]")?.addEventListener("click", function () {
      createPaymentCode("manual");
    });
    $("[data-create-payment-code-preauth]")?.addEventListener("click", function () {
      createPaymentCode("preauth");
    });
    $("[data-load-payment-code]")?.addEventListener("click", loadPaymentCode);
    $("[data-accept-voucher]")?.addEventListener("click", acceptVoucher);
    $("[data-reject-voucher]")?.addEventListener("click", rejectVoucher);
    $("[data-save-preauth]")?.addEventListener("click", savePreauth);
    $("[data-preauth-toggle]")?.addEventListener("change", function (ev) {
      var on = !!ev.target.checked;
      try {
        localStorage.setItem(LS_PREAUTH, on ? "1" : "0");
      } catch (_) {}
      syncPreauthUi(on);
    });
    $("[data-trade-role]")?.addEventListener("change", function () {
      syncPreauthUi(!!$("[data-preauth-toggle]")?.checked);
    });
  }

  if ($("[data-trade-root]")) bind();
})();
