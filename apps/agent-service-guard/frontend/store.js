const STORAGE_KEY = "karma_guard_mock_v1";

function nowIso() {
  return new Date().toISOString();
}

function uid(prefix) {
  return `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

function hashFrom(text) {
  let h = 2166136261;
  for (let i = 0; i < text.length; i += 1) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return `0x${(h >>> 0).toString(16).padStart(8, "0")}${Math.floor(Math.random() * 1e8).toString(16).padStart(8, "0")}`;
}

function readDb() {
  const raw = localStorage.getItem(STORAGE_KEY);
  if (!raw) {
    return { services: [], orders: [], evidence: [], disputes: [] };
  }
  try {
    return JSON.parse(raw);
  } catch (_err) {
    return { services: [], orders: [], evidence: [], disputes: [] };
  }
}

function writeDb(db) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(db));
}

export function listServices() {
  return readDb().services;
}

export function getService(serviceId) {
  return readDb().services.find((s) => s.service_id === serviceId) || null;
}

export const getServiceById = getService;

export function createService(input) {
  const db = readDb();
  const service = {
    service_id: uid("svc"),
    seller_wallet: input.seller_wallet,
    service_name: input.service_name,
    service_type: input.service_type,
    description: input.description,
    price: Number(input.price),
    currency: input.currency || "USDC",
    delivery_time: input.delivery_time,
    refund_policy: input.refund_policy,
    seller_bond_rate: Number(input.seller_bond_rate || 30),
    created_at: nowIso(),
    status: "ACTIVE",
  };
  service.payment_link = `/pay/${service.service_id}`;
  db.services.unshift(service);
  writeDb(db);
  return service;
}

export function createOrder(serviceOrId, buyerWallet) {
  const db = readDb();
  const serviceId = typeof serviceOrId === "string" ? serviceOrId : serviceOrId?.service_id;
  const service = db.services.find((s) => s.service_id === serviceId);
  if (!service) throw new Error("Service not found");
  const sellerBondAmount = Number(((service.price * service.seller_bond_rate) / 100).toFixed(2));
  const order = {
    order_id: uid("ord"),
    service_id: service.service_id,
    buyer_wallet: buyerWallet,
    seller_wallet: service.seller_wallet,
    service_name: service.service_name,
    service_type: service.service_type,
    price: service.price,
    currency: service.currency,
    seller_bond_amount: sellerBondAmount,
    payment_status: "MOCK_LOCKED",
    delivery_status: "PENDING",
    dispute_status: "NONE",
    settlement_status: "UNSETTLED",
    seller_bond_status: "MOCK_LOCKED",
    evidence_hash: "",
    created_at: nowIso(),
    updated_at: nowIso(),
  };
  db.orders.unshift(order);
  writeDb(db);
  return order;
}

export function getOrder(orderId) {
  return readDb().orders.find((o) => o.order_id === orderId) || null;
}

export function updateOrderById(orderId, patch) {
  const db = readDb();
  const order = db.orders.find((o) => o.order_id === orderId);
  if (!order) return null;
  Object.assign(order, patch || {}, { updated_at: nowIso() });
  writeDb(db);
  return order;
}

export function listOrders() {
  return readDb().orders;
}

export function submitDelivery(orderId, inputSummary, outputSummary) {
  const db = readDb();
  const order = db.orders.find((o) => o.order_id === orderId);
  if (!order) throw new Error("Order not found");
  const evidenceHash = hashFrom(`${orderId}|${inputSummary}|${outputSummary}|${Date.now()}`);
  const evidence = {
    evidence_id: uid("evd"),
    order_id: order.order_id,
    buyer_wallet: order.buyer_wallet,
    seller_wallet: order.seller_wallet,
    service_type: order.service_type,
    price: order.price,
    currency: order.currency,
    input_summary: inputSummary,
    output_summary: outputSummary,
    output_hash: hashFrom(outputSummary),
    execution_status: "DELIVERED",
    failure_reason: "",
    started_at: order.created_at,
    completed_at: nowIso(),
    buyer_signature: "",
    seller_signature: "MOCK_SELLER_SIG",
    evidence_hash: evidenceHash,
    settlement_status: order.settlement_status,
    dispute_status: order.dispute_status,
    created_at: nowIso(),
  };
  db.evidence.unshift(evidence);
  order.delivery_status = "DELIVERED";
  order.evidence_hash = evidenceHash;
  order.updated_at = nowIso();
  writeDb(db);
  return { order, evidence };
}

export function buyerConfirm(orderId) {
  const db = readDb();
  const order = db.orders.find((o) => o.order_id === orderId);
  if (!order) throw new Error("Order not found");
  order.delivery_status = "CONFIRMED";
  order.payment_status = "RELEASED";
  order.seller_bond_status = "RELEASED";
  order.settlement_status = "SETTLED";
  order.updated_at = nowIso();
  writeDb(db);
  return order;
}

export function openDispute(orderId, reasonText) {
  const db = readDb();
  const order = db.orders.find((o) => o.order_id === orderId);
  if (!order) throw new Error("Order not found");
  const dispute = {
    dispute_id: uid("dsp"),
    order_id: order.order_id,
    opened_by: "BUYER",
    reason_code: "QUALITY_DISPUTE",
    reason_text: reasonText || "Buyer requested dispute review",
    evidence_hash: order.evidence_hash || "",
    status: "OPEN",
    resolution: "",
    refund_amount: 0,
    seller_penalty_amount: 0,
    created_at: nowIso(),
    resolved_at: "",
  };
  db.disputes.unshift(dispute);
  order.dispute_status = "OPEN";
  order.settlement_status = "FROZEN";
  order.seller_bond_status = "FROZEN";
  order.updated_at = nowIso();
  writeDb(db);
  return { order, dispute };
}

export function resolveDispute(orderId, decision) {
  const db = readDb();
  const order = db.orders.find((o) => o.order_id === orderId);
  if (!order) throw new Error("Order not found");
  const dispute = db.disputes.find((d) => d.order_id === orderId && d.status === "OPEN");
  if (!dispute) throw new Error("No open dispute");

  dispute.status = "RESOLVED";
  dispute.resolution = decision;
  dispute.resolved_at = nowIso();

  if (decision === "BUYER_WINS") {
    order.payment_status = "REFUNDED";
    order.settlement_status = "REFUNDED";
    order.seller_bond_status = "SLASHED";
    dispute.refund_amount = order.price;
    dispute.seller_penalty_amount = order.seller_bond_amount;
  } else if (decision === "SELLER_WINS") {
    order.payment_status = "RELEASED";
    order.settlement_status = "SETTLED";
    order.seller_bond_status = "RELEASED";
  } else {
    order.payment_status = "PARTIAL_RELEASED";
    order.settlement_status = "PARTIALLY_SETTLED";
    order.seller_bond_status = "PARTIAL_RELEASED";
    dispute.refund_amount = Number((order.price * 0.5).toFixed(2));
    dispute.seller_penalty_amount = Number((order.seller_bond_amount * 0.5).toFixed(2));
  }

  order.dispute_status = "RESOLVED";
  order.updated_at = nowIso();
  writeDb(db);
  return { order, dispute };
}

export function getSellerStats(wallet) {
  const db = readDb();
  const orders = db.orders.filter((o) => o.seller_wallet === wallet);
  const totalVolume = orders.reduce((sum, o) => sum + Number(o.price), 0);
  const verified = orders.filter((o) => o.delivery_status === "CONFIRMED").length;
  const settled = orders.filter((o) => o.settlement_status === "SETTLED").length;
  const disputed = orders.filter((o) => o.dispute_status === "OPEN" || o.dispute_status === "RESOLVED").length;
  const refunded = orders.filter((o) => o.settlement_status === "REFUNDED").length;
  const activeBond = orders
    .filter((o) => o.seller_bond_status === "MOCK_LOCKED" || o.seller_bond_status === "LOCKED" || o.seller_bond_status === "FROZEN")
    .reduce((sum, o) => sum + Number(o.seller_bond_amount), 0);
  const totalBond = orders.reduce((sum, o) => sum + Number(o.seller_bond_amount), 0);
  const successRate = orders.length ? Number(((settled / orders.length) * 100).toFixed(2)) : 0;
  const disputeRate = orders.length ? Number(((disputed / orders.length) * 100).toFixed(2)) : 0;
  const avgSettleTime = orders.length ? "mock-<24h" : "n/a";
  return {
    seller_wallet: wallet,
    total_protected_volume: Number(totalVolume.toFixed(2)),
    verified_orders: verified,
    settled_orders: settled,
    disputed_orders: disputed,
    refunded_orders: refunded,
    success_rate: successRate,
    dispute_rate: disputeRate,
    active_bond_amount: Number(activeBond.toFixed(2)),
    total_bond_locked: Number(totalBond.toFixed(2)),
    average_settlement_time: avgSettleTime,
  };
}

export function getDashboardStats() {
  const orders = listOrders();
  const totalProtectedVolume = orders.reduce((sum, o) => sum + Number(o.price), 0);
  const verifiedOrders = orders.filter((o) => o.delivery_status === "CONFIRMED").length;
  const settledOrders = orders.filter((o) => o.settlement_status === "SETTLED").length;
  const disputedOrders = orders.filter((o) => o.dispute_status === "OPEN" || o.dispute_status === "RESOLVED").length;
  const refundedOrders = orders.filter((o) => o.settlement_status === "REFUNDED").length;
  const activeSellerBond = orders
    .filter((o) => o.seller_bond_status === "MOCK_LOCKED" || o.seller_bond_status === "LOCKED" || o.seller_bond_status === "FROZEN")
    .reduce((sum, o) => sum + Number(o.seller_bond_amount), 0);
  return {
    total_protected_volume: Number(totalProtectedVolume.toFixed(2)),
    verified_orders: verifiedOrders,
    settled_orders: settledOrders,
    disputed_orders: disputedOrders,
    refunded_orders: refundedOrders,
    active_seller_bond: Number(activeSellerBond.toFixed(2)),
    average_settlement_time: orders.length ? "mock-<24h" : "n/a",
    seller_success_rate: orders.length ? Number(((settledOrders / orders.length) * 100).toFixed(2)) : 0,
    dispute_rate: orders.length ? Number(((disputedOrders / orders.length) * 100).toFixed(2)) : 0,
  };
}

export const computeDashboardStats = getDashboardStats;

export function formatUsd(value) {
  return `$${Number(value || 0).toFixed(2)}`;
}

export function formatCurrency(value, currency = "USDC") {
  return `${Number(value || 0).toFixed(2)} ${currency}`;
}

export function nowTs() {
  return Date.now();
}

export function generateEvidenceHash(input) {
  return hashFrom(String(input || ""));
}

export function generateEvidenceHash(input) {
  return hashFrom(String(input || ""));
}

export { nowIso };
