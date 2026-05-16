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
  };
  global.karmaRuntimeApi = { runtimeCreateKey, runtimeListKeys, runtimeRevokeKey, karmaFetch, headers };
})(window);
