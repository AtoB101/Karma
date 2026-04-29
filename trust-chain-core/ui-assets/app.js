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
    services: [{ id: "svc-001", name: "Price API", price: 0.01, token: "USDC", status: "active" }],
    bills: [
      {
        id: "BILL-001",
        service: "Price API",
        seller: "MarketDataBot",
        amount: 0.01,
        status: "Settled",
        createdAt: "2026-04-29 08:10",
      },
      {
        id: "BILL-002",
        service: "Risk Scan",
        seller: "SafeScan",
        amount: 0.03,
        status: "Pending",
        createdAt: "2026-04-29 08:21",
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
};
