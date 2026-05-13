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

  global.cyberKarmaApi = { apiBase, getCapacity, getSettlement };
})(window);
