const STORE_KEY = "trustchain_ui_p0_state_v1";
const DEMO_SCRIPT_KEY = "trustchain_ui_p0_demo_script_v1";
const DEMO_SCRIPT_STEPS = [
  { path: "/index.html", title: "入口总览", hint: "先介绍三步闭环目标：调用一次服务，自动结算一次费用。" },
  { path: "/buyer/authorize/", title: "买方授权", hint: "展示额度、单次上限、日限额，强调先授权后调用。" },
  { path: "/agent/confirm-call/", title: "Agent 调用确认", hint: "讲解调用原因、价格和确认动作，点“允许本次”生成待结算账单。" },
  { path: "/buyer/bills/", title: "买方账单", hint: "展示账单状态从 Pending 到 Settled/Disputed 的可追溯过程。" },
  { path: "/seller/create-service/", title: "卖方建服务", hint: "演示卖方如何配置服务与价格，并复制接入代码。" },
  { path: "/seller/revenue/", title: "卖方收入", hint: "展示收入看板与明细记录，证明收费闭环成立。" },
  { path: "/buyer/agent-activity/", title: "行为透明", hint: "收尾展示 Agent 行为时间线，强调可审计与可解释。" },
];

function buildSeedState() {
  return {
    buyer: {
      wallet: "0xA12...89F",
      token: "USDC",
      walletBalance: 100,
      allowance: 50,
      locked: 30,
      active: 24.5,
      reserved: 5.5,
      settled: 12.2,
      disputed: 0,
      perCallLimit: 0.05,
      dailyLimit: 5,
      autoConfirm: 0.01,
    },
    myAgents: [
      {
        id: "agent-001",
        name: "PriceHunter",
        description: "Any pair market price query",
        serviceType: "数据查询",
        endpoint: "https://api.binance.com/api/v3/ticker/price?symbol={SYMBOL}",
        price: 0.03,
        token: "USDC",
        wallet: "0xSELL...001",
        successOnly: true,
        refundable: true,
        manualConfirm: false,
        status: "running",
        todayCalls: 12,
        todayIncome: 0.36,
        totalIncome: 8.42,
      },
      {
        id: "agent-002",
        name: "RiskGuard",
        description: "Token risk check and warning",
        serviceType: "风险检测",
        endpoint: "https://risk.example.com/check",
        price: 0.05,
        token: "USDT",
        wallet: "0xSELL...002",
        successOnly: true,
        refundable: false,
        manualConfirm: true,
        status: "paused",
        todayCalls: 4,
        todayIncome: 0.2,
        totalIncome: 3.1,
      },
    ],
    services: [{ id: "svc-001", name: "Price API", price: 0.01, token: "USDC", status: "active" }],
    bills: [
      {
        id: "BILL-001",
        service: "ETHUSDT Price Query",
        seller: "PriceHunter",
        callerAgent: "PortfolioBot",
        amount: 0.01,
        status: "Paid",
        payStrategy: "now",
        createdAt: "2026-04-29 08:10",
      },
      {
        id: "BILL-002",
        service: "Risk Scan",
        seller: "RiskGuard",
        callerAgent: "TradingAgent",
        amount: 0.03,
        status: "PendingConfirm",
        payStrategy: "batch",
        createdAt: "2026-04-29 08:21",
      },
      {
        id: "BILL-003",
        service: "SOLUSDT Price Query",
        seller: "PriceHunter",
        callerAgent: "ArbAgent",
        amount: 0.02,
        status: "PendingSettle",
        payStrategy: "now",
        createdAt: "2026-04-29 08:34",
      },
      {
        id: "BILL-004",
        service: "Token Risk Audit",
        seller: "RiskGuard",
        callerAgent: "AlphaAgent",
        amount: 0.05,
        status: "Disputed",
        payStrategy: "batch",
        createdAt: "2026-04-29 08:40",
      },
    ],
    calls: [
      {
        time: "2026-04-29 08:21",
        agent: "Trading Agent",
        service: "Risk Scan",
        reason: "Token safety check",
        price: 0.03,
        status: "Waiting settle",
      },
    ],
    revenue: [{ time: "2026-04-29 08:10", buyer: "0xA12...89F", service: "Price API", amount: 0.01, status: "Settled" }],
  };
}

function initState() {
  const seed = buildSeedState();
  localStorage.setItem(STORE_KEY, JSON.stringify(seed));
  return seed;
}

function getState() {
  const raw = localStorage.getItem(STORE_KEY);
  if (!raw) return initState();
  try {
    return JSON.parse(raw);
  } catch {
    return initState();
  }
}

function saveState(state) {
  localStorage.setItem(STORE_KEY, JSON.stringify(state));
}

function resetDemoState() {
  return initState();
}

function maybeResetFromUrl() {
  if (typeof window === "undefined") return;
  const params = new URLSearchParams(window.location.search);
  if (params.get("demoReset") === "1") {
    resetDemoState();
  }
}

function fmt(n, token) {
  return `${Number(n).toFixed(2)} ${token}`;
}

function normalizePath(path) {
  if (!path) return "/index.html";
  return path.endsWith("/") ? path : path.replace(/\/index\.html$/, "/");
}

function getDemoScriptState() {
  if (typeof window === "undefined") return { active: false, stepIndex: 0 };
  const raw = window.sessionStorage.getItem(DEMO_SCRIPT_KEY);
  if (!raw) return { active: false, stepIndex: 0 };
  try {
    const parsed = JSON.parse(raw);
    return {
      active: !!parsed.active,
      stepIndex: Number.isInteger(parsed.stepIndex) ? parsed.stepIndex : 0,
    };
  } catch {
    return { active: false, stepIndex: 0 };
  }
}

function saveDemoScriptState(state) {
  if (typeof window === "undefined") return;
  window.sessionStorage.setItem(DEMO_SCRIPT_KEY, JSON.stringify(state));
}

function getCurrentStepIndex() {
  if (typeof window === "undefined") return 0;
  const current = normalizePath(window.location.pathname);
  const idx = DEMO_SCRIPT_STEPS.findIndex((step) => normalizePath(step.path) === current);
  return idx >= 0 ? idx : 0;
}

function goToStep(stepIndex) {
  if (typeof window === "undefined") return;
  const idx = Math.max(0, Math.min(stepIndex, DEMO_SCRIPT_STEPS.length - 1));
  const step = DEMO_SCRIPT_STEPS[idx];
  saveDemoScriptState({ active: true, stepIndex: idx });
  const url = new URL(step.path, window.location.origin);
  url.searchParams.set("demoScript", "1");
  window.location.href = url.toString();
}

function startDemoScript() {
  goToStep(0);
}

function stopDemoScript() {
  if (typeof window === "undefined") return;
  window.sessionStorage.removeItem(DEMO_SCRIPT_KEY);
}

function ensureBuyerOneClickAuthorization() {
  const s = getState();
  const b = s.buyer || {};
  b.token = b.token || "USDC";
  b.allowance = Math.max(Number(b.allowance || 0), 100);
  b.perCallLimit = Math.max(Number(b.perCallLimit || 0), 0.05);
  b.dailyLimit = Math.max(Number(b.dailyLimit || 0), 5);
  b.autoConfirm = Math.max(Number(b.autoConfirm || 0), 0.01);
  b.locked = Math.max(Number(b.locked || 0), 30);
  b.reserved = Math.max(Number(b.reserved || 0), 5.5);
  b.active = Math.max(0, Number(b.allowance) - Number(b.locked) - Number(b.reserved));
  s.buyer = b;
  saveState(s);
  return s;
}

function ensureSellerOneClickDeploy() {
  const s = getState();
  const now = new Date().toISOString().slice(0, 16).replace("T", " ");
  const baseService = {
    id: `svc-${Date.now()}`,
    name: "Any Pair Price API",
    price: 0.03,
    token: "USDC",
    status: "active",
    endpoint: "https://api.binance.com/api/v3/ticker/price?symbol={SYMBOL}",
    method: "GET",
    deployedAt: now,
  };
  const hasEquivalent = (s.services || []).some((v) => v.name === baseService.name && v.status === "active");
  if (!hasEquivalent) {
    s.services = s.services || [];
    s.services.unshift(baseService);
  }
  saveState(s);
  return s;
}

function ensureDataShape() {
  const s = getState();
  if (!Array.isArray(s.myAgents)) {
    s.myAgents = [{ id: `agent-${Date.now()}`, name: "DefaultAgent", status: "running", services: 1 }];
  }
  s.buyer = s.buyer || {};
  s.buyer.stopped = !!s.buyer.stopped;
  s.bills = (s.bills || []).map((b) => ({
    seller: b.seller || "UnknownSeller",
    callerAgent: b.callerAgent || "UnknownAgent",
    status: b.status || "PendingConfirm",
    payStrategy: b.payStrategy || (Number(b.amount || 0) >= 0.03 ? "batch" : "now"),
    ...b,
  }));
  saveState(s);
  return s;
}

function addMyAgent(payload) {
  const s = ensureDataShape();
  const data = payload || {};
  s.myAgents.unshift({
    id: `agent-${Date.now()}`,
    name: String(data.name || "NewAgent").trim(),
    description: String(data.description || ""),
    serviceType: String(data.serviceType || "数据查询"),
    endpoint: String(data.endpoint || ""),
    price: Number(data.price || 0),
    token: String(data.token || "USDC"),
    wallet: String(data.wallet || ""),
    successOnly: !!data.successOnly,
    refundable: !!data.refundable,
    manualConfirm: !!data.manualConfirm,
    status: "running",
    todayCalls: 0,
    todayIncome: 0,
    totalIncome: 0,
  });
  saveState(s);
  return s;
}

function removeMyAgent(agentId) {
  const s = ensureDataShape();
  s.myAgents = (s.myAgents || []).filter((a) => a.id !== agentId);
  saveState(s);
  return s;
}

function updateMyAgent(agentId, patch) {
  const s = ensureDataShape();
  s.myAgents = (s.myAgents || []).map((a) => (a.id === agentId ? { ...a, ...patch } : a));
  saveState(s);
  return s;
}

function stopBuyerAuthorization() {
  const s = ensureDataShape();
  s.buyer.stopped = true;
  s.buyer.active = 0;
  saveState(s);
  return s;
}

function increaseBuyerAllowance(delta) {
  const s = ensureDataShape();
  const d = Number(delta || 0);
  s.buyer.stopped = false;
  s.buyer.allowance = Number(s.buyer.allowance || 0) + d;
  s.buyer.active = Math.max(0, Number(s.buyer.active || 0) + d);
  saveState(s);
  return s;
}

function updateBillStatus(billId, status) {
  const s = ensureDataShape();
  s.bills = (s.bills || []).map((b) => (b.id === billId ? { ...b, status } : b));
  saveState(s);
  return s;
}

function updateBillStrategy(billId, payStrategy) {
  const s = ensureDataShape();
  s.bills = (s.bills || []).map((b) => (b.id === billId ? { ...b, payStrategy } : b));
  saveState(s);
  return s;
}

function batchSettleNowBills() {
  const s = ensureDataShape();
  let settledAmount = 0;
  s.bills = (s.bills || []).map((b) => {
    if (b.status === "PendingSettle" && b.payStrategy === "now") {
      settledAmount += Number(b.amount || 0);
      return { ...b, status: "Paid" };
    }
    return b;
  });
  s.buyer.active = Math.max(0, Number(s.buyer.active || 0) - settledAmount);
  s.buyer.reserved = Math.max(0, Number(s.buyer.reserved || 0) - settledAmount);
  s.buyer.settled = Number(s.buyer.settled || 0) + settledAmount;
  saveState(s);
  return { ...s, _batchSettledAmount: settledAmount };
}

function getBuyerChecklist() {
  const s = getState();
  const b = s.buyer || {};
  return [
    { key: "authorize", label: "1) 一键授权额度", done: Number(b.allowance || 0) > 0, href: "/buyer/authorize/" },
    { key: "confirm", label: "2) 确认 Agent 调用", done: (s.calls || []).length > 0, href: "/agent/confirm-call/" },
    { key: "track", label: "3) 查看账单追踪", done: (s.bills || []).length > 0, href: "/buyer/bills/" },
  ];
}

function getSellerChecklist() {
  const s = getState();
  const hasService = (s.services || []).length > 0;
  return [
    { key: "deploy", label: "1) 一键部署收费服务", done: hasService, href: "/seller/create-service/" },
    { key: "accept", label: "2) 接收 Agent 调用", done: (s.calls || []).length > 0, href: "/agent/confirm-call/" },
    { key: "income", label: "3) 查看收入结算", done: (s.revenue || []).length > 0, href: "/seller/revenue/" },
  ];
}

function mountDemoScriptGuide() {
  if (typeof window === "undefined" || typeof document === "undefined") return;
  const params = new URLSearchParams(window.location.search);
  const scriptedByUrl = params.get("demoScript") === "1";
  const state = getDemoScriptState();
  const active = scriptedByUrl || state.active;
  if (!active) return;

  const currentStep = getCurrentStepIndex();
  saveDemoScriptState({ active: true, stepIndex: currentStep });
  if (document.getElementById("tcDemoGuide")) return;

  const panel = document.createElement("div");
  panel.id = "tcDemoGuide";
  panel.className = "demo-guide";
  const step = DEMO_SCRIPT_STEPS[currentStep];
  const atEnd = currentStep >= DEMO_SCRIPT_STEPS.length - 1;
  panel.innerHTML = `
    <div class="demo-guide-title">演示脚本模式（${currentStep + 1}/${DEMO_SCRIPT_STEPS.length}） ${step.title}</div>
    <div class="demo-guide-hint">${step.hint}</div>
    <div class="demo-guide-actions">
      <button id="tcDemoStop">退出脚本</button>
      <button id="tcDemoNext" class="primary">${atEnd ? "完成演示" : "下一步自动跳页"}</button>
    </div>
  `;
  document.body.appendChild(panel);

  document.getElementById("tcDemoStop").onclick = () => {
    stopDemoScript();
    panel.remove();
  };
  document.getElementById("tcDemoNext").onclick = () => {
    if (atEnd) {
      stopDemoScript();
      panel.remove();
      return;
    }
    goToStep(currentStep + 1);
  };
}

maybeResetFromUrl();
ensureDataShape();
mountDemoScriptGuide();

window.tcUI = {
  getState,
  saveState,
  fmt,
  resetDemoState,
  startDemoScript,
  stopDemoScript,
  ensureBuyerOneClickAuthorization,
  ensureSellerOneClickDeploy,
  getBuyerChecklist,
  getSellerChecklist,
  addMyAgent,
  removeMyAgent,
  updateMyAgent,
  stopBuyerAuthorization,
  increaseBuyerAllowance,
  updateBillStatus,
  updateBillStrategy,
  batchSettleNowBills,
};
