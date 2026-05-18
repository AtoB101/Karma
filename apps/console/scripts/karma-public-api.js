/**
 * Minimal Karma public HTTP client for static console pages.
 * Configure before other scripts:
 *   window.KARMA_API_BASE = "http://127.0.0.1:8000";
 *   window.KARMA_API_KEY = "karma_worker-001_secret"; // optional in dev
 */
(function (global) {
  function apiBase() {
    return String(global.KARMA_API_BASE || "http://127.0.0.1:8000")
      .trim()
      .replace(/\/$/, "");
  }

  function headers() {
    const h = { Accept: "application/json" };
    const key = String(global.KARMA_API_KEY || "").trim();
    if (key) h["X-Karma-Api-Key"] = key;
    return h;
  }

  async function karmaFetch(path, init) {
    const url = apiBase() + path;
    const res = await fetch(url, init);
    const text = await res.text();
    let body;
    try {
      body = text ? JSON.parse(text) : null;
    } catch {
      body = { raw: text };
    }
    if (!res.ok) {
      const msg =
        (body && (body.detail || body.message)) ||
        (typeof body === "object" ? JSON.stringify(body) : text) ||
        res.statusText;
      const err = new Error("HTTP " + res.status + ": " + msg);
      err.status = res.status;
      err.body = body;
      throw err;
    }
    return body;
  }

  async function getCapacity(identityId) {
    const id = encodeURIComponent(identityId);
    return karmaFetch("/v1/capacity/" + id, { method: "GET", headers: headers() });
  }

  async function getSettlement(taskId) {
    const id = encodeURIComponent(taskId);
    return karmaFetch("/v1/settlement/" + id, { method: "GET", headers: headers() });
  }

  async function runtimeCreateKey(payload) {
    return karmaFetch("/runtime/create-key", {
      method: "POST",
      headers: { ...headers(), "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  async function runtimeListKeys(payload) {
    return karmaFetch("/runtime/list-keys", {
      method: "POST",
      headers: { ...headers(), "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  async function runtimeRevokeKey(payload) {
    return karmaFetch("/runtime/revoke-key", {
      method: "POST",
      headers: { ...headers(), "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  async function getHealth() {
    return karmaFetch("/health", { method: "GET", headers: { Accept: "application/json" } });
  }

  async function getV1Info() {
    return karmaFetch("/v1/info", { method: "GET", headers: headers() });
  }

  async function getContract(taskId) {
    return karmaFetch("/v1/contracts/" + encodeURIComponent(taskId), { method: "GET", headers: headers() });
  }

  async function listReceiptsForTask(taskId) {
    return karmaFetch("/v1/receipts/task/" + encodeURIComponent(taskId), { method: "GET", headers: headers() });
  }

  async function listProgressForTask(taskId) {
    return karmaFetch("/v1/progress/task/" + encodeURIComponent(taskId), { method: "GET", headers: headers() });
  }

  async function getBundleForTask(taskId) {
    return karmaFetch("/v1/bundles/task/" + encodeURIComponent(taskId), { method: "GET", headers: headers() });
  }

  async function listSettlementTransitions(taskId) {
    return karmaFetch(
      "/v1/settlement/" + encodeURIComponent(taskId) + "/transitions?limit=50",
      { method: "GET", headers: headers() }
    );
  }

  async function listAgents(role) {
    var q = role ? "?role=" + encodeURIComponent(role) : "";
    return karmaFetch("/v1/agents" + q, { method: "GET", headers: headers() });
  }

  async function getRuntimeSafetyMode() {
    return karmaFetch("/v1/security/runtime/safety-mode", { method: "GET", headers: headers() });
  }

  async function getOpenclawHandoffDraft(taskId, traceId) {
    const q = new URLSearchParams({ task_id: taskId });
    if (traceId) q.set("trace_id", traceId);
    return karmaFetch("/v1/openclaw/handoff-draft?" + q.toString(), { method: "GET", headers: headers() });
  }

  async function getAutomationPolicy(identityId) {
    return karmaFetch("/v1/identities/" + encodeURIComponent(identityId) + "/automation-policy", {
      method: "GET",
      headers: headers(),
    });
  }

  async function putAutomationPolicy(identityId, payload) {
    return karmaFetch("/v1/identities/" + encodeURIComponent(identityId) + "/automation-policy", {
      method: "PUT",
      headers: { ...headers(), "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  async function postOpenclawHandoffConfirm(payload) {
    return karmaFetch("/v1/openclaw/handoff-confirm", {
      method: "POST",
      headers: { ...headers(), "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  async function getOpenclawHandoffAttestation(taskId, identityId) {
    const q = new URLSearchParams({ task_id: taskId, karma_identity_id: identityId });
    return karmaFetch("/v1/openclaw/handoff-attestation?" + q.toString(), { method: "GET", headers: headers() });
  }

  async function getOpenclawAutomationReadiness(taskId, role, identityId) {
    const q = new URLSearchParams({ task_id: taskId, role: role || "buyer" });
    if (identityId) q.set("karma_identity_id", identityId);
    return karmaFetch("/v1/openclaw/automation-readiness?" + q.toString(), { method: "GET", headers: headers() });
  }

  async function listOpenclawHandoffEvents(taskId, limit) {
    const q = new URLSearchParams();
    if (taskId) q.set("task_id", taskId);
    if (limit != null) q.set("limit", String(limit));
    const qs = q.toString();
    return karmaFetch("/v1/openclaw/handoff-events" + (qs ? "?" + qs : ""), { method: "GET", headers: headers() });
  }

  function jsonPost(path, payload, extraHeaders) {
    const h = { ...headers(), "Content-Type": "application/json" };
    if (extraHeaders) {
      for (const ek in extraHeaders) {
        if (Object.prototype.hasOwnProperty.call(extraHeaders, ek)) h[ek] = extraHeaders[ek];
      }
    }
    return karmaFetch(path, {
      method: "POST",
      headers: h,
      body: JSON.stringify(payload == null ? {} : payload),
    });
  }

  function jsonPut(path, payload) {
    return karmaFetch(path, {
      method: "PUT",
      headers: { ...headers(), "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  async function postAuthToken(agentId, apiKey) {
    return karmaFetch("/v1/auth/token", {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify({ agent_id: agentId, api_key: apiKey }),
    });
  }

  async function lockCapacity(identityId, amount) {
    const id = encodeURIComponent(identityId);
    return jsonPost("/v1/capacity/" + id + "/lock", { amount: Number(amount) });
  }

  async function releaseCapacity(identityId, amount) {
    const id = encodeURIComponent(identityId);
    return jsonPost("/v1/capacity/" + id + "/release", { amount: Number(amount) });
  }

  async function createSettlement(payload) {
    return jsonPost("/v1/settlement/create", payload);
  }

  async function settlementPending(taskId) {
    return jsonPost("/v1/settlement/" + encodeURIComponent(taskId) + "/pending", {});
  }

  async function settlementLock(taskId, workerAgentId) {
    return jsonPost("/v1/settlement/" + encodeURIComponent(taskId) + "/lock", {
      worker_agent_id: workerAgentId,
    });
  }

  async function settlementStart(taskId) {
    return jsonPost("/v1/settlement/" + encodeURIComponent(taskId) + "/start", {});
  }

  async function settlementSubmit(taskId) {
    return jsonPost("/v1/settlement/" + encodeURIComponent(taskId) + "/submit", {});
  }

  async function settlementFail(taskId) {
    return jsonPost("/v1/settlement/" + encodeURIComponent(taskId) + "/fail", {});
  }

  async function settlementDispute(taskId, reason) {
    return jsonPost("/v1/settlement/" + encodeURIComponent(taskId) + "/dispute", {
      reason: reason || "console dispute",
    });
  }

  async function settlementBuyerAccept(taskId) {
    return jsonPost("/v1/settlement/" + encodeURIComponent(taskId) + "/buyer-accept", {});
  }

  async function settlementPartial(taskId, settledValuePercent, reason) {
    return jsonPost("/v1/settlement/" + encodeURIComponent(taskId) + "/partial", {
      settled_value_percent: Number(settledValuePercent),
      reason: reason || null,
    });
  }

  async function settlementRegret(taskId, buyerIdentityId, reason) {
    return jsonPost("/v1/settlement/" + encodeURIComponent(taskId) + "/regret", {
      buyer_identity_id: buyerIdentityId || null,
      reason: reason || null,
    });
  }

  async function createPaymentCode(body) {
    return jsonPost("/v1/payment-codes", body);
  }

  async function getPaymentCode(voucherId) {
    return karmaFetch("/v1/payment-codes/" + encodeURIComponent(voucherId), {
      method: "GET",
      headers: headers(),
    });
  }

  async function acceptPaymentCode(voucherId, sellerIdentityId) {
    return jsonPost("/v1/payment-codes/" + encodeURIComponent(voucherId) + "/accept", {
      seller_identity_id: sellerIdentityId,
    });
  }

  async function rejectPaymentCode(voucherId, sellerIdentityId, reason) {
    return jsonPost("/v1/payment-codes/" + encodeURIComponent(voucherId) + "/reject", {
      seller_identity_id: sellerIdentityId,
      reason: reason || "rejected",
    });
  }

  async function getVoucherEvents(voucherId, identityId) {
    const q = new URLSearchParams({ identity_id: identityId });
    return karmaFetch(
      "/v1/vouchers/" + encodeURIComponent(voucherId) + "/events?" + q.toString(),
      { method: "GET", headers: headers() }
    );
  }

  async function launchTradeOrder(body, idempotencyKey) {
    const extra = idempotencyKey ? { "Idempotency-Key": idempotencyKey } : null;
    return jsonPost("/v1/trade/orders/launch", body, extra);
  }

  global.cyberKarmaApi = {
    apiBase,
    karmaFetch,
    headers,
    getCapacity,
    getSettlement,
    getHealth,
    getV1Info,
    getContract,
    listReceiptsForTask,
    listProgressForTask,
    getBundleForTask,
    listSettlementTransitions,
    listAgents,
    getRuntimeSafetyMode,
    getOpenclawHandoffDraft,
    getOpenclawAutomationReadiness,
    postOpenclawHandoffConfirm,
    getOpenclawHandoffAttestation,
    getAutomationPolicy,
    putAutomationPolicy,
    listOpenclawHandoffEvents,
    postAuthToken,
    lockCapacity,
    releaseCapacity,
    createSettlement,
    settlementPending,
    settlementLock,
    settlementStart,
    settlementSubmit,
    settlementFail,
    settlementDispute,
    settlementBuyerAccept,
    settlementPartial,
    settlementRegret,
    createPaymentCode,
    getPaymentCode,
    acceptPaymentCode,
    rejectPaymentCode,
    getVoucherEvents,
    launchTradeOrder,
    jsonPost,
    jsonPut,
  };
  global.karmaRuntimeApi = { runtimeCreateKey, runtimeListKeys, runtimeRevokeKey, karmaFetch, headers };
})(window);
