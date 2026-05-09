/**
 * Public API client — paths match apps/agent-service-guard/api/README.md.
 * Reserved engine endpoints: POST /risk/check, /dispute/recommend-resolution, /score/seller
 */

function apiBase() {
  const b = typeof window !== "undefined" && window.KARMAPAY_STUDIO_API_BASE != null
    ? String(window.KARMAPAY_STUDIO_API_BASE)
    : "";
  return b.replace(/\/$/, "");
}

async function fetchJson(path, options = {}) {
  const url = `${apiBase()}${path.startsWith("/") ? path : "/" + path}`;
  const { headers = {}, ...rest } = options;
  const res = await fetch(url, {
    ...rest,
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      ...headers,
    },
  });
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
