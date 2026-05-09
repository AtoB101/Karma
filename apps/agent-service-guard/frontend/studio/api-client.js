/**
 * Public API client — paths match apps/agent-service-guard/api/README.md.
 * Reserved engine endpoints: POST /risk/check, /dispute/recommend-resolution, /score/seller
 *
 * Security defaults:
 * - Relative URLs only unless `KARMAPAY_STUDIO_API_ORIGIN_ALLOWLIST` includes the API origin.
 * - `credentials: "same-origin"` so cookies are never sent to cross-origin APIs by mistake.
 * - Basic 429 backoff (server should still enforce rate limits; see infra/nginx examples).
 */

function apiBase() {
  const b = typeof window !== "undefined" && window.KARMAPAY_STUDIO_API_BASE != null
    ? String(window.KARMAPAY_STUDIO_API_BASE)
    : "";
  return b.replace(/\/$/, "");
}

function apiOriginAllowlist() {
  if (typeof window === "undefined") return [];
  const v = window.KARMAPAY_STUDIO_API_ORIGIN_ALLOWLIST;
  if (typeof v === "string") {
    return v.split(",").map((s) => s.trim()).filter(Boolean);
  }
  return Array.isArray(v) ? v.filter((x) => typeof x === "string" && x.trim()) : [];
}

/** @returns {string | null} blocked origin label, or null if allowed */
function crossOriginApiBlocked(base) {
  if (typeof window === "undefined" || !base) return null;
  try {
    const u = new URL(base, window.location.href);
    if (u.origin === window.location.origin) return null;
    const list = apiOriginAllowlist();
    if (list.includes(u.origin)) return null;
    return u.origin;
  } catch {
    return "invalid_api_base_url";
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function fetchJson(path, options = {}) {
  const base = apiBase();
  const blocked = crossOriginApiBlocked(base);
  if (blocked) {
    return {
      ok: false,
      status: 0,
      body: { error: "studio_api_cross_origin_blocked", detail: String(blocked) },
    };
  }

  const url = `${base}${path.startsWith("/") ? path : "/" + path}`;
  const { headers = {}, ...rest } = options;
  const maxAttempts = 3;
  let lastRes = null;
  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    lastRes = await fetch(url, {
      ...rest,
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        ...headers,
      },
    });
    if (lastRes.status === 429 && attempt < maxAttempts) {
      const ra = lastRes.headers.get("Retry-After");
      const sec = ra ? parseInt(ra, 10) : NaN;
      const backoff = Number.isFinite(sec) && sec > 0 ? Math.min(sec * 1000, 15000) : 300 * attempt;
      await sleep(backoff);
      continue;
    }
    break;
  }
  const res = lastRes;
  const text = await res.text();
  let body = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = { raw: text };
    }
  }
  return { ok: res.ok, status: res.status, body };
}

function walletHeaders(wallet) {
  return wallet ? { "X-Wallet-Address": wallet, "X-Seller-Wallet": wallet } : {};
}

/** @param {string} [sellerWallet] */
export async function getDashboardStats(sellerWallet) {
  const q = sellerWallet ? `?seller_wallet=${encodeURIComponent(sellerWallet)}` : "";
  return fetchJson(`/dashboard/stats${q}`, { headers: walletHeaders(sellerWallet) });
}

export async function listServices(sellerWallet) {
  const q = sellerWallet ? `?seller_wallet=${encodeURIComponent(sellerWallet)}` : "";
  return fetchJson(`/services${q}`, { headers: walletHeaders(sellerWallet) });
}

export async function getService(serviceId) {
  return fetchJson(`/services/${encodeURIComponent(serviceId)}`);
}

export async function createService(payload, sellerWallet) {
  return fetchJson(`/services`, {
    method: "POST",
    headers: walletHeaders(sellerWallet),
    body: JSON.stringify(payload),
  });
}

export async function listOrders(sellerWallet) {
  const q = sellerWallet ? `?seller_wallet=${encodeURIComponent(sellerWallet)}` : "";
  return fetchJson(`/orders${q}`, { headers: walletHeaders(sellerWallet) });
}

export async function getOrder(orderId) {
  return fetchJson(`/orders/${encodeURIComponent(orderId)}`);
}

export async function createOrder(payload, buyerWallet) {
  return fetchJson(`/orders`, {
    method: "POST",
    headers: buyerWallet ? { "X-Buyer-Wallet": buyerWallet } : {},
    body: JSON.stringify(payload),
  });
}

export async function postDeliver(orderId, payload, sellerWallet) {
  return fetchJson(`/orders/${encodeURIComponent(orderId)}/deliver`, {
    method: "POST",
    headers: walletHeaders(sellerWallet),
    body: JSON.stringify(payload || {}),
  });
}

export async function postConfirm(orderId, buyerWallet) {
  return fetchJson(`/orders/${encodeURIComponent(orderId)}/confirm`, {
    method: "POST",
    headers: buyerWallet ? { "X-Buyer-Wallet": buyerWallet } : {},
    body: JSON.stringify({}),
  });
}

export async function postDispute(orderId, payload, buyerWallet) {
  return fetchJson(`/orders/${encodeURIComponent(orderId)}/dispute`, {
    method: "POST",
    headers: buyerWallet ? { "X-Buyer-Wallet": buyerWallet } : {},
    body: JSON.stringify(payload || {}),
  });
}

export async function postArbitrate(orderId, payload) {
  return fetchJson(`/orders/${encodeURIComponent(orderId)}/arbitrate`, {
    method: "POST",
    body: JSON.stringify(payload || {}),
  });
}

export async function getTrustBadge(sellerWallet) {
  return fetchJson(`/badge/${encodeURIComponent(sellerWallet)}`, { headers: walletHeaders(sellerWallet) });
}

export async function postRiskCheck(payload) {
  return fetchJson(`/risk/check`, { method: "POST", body: JSON.stringify(payload) });
}

export async function postDisputeRecommend(payload) {
  return fetchJson(`/dispute/recommend-resolution`, { method: "POST", body: JSON.stringify(payload) });
}

export async function postScoreSeller(payload) {
  return fetchJson(`/score/seller`, { method: "POST", body: JSON.stringify(payload) });
}
