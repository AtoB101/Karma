const KEY = "karma_studio_state_v2";

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
    return {
      ...clone(defaultState),
      ...parsed,
      agents: Array.isArray(parsed.agents) ? parsed.agents : clone(defaultState.agents),
      allowances: Array.isArray(parsed.allowances) ? parsed.allowances : clone(defaultState.allowances),
      bills: Array.isArray(parsed.bills) ? parsed.bills : clone(defaultState.bills),
      pushConfig: { ...defaultState.pushConfig, ...(parsed.pushConfig || {}) },
    };
  } catch {
    return clone(defaultState);
  }
}

export function saveState(state) {
  localStorage.setItem(KEY, JSON.stringify(state));
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

