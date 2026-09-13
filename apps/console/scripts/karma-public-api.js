/**
 * Minimal Karma public HTTP client for static console pages.
 * Configure before other scripts:
 *   window.KARMA_API_BASE = "http://127.0.0.1:8000";
 *   window.KARMA_API_KEY = "karma_worker-001_secret"; // optional in dev
 */
(function (global) {
  /**
   * Resolve the API base URL for every console page.
   *   unset (undefined / null) -> local dev API
   *   explicitly ""            -> same-origin (site reverse proxy in production)
   */
  function karmaResolveApiBase(raw) {
    if (raw === undefined || raw === null) return "http://127.0.0.1:8000";
    return String(raw).trim().replace(/\/+$/, "");
  }

  function apiBase() {
    return karmaResolveApiBase(global.KARMA_API_BASE);
  }

  // Restore the SIWE session token issued by console-wallet-auth.js so console
  // scripts that run before the wallet layer settles still send Authorization.
  try {
    if (!global.KARMA_ACCESS_TOKEN) {
      global.KARMA_ACCESS_TOKEN = sessionStorage.getItem("karma_console_access_token") || "";
    }
    if (!global.KARMA_IDENTITY_ID) {
      global.KARMA_IDENTITY_ID = sessionStorage.getItem("karma_console_identity") || "";
    }
  } catch (_) {}

  function headers() {
    const h = { Accept: "application/json" };
    const token = String(global.KARMA_ACCESS_TOKEN || "").trim();
    if (token) {
      h["Authorization"] = "Bearer " + token;
      return h;
    }
    const key = String(global.KARMA_API_KEY || "").trim();
    if (key) h["X-Karma-Api-Key"] = key;
    const id = String(global.KARMA_IDENTITY_ID || "").trim();
    if (id) h["X-Karma-Identity-Id"] = id;
    return h;
  }

  function activeProfileId() {
    try {
      if (global.KarmaIdentitySwitcher && global.KarmaIdentitySwitcher.getActiveProfileId) {
        var p = global.KarmaIdentitySwitcher.getActiveProfileId();
        if (p) return p;
      }
      return sessionStorage.getItem("karma_console_active_profile") || "";
    } catch (_) {
      return "";
    }
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

  async function getAllocations(identityId) {
    return karmaFetch(
      "/v1/capacity/" + encodeURIComponent(identityId) + "/allocations",
      { method: "GET", headers: headers() }
    );
  }

  async function setAllocations(identityId, allocations) {
    return jsonPut(
      "/v1/capacity/" + encodeURIComponent(identityId) + "/allocations",
      { allocations: allocations }
    );
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

  async function listRoleProfiles(ownerIdentityId) {
    var q = ownerIdentityId ? "?owner_identity_id=" + encodeURIComponent(ownerIdentityId) : "";
    return karmaFetch("/v1/identity/role-profiles" + q, { method: "GET", headers: headers() });
  }

  async function getRoleProfile(profileId) {
    return karmaFetch(
      "/v1/identity/role-profiles/" + encodeURIComponent(profileId),
      { method: "GET", headers: headers() }
    );
  }

  async function createRoleProfile(payload) {
    return jsonPost("/v1/identity/role-profiles", payload);
  }

  async function getIdentityCard(identityId) {
    return karmaFetch(
      "/v1/identity/" + encodeURIComponent(identityId) + "/card?scope=basic",
      { method: "GET", headers: headers() }
    );
  }

  async function grantDisclosure(profileId, body) {
    return jsonPost("/v1/identity/role-profiles/" + encodeURIComponent(profileId) + "/disclosures", body);
  }

  async function listDisclosures(profileId) {
    return karmaFetch(
      "/v1/identity/role-profiles/" + encodeURIComponent(profileId) + "/disclosures",
      { method: "GET", headers: headers() }
    );
  }

  async function revokeDisclosure(profileId, disclosureId) {
    return karmaFetch(
      "/v1/identity/role-profiles/" + encodeURIComponent(profileId) + "/disclosures/" + encodeURIComponent(disclosureId),
      { method: "DELETE", headers: headers() }
    );
  }

  async function getProfileLedger(profileId) {
    return karmaFetch(
      "/v1/identity/role-profiles/" + encodeURIComponent(profileId) + "/ledger",
      { method: "GET", headers: headers() }
    );
  }

  async function submitKyc(profileId, payload) {
    return jsonPost(
      "/v1/identity/role-profiles/" + encodeURIComponent(profileId) + "/kyc",
      { kyc_payload: payload }
    );
  }

  async function verifyKyc(profileId, decision) {
    return jsonPost(
      "/v1/identity/role-profiles/" + encodeURIComponent(profileId) + "/kyc/verify",
      { decision: decision }
    );
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

  async function listOnboardingIndustries() {
    return karmaFetch("/v1/standards/onboarding/industries", {
      method: "GET",
      headers: { Accept: "application/json" },
    });
  }

  async function getOnboardingIndustry(industryId) {
    return karmaFetch("/v1/standards/onboarding/industries/" + encodeURIComponent(industryId), {
      method: "GET",
      headers: { Accept: "application/json" },
    });
  }

  /** Agents owned by the authenticated identity card (P1 readiness included). */
  async function listMyAgents() {
    return karmaFetch("/v1/agents/mine", { method: "GET", headers: headers() });
  }

  /** Owner-console connect: Karma custody-holds the agent key server-side. */
  async function ownerConnect(payload) {
    return jsonPost("/v1/agents/owner-connect", payload);
  }

  async function ownerRevokeAgent(agentId) {
    return jsonPost("/v1/agents/owner-revoke", { agent_id: agentId });
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

  /*
   * Lock / release act on the master capacity row only.
   *
   * POST /v1/capacity/{id}/lock and /release accept an optional profile_id, but
   * the server only uses it to *stamp* the master row (see api/routes/capacity.py):
   * the credits still come from and return to the master pool, and per-profile
   * allocations move with PUT /allocations. Sending a sub-identity id here bought
   * nothing and quietly branded the master ledger row with a sub-identity, so the
   * console never sends one. Release is refused client-side while a sub-identity
   * scope is active.
   */
  async function lockCapacity(identityId, amount) {
    const id = encodeURIComponent(identityId);
    return jsonPost("/v1/capacity/" + id + "/lock", { amount: Number(amount) });
  }

  async function releaseCapacity(identityId, amount) {
    const id = encodeURIComponent(identityId);
    return jsonPost("/v1/capacity/" + id + "/release", { amount: Number(amount) });
  }

  /*
   * Real on-chain deposits.
   *
   * The wallet signs `approve` + `lock` itself and the server only verifies the
   * receipt, so no key ever reaches Karma. `claimBill` credits the ledger from
   * the on-chain BillMinted event and is idempotent per transaction.
   */
  async function getChainLockState(identityId) {
    const id = encodeURIComponent(identityId);
    return karmaFetch("/v1/capacity/" + id + "/chain", { method: "GET", headers: headers() });
  }

  async function claimBill(identityId, txHash) {
    const id = encodeURIComponent(identityId);
    return jsonPost("/v1/capacity/" + id + "/claim-bill", { tx_hash: String(txHash) });
  }

  async function claimUnlock(identityId, billId, txHash) {
    const id = encodeURIComponent(identityId);
    return jsonPost("/v1/capacity/" + id + "/claim-unlock", {
      bill_id: String(billId),
      tx_hash: String(txHash),
    });
  }

  /*
   * v2 allowance escrow — the money never leaves the user's wallet.
   *
   * The wallet signs `approve` + `commit` once; the server verifies the receipt
   * and records the commitment. Everything after that (binding an order,
   * submitting a proof, pulling the payment) is Karma's rules running on top of
   * that allowance, and the payer can revoke it at any time with one more
   * signature of their own.
   */
  async function getEscrowState(identityId) {
    const id = encodeURIComponent(identityId);
    return karmaFetch("/v1/escrow/" + id, { method: "GET", headers: headers() });
  }

  async function claimCommit(identityId, txHash) {
    const id = encodeURIComponent(identityId);
    return jsonPost("/v1/escrow/" + id + "/claim-commit", { tx_hash: String(txHash) });
  }

  async function claimEscrowRevoke(identityId, billId, txHash) {
    const id = encodeURIComponent(identityId);
    return jsonPost("/v1/escrow/" + id + "/claim-revoke", {
      bill_id: String(billId),
      tx_hash: String(txHash),
    });
  }

  async function syncEscrow(identityId) {
    const id = encodeURIComponent(identityId);
    return jsonPost("/v1/escrow/" + id + "/sync", {});
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

  async function acceptPaymentCode(voucherId, sellerIdentityId, sellerProfileId) {
    var body = { seller_identity_id: sellerIdentityId };
    // 可选：这一单算到哪个子身份账上（收付中心按它拆收入）。
    if (sellerProfileId) body.seller_profile_id = sellerProfileId;
    return jsonPost("/v1/payment-codes/" + encodeURIComponent(voucherId) + "/accept", body);
  }

  /** 收付中心台账：总览 / 收入明细 / 支出明细 / 确认区 / 争议区 一次拿全。 */
  async function getPaymentLedger(params) {
    var p = params || {};
    var q = new URLSearchParams();
    ["identity_id", "profile_id", "direction", "kind", "status"].forEach(function (k) {
      if (p[k]) q.set(k, String(p[k]));
    });
    if (p.limit) q.set("limit", String(p.limit));
    if (p.offset) q.set("offset", String(p.offset));
    var qs = q.toString();
    return karmaFetch("/v1/payments/ledger" + (qs ? "?" + qs : ""), {
      method: "GET",
      headers: headers(),
    });
  }

  /** 单笔详情（含状态流转 / 事件历史）。 */
  async function getPaymentEntry(kind, refId, identityId) {
    var q = identityId ? "?" + new URLSearchParams({ identity_id: identityId }).toString() : "";
    return karmaFetch(
      "/v1/payments/entries/" + encodeURIComponent(kind) + "/" + encodeURIComponent(refId) + q,
      { method: "GET", headers: headers() }
    );
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

  async function tradeLaunchSigningPreview(body, idempotencyKey) {
    const extra = idempotencyKey ? { "Idempotency-Key": idempotencyKey } : null;
    return jsonPost("/v1/trade/orders/launch/signing-preview", body, extra);
  }

  global.cyberKarmaApi = {
    apiBase,
    karmaFetch,
    headers,
    getCapacity,
    getAllocations,
    setAllocations,
    getSettlement,
    getHealth,
    getV1Info,
    getContract,
    listReceiptsForTask,
    listProgressForTask,
    getBundleForTask,
    listSettlementTransitions,
    listAgents,
    listMyAgents,
    listOnboardingIndustries,
    getOnboardingIndustry,
    ownerConnect,
    ownerRevokeAgent,
    listRoleProfiles,
    getRoleProfile,
    createRoleProfile,
    getIdentityCard,
    grantDisclosure,
    listDisclosures,
    revokeDisclosure,
    getProfileLedger,
    submitKyc,
    verifyKyc,
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
    getChainLockState,
    claimBill,
    claimUnlock,
    getEscrowState,
    claimCommit,
    claimEscrowRevoke,
    syncEscrow,
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
    getPaymentLedger,
    getPaymentEntry,
    launchTradeOrder,
    tradeLaunchSigningPreview,
    jsonPost,
    jsonPut,
    activeProfileId,
  };
  global.karmaRuntimeApi = { runtimeCreateKey, runtimeListKeys, runtimeRevokeKey, karmaFetch, headers };
})(window);
