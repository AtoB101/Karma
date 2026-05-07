const KEY = "karma_studio_state_v2";
const MAX_STATE_BYTES = 300_000;
const MAX_LIST = 200;

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
};

function clone(x) {
  return JSON.parse(JSON.stringify(x));
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
    return {
      ...clone(defaultState),
      ...parsed,
      agents,
      allowances,
      bills,
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

