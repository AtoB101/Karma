/**
 * Pull remote state into local unified store; DATA_CONTRACT-aligned merge.
 */
import * as api from "./api-client.js";
import { saveState } from "./store.js?v=20260507a";

function pick(obj, keys) {
  const o = {};
  keys.forEach((k) => {
    if (obj && obj[k] !== undefined) o[k] = obj[k];
  });
  return o;
}

/** Normalize API list responses */
function asArray(x) {
  if (Array.isArray(x)) return x;
  if (x && Array.isArray(x.items)) return x.items;
  if (x && Array.isArray(x.data)) return x.data;
  return [];
}

/**
 * @param {object} state — full store from store.js
 * @param {string} sellerWallet
 * @returns {Promise<{ source: string, error?: string }>}
 */
export async function syncUnifiedState(state, sellerWallet) {
  const meta = state.unified.syncMeta || {};
  let source = "local";
  let error = "";

  try {
    const dash = await api.getDashboardStats(sellerWallet);
    if (dash.ok && dash.body && typeof dash.body === "object") {
      const b = dash.body;
      if (b.lock_summary || b.lockSummary) {
        state.unified.lockSummary = { ...state.unified.lockSummary, ...(b.lock_summary || b.lockSummary) };
      }
      if (b.stats || b.dashboard_stats) {
        state.unified.stats = { ...state.unified.stats, ...(b.stats || b.dashboard_stats) };
      }
      if (b.todos) state.unified.todos = asArray(b.todos).slice(0, 200);
      if (b.evidence || b.evidence_bundles) {
        state.unified.evidence = asArray(b.evidence || b.evidence_bundles).slice(0, 200);
      }
      if (b.risk_alerts || b.riskAlerts) {
        state.unified.riskAlerts = asArray(b.risk_alerts || b.riskAlerts).slice(0, 200);
      }
      if (b.seller_stats || b.sellerStats) {
        state.unified.sellerStats = { ...state.unified.sellerStats, ...(b.seller_stats || b.sellerStats) };
      }
      source = "api";
    }

    const svc = await api.listServices(sellerWallet);
    if (svc.ok && svc.body) {
      const list = asArray(svc.body.services || svc.body).filter(Boolean);
      if (list.length) {
        state.unified.services = list.map((s) =>
          pick(s, [
            "service_id",
            "seller_wallet",
            "service_name",
            "service_type",
            "description",
            "price",
            "currency",
            "delivery_time",
            "refund_policy",
            "seller_bond_rate",
            "created_at",
            "status",
          ])
        );
        source = "api";
      }
    }

    const ord = await api.listOrders(sellerWallet);
    if (ord.ok && ord.body) {
      const list = asArray(ord.body.orders || ord.body).filter(Boolean);
      if (list.length) {
        state.unified.orders = list.map((o) =>
          pick(o, [
            "order_id",
            "service_id",
            "buyer_wallet",
            "seller_wallet",
            "service_name",
            "service_type",
            "price",
            "currency",
            "seller_bond_amount",
            "payment_status",
            "delivery_status",
            "dispute_status",
            "settlement_status",
            "seller_bond_status",
            "created_at",
            "updated_at",
          ])
        );
        source = "api";
      }
    }

    if (sellerWallet) {
      const badge = await api.getTrustBadge(sellerWallet);
      if (badge.ok && badge.body && typeof badge.body === "object") {
        state.unified.trustBadge = { ...state.unified.trustBadge, ...badge.body };
        source = "api";
      }

      const score = await api.postScoreSeller({ seller_wallet: sellerWallet, period_days: 30 });
      if (score.ok && score.body) {
        state.unified.sellerScore = score.body;
        source = "api";
      }
    }
  } catch (e) {
    error = e && e.message ? e.message : "sync_failed";
  }

  state.unified.syncMeta = {
    ...meta,
    lastSyncAt: new Date().toISOString(),
    lastSource: source,
    lastError: error || null,
    sellerWallet: sellerWallet || null,
  };
  saveState(state);
  return { source, error: error || undefined };
}
