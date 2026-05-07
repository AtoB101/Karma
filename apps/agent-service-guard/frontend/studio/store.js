const KEY = "karma_studio_state_v2";
const MAX_STATE_BYTES = 300_000;
const MAX_LIST = 200;

const defaultUnified = {
  lockSummary: {
    buyerLocked: 12400,
    mandatoryMinBond: 3720,
    sellerVoluntaryExcess: 2000,
    reducibleExcess: 2000,
    settleable: 1240,
    currency: "USDT",
  },
  stats: {
    todayIncome: 680,
    pendingSettlement: 1240,
    minBond: 3720,
    excessLock: 2000,
    trustLevel: "A+",
    disputeFrozen: 600,
  },
  services: [
    {
      service_id: "svc_ai_data",
      service_name: "AI Data API",
      service_type: "agent_api",
      description: "数据查询 / API 调用",
      price: 5,
      currency: "USDC",
      seller_bond_rate: 0.3,
      status: "running",
      created_at: new Date().toISOString(),
      _mock_calls_today: 286,
      _mock_success_pct: 98.6,
      _mock_pending_usd: 840,
      _mock_anomaly: 1,
    },
  ],
  orders: [
    {
      order_id: "KMA-2048",
      service_id: "svc_ai_data",
      service_name: "AI Data API 服务",
      price: 500,
      currency: "USDC",
      buyer_wallet: "",
      seller_wallet: "",
      seller_bond_amount: 150,
      payment_status: "MOCK_LOCKED",
      delivery_status: "PENDING",
      dispute_status: "NONE",
      settlement_status: "UNSETTLED",
      seller_bond_status: "MOCK_LOCKED",
      _excess_lock: 50,
      _trust_grade: "A+",
      _reducible: 50,
    },
    {
      order_id: "KMA-1188",
      service_name: "AI 视频广告生成",
      price: 300,
      currency: "USDT",
      seller_bond_amount: 90,
      payment_status: "MOCK_LOCKED",
      delivery_status: "DELIVERED",
      dispute_status: "OPEN",
      settlement_status: "FROZEN",
      seller_bond_status: "FROZEN",
      _excess_lock: 0,
      _responsible_party: "卖家",
      _dispute_phase: "等待补证",
    },
  ],
  todos: [
    {
      id: "t1",
      title: "可减少 $2,000 超额锁仓",
      detail: "这部分不是强制责任金，减少后不会影响现有订单最低保障。",
    },
    {
      id: "t2",
      title: "AI 视频订单责任金冻结",
      detail: "订单 #KMA-1188 进入争议，最低责任金 $90 暂时冻结。",
    },
    {
      id: "t3",
      title: "3 笔订单等待买家确认",
      detail: "如果买家超时未争议，系统将自动释放资金和责任金。",
    },
  ],
  evidence: [
    {
      evidence_id: "ev_1",
      order_id: "KMA-2048",
      input_summary: "Request Hash 已生成",
      output_summary: "Response Hash 已生成",
      execution_status: "ok",
      evidence_hash: "0x…mock",
    },
    {
      evidence_id: "ev_2",
      order_id: "KMA-2048",
      input_summary: "Execution Log 已保存",
      output_summary: "执行时间、状态、错误原因已保存",
      execution_status: "ok",
      evidence_hash: "0x…mock2",
    },
  ],
  riskAlerts: [
    { id: "r1", risk_level: "MEDIUM", title: "高频调用：中风险", detail: "同一买家短时间重复调用。" },
    { id: "r2", risk_level: "HIGH", title: "重复争议买家：高风险", detail: "历史争议率偏高，需要更严格证据。" },
    { id: "r3", risk_level: "LOW", title: "服务失败率：正常", detail: "最近 24 小时服务稳定。" },
  ],
  sellerStats: {
    seller_wallet: "",
    active_bond_amount: 3720,
    total_bond_locked: 5720,
    success_rate: 0.986,
    dispute_rate: 0.02,
  },
  trustBadge: {
    band: "A+",
    min_guarantee_pct: 30,
    extra_guarantee_pct: 16,
    narrative: "你在最低责任金之外额外锁定 $2,000，买家看到的是“高保障卖家”。",
  },
  sellerScore: null,
  syncMeta: {
    lastSyncAt: null,
    lastSource: "local",
    lastError: null,
    sellerWallet: null,
  },
};

const defaultState = {
  agents: [
    { id: "agent_1", name: "合约风险检测 Agent", price: 0.03, trust: 92, totalCalls: 412 },
    { id: "agent_2", name: "Smart Money Tracker", price: 0.08, trust: 78, totalCalls: 1523 },
  ],
  allowances: [
    { agentId: "agent_1", agentName: "合约风险检测 Agent", perTxLimit: 0.1, dailyLimit: 2, totalAssigned: 100, usedThisMonth: 23.5 },
    { agentId: "agent_2", agentName: "Smart Money Tracker", perTxLimit: 0.5, dailyLimit: 10, totalAssigned: 200, usedThisMonth: 88.2 },
  ],
  bills: [
    { id: "BILL-001", caller: "数据分析 Agent", receiver: "钱包画像 Agent", amount: 0.08, status: "已付款" },
    { id: "BILL-002", caller: "交易助手 Agent", receiver: "信号 Agent", amount: 0.15, status: "争议中" },
  ],
  pushConfig: { channel: "whatsapp", provider: "pushplus", destination: "" },
  unified: clone(defaultUnified),
};

function clone(x) {
  return JSON.parse(JSON.stringify(x));
}

function migrateUnified(parsed, base) {
  const u = parsed.unified && typeof parsed.unified === "object"
    ? { ...clone(defaultUnified), ...parsed.unified }
    : clone(defaultUnified);

  if ((!u.services || !u.services.length) && Array.isArray(parsed.agents) && parsed.agents.length) {
    u.services = parsed.agents.slice(0, MAX_LIST).map((a) => ({
      service_id: a.id,
      service_name: a.name,
      service_type: "agent_api",
      description: "",
      price: a.price,
      currency: "USDC",
      seller_bond_rate: 0.3,
      status: "running",
      _mock_calls_today: a.totalCalls || 0,
      _mock_success_pct: 98,
      _mock_pending_usd: 0,
      _mock_anomaly: 0,
    }));
  }

  if ((!u.orders || !u.orders.length) && Array.isArray(parsed.bills) && parsed.bills.length) {
    u.orders = parsed.bills.slice(0, MAX_LIST).map((b) => ({
      order_id: b.id,
      service_name: "Legacy bill",
      price: b.amount,
      currency: "USDC",
      payment_status: "MOCK_LOCKED",
      delivery_status: "PENDING",
      dispute_status: String(b.status || "").includes("争议") ? "OPEN" : "NONE",
      settlement_status: "UNSETTLED",
      seller_bond_status: "MOCK_LOCKED",
    }));
  }

  ["services", "orders", "todos", "evidence", "riskAlerts"].forEach((k) => {
    if (Array.isArray(u[k])) u[k] = u[k].slice(0, MAX_LIST);
  });
  return u;
}

export function loadState() {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return clone(defaultState);
    const parsed = JSON.parse(raw);
    const agents = Array.isArray(parsed.agents)
      ? parsed.agents.slice(0, MAX_LIST)
      : clone(defaultState.agents);
    const allowances = Array.isArray(parsed.allowances)
      ? parsed.allowances.slice(0, MAX_LIST)
      : clone(defaultState.allowances);
    const bills = Array.isArray(parsed.bills) ? parsed.bills.slice(0, MAX_LIST) : clone(defaultState.bills);
    const unified = migrateUnified(parsed, defaultState);
    return {
      ...clone(defaultState),
      ...parsed,
      agents,
      allowances,
      bills,
      unified,
      pushConfig: { ...defaultState.pushConfig, ...(parsed.pushConfig || {}) },
    };
  } catch {
    return clone(defaultState);
  }
}

export function saveState(state) {
  const raw = JSON.stringify(state);
  if (typeof Blob !== "undefined" && new Blob([raw]).size > MAX_STATE_BYTES) {
    return;
  }
  localStorage.setItem(KEY, raw);
}

export function escapeHtml(input) {
  return String(input ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function safeText(input, max = 64) {
  return String(input ?? "")
    .trim()
    .replace(/[^\u4e00-\u9fa5\w\s\-./]/g, "")
    .slice(0, max);
}

export function createAgent(state, payload) {
  const id = `agent_${Date.now()}`;
  const name = safeText(payload.name, 40) || "New Agent";
  const price = Number(payload.price || 0);
  const next = {
    id,
    name,
    price: Number.isFinite(price) && price > 0 ? Number(price.toFixed(2)) : 0.01,
    trust: 75,
    totalCalls: 0,
    shareLink: new URL("../index.html", location.href).href + "?agent=" + encodeURIComponent(id),
  };
  state.agents.unshift(next);
  state.allowances.unshift({
    agentId: id,
    agentName: name,
    perTxLimit: Math.max(0.01, Number(next.price)),
    dailyLimit: Math.max(1, Number((next.price * 20).toFixed(2))),
    totalAssigned: 0,
    usedThisMonth: 0,
  });
  state.unified.services.unshift({
    service_id: id,
    service_name: name,
    service_type: "agent_api",
    description: "",
    price: next.price,
    currency: "USDC",
    seller_bond_rate: 0.3,
    status: "running",
    _mock_calls_today: 0,
    _mock_success_pct: 100,
    _mock_pending_usd: 0,
    _mock_anomaly: 0,
  });
}

export function updateAllowance(state, agentId, key, value) {
  const item = state.allowances.find((a) => a.agentId === agentId);
  if (!item) return;
  if (!["perTxLimit", "dailyLimit"].includes(key)) return;
  const next = Number(value || 0);
  if (!Number.isFinite(next) || next < 0) return;
  item[key] = Number(next.toFixed(2));
}

export function updatePushConfig(state, payload) {
  const channel = safeText(payload.channel || state.pushConfig.channel, 16).toLowerCase();
  const destination = safeText(payload.destination || "", 64);
  state.pushConfig = {
    ...state.pushConfig,
    channel: channel || "whatsapp",
    destination,
  };
}

/** @param {number} delta — adjust voluntary excess lock (local demo) */
export function adjustVoluntaryLock(state, delta) {
  const ls = state.unified.lockSummary;
  const d = Number(delta);
  if (!Number.isFinite(d)) return false;
  const next = ls.sellerVoluntaryExcess + d;
  if (next < 0) return false;
  ls.sellerVoluntaryExcess = next;
  ls.reducibleExcess = Math.max(0, next);
  state.unified.stats.excessLock = next;
  state.unified.stats.minBond = ls.mandatoryMinBond;
  return true;
}
