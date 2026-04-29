#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const http = require("http");
const { URL } = require("url");
const { ethers } = require("ethers");

const HOST = process.env.MVP_HOST || process.env.HOST || "127.0.0.1";
const PORT = Number(process.env.MVP_PORT || process.env.PORT || 8822);
const RPC_URL = process.env.RPC_URL || "";
const USER_PRIVATE_KEY = process.env.USER_PRIVATE_KEY || process.env.SETTLEMENT_PRIVATE_KEY || "";
const PROVIDER_WALLET = process.env.PROVIDER_WALLET || process.env.TREASURY_ADDRESS || "";
const CHARGE_WEI = process.env.CHARGE_WEI || "10000000000000"; // 0.00001 ETH
const LOG_PATH = process.env.LOG_PATH || path.join(__dirname, "logs", "paid-calls.jsonl");
const DEFAULT_SYMBOL = (process.env.DEFAULT_SYMBOL || "BTC/USDT").toUpperCase();
const ALLOW_ORIGIN = process.env.ALLOW_ORIGIN || "*";
const STATIC_ROOT =
  process.env.DASHBOARD_STATIC_DIR || path.resolve(__dirname, "../../../trust-chain-core");
const API_PREFIX = "/api/v1";
const APP_ENV = process.env.APP_ENV || process.env.NODE_ENV || "development";
const BASE_PUBLIC_URL = process.env.BASE_PUBLIC_URL || "";

const dashboardState = {
  allowance: {
    token: "USDC",
    allowance: 50,
    active: 24.5,
    locked: 30,
    reserved: 5.5,
    stopped: false,
  },
  agents: [
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
  ],
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
  ],
  activity: [
    {
      time: "15:42",
      agent: "交易助手 Agent",
      action: "调用合约风险检测服务",
      amount: 0.03,
      status: "PendingConfirm",
    },
    {
      time: "15:20",
      agent: "数据分析 Agent",
      action: "调用钱包画像服务",
      amount: 0.08,
      status: "Paid",
    },
  ],
};

const userConsoleState = {
  profile: {
    userId: "user-001",
    displayName: "Karma Operator",
    wallet: "0xA12...89F",
    token: "USDC",
  },
  payRule: {
    autoPayEnabled: true,
    autoPayLimit: 0.02,
    hardLimit: 1.0,
  },
  payments: [
    {
      id: "PAY-001",
      direction: "pay",
      counterparty: "PriceHunter",
      amount: 0.01,
      status: "paid",
      note: "BTC/USDT quote",
      createdAt: "2026-04-29 09:10",
      approvalRequired: false,
    },
    {
      id: "PAY-002",
      direction: "pay",
      counterparty: "RiskGuard",
      amount: 0.08,
      status: "pending_manual",
      note: "Risk scan bundle",
      createdAt: "2026-04-29 09:18",
      approvalRequired: true,
    },
  ],
  receipts: [
    {
      id: "REC-001",
      direction: "receive",
      from: "PortfolioBot",
      amount: 0.03,
      status: "received",
      note: "ETH market data",
      createdAt: "2026-04-29 09:03",
    },
  ],
};

function chainEnabled() {
  return Boolean(RPC_URL && USER_PRIVATE_KEY && PROVIDER_WALLET);
}

class HttpError extends Error {
  constructor(status, code, message, data) {
    super(message);
    this.status = status;
    this.code = code;
    this.data = data;
  }
}

function json(res, status, payload) {
  let body = payload;
  if (payload && typeof payload === "object" && !Array.isArray(payload)) {
    const hasUnifiedShape =
      Object.prototype.hasOwnProperty.call(payload, "code") &&
      Object.prototype.hasOwnProperty.call(payload, "message") &&
      Object.prototype.hasOwnProperty.call(payload, "data");
    if (!hasUnifiedShape) {
      const ok = payload.ok !== false && status < 400;
      const code = payload.code || (ok ? "OK" : "ERROR");
      const message = payload.message || payload.error || (ok ? "success" : "error");
      const data =
        payload.data ??
        Object.fromEntries(
          Object.entries(payload).filter(([k]) => !["ok", "code", "message", "error"].includes(k))
        );
      body = { ok, code, message, data };
    }
  }
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Access-Control-Allow-Origin": ALLOW_ORIGIN,
    "Access-Control-Allow-Methods": "GET,POST,PATCH,DELETE,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
  });
  res.end(JSON.stringify(body, null, 2));
}

function text(res, status, payload) {
  res.writeHead(status, {
    "Content-Type": "text/plain; charset=utf-8",
    "Access-Control-Allow-Origin": ALLOW_ORIGIN,
    "Access-Control-Allow-Methods": "GET,POST,PATCH,DELETE,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
  });
  res.end(payload);
}

function appendLog(record) {
  fs.mkdirSync(path.dirname(LOG_PATH), { recursive: true });
  fs.appendFileSync(LOG_PATH, `${JSON.stringify(record)}\n`, "utf-8");
}

function contentTypeByExt(ext) {
  const map = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
  };
  return map[ext] || "application/octet-stream";
}

function isApiPath(urlPath, routePath) {
  const canonical = routePath.startsWith("/api/") ? routePath.slice(4) : routePath;
  const legacyPath = routePath.startsWith("/api/") ? routePath : `/api${canonical}`;
  const v1Path = `${API_PREFIX}${canonical}`;
  return urlPath === legacyPath || urlPath === v1Path;
}

function getApiPath(routePath) {
  const canonical = routePath.startsWith("/api/") ? routePath.slice(4) : routePath;
  return `${API_PREFIX}${canonical}`;
}

function toCanonicalApiPath(urlPath) {
  if (urlPath.startsWith(`${API_PREFIX}/`)) {
    return `/api${urlPath.slice(API_PREFIX.length)}`;
  }
  if (urlPath === API_PREFIX) return "/api";
  if (urlPath.startsWith("/api/") || urlPath === "/api") return urlPath;
  return null;
}

function assertNonEmptyString(value, fieldName) {
  const str = String(value ?? "").trim();
  if (!str) {
    throw new HttpError(400, "INVALID_ARGUMENT", `${fieldName} is required`);
  }
  return str;
}

function assertPositiveNumber(value, fieldName) {
  const num = Number(value);
  if (!Number.isFinite(num) || num <= 0) {
    throw new HttpError(400, "INVALID_ARGUMENT", `${fieldName} must be a positive number`);
  }
  return num;
}

function tryServeStaticFile(urlPath, res) {
  const normalized = decodeURIComponent(urlPath || "/");
  const relPath = normalized === "/" ? "/index.html" : normalized;
  const absPath = path.resolve(STATIC_ROOT, `.${relPath}`);
  if (!absPath.startsWith(STATIC_ROOT)) return false;
  if (!fs.existsSync(absPath) || fs.statSync(absPath).isDirectory()) return false;
  res.writeHead(200, {
    "Content-Type": contentTypeByExt(path.extname(absPath).toLowerCase()),
    "Access-Control-Allow-Origin": ALLOW_ORIGIN,
  });
  res.end(fs.readFileSync(absPath));
  return true;
}

function normalizeDashboardState() {
  dashboardState.allowance.active = Math.max(
    0,
    Number(dashboardState.allowance.allowance || 0) -
      Number(dashboardState.allowance.locked || 0) -
      Number(dashboardState.allowance.reserved || 0)
  );
}

function nowHm() {
  const d = new Date();
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${hh}:${mm}`;
}

function pushActivity(entry) {
  dashboardState.activity.unshift({
    time: nowHm(),
    ...entry,
  });
  dashboardState.activity = dashboardState.activity.slice(0, 30);
}

function summarizeDashboard() {
  const totalIncome = dashboardState.agents.reduce((sum, a) => sum + Number(a.totalIncome || 0), 0);
  const totalExpense = dashboardState.bills
    .filter((b) => b.status === "Paid")
    .reduce((sum, b) => sum + Number(b.amount || 0), 0);
  return {
    wallet: {
      address: "0xA12...89F",
      token: dashboardState.allowance.token,
      balance: 100,
    },
    allowance: dashboardState.allowance,
    totals: { totalIncome, totalExpense },
    counts: {
      pendingConfirm: dashboardState.bills.filter((b) => b.status === "PendingConfirm").length,
      pendingSettle: dashboardState.bills.filter((b) => b.status === "PendingSettle").length,
      paid: dashboardState.bills.filter((b) => b.status === "Paid").length,
      disputed: dashboardState.bills.filter((b) => b.status === "Disputed").length,
    },
  };
}

function nowYmdHm() {
  const d = new Date();
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd} ${nowHm()}`;
}

function summarizeUserConsole() {
  const paidOut = userConsoleState.payments
    .filter((p) => p.status === "paid")
    .reduce((sum, p) => sum + Number(p.amount || 0), 0);
  const pendingManual = userConsoleState.payments.filter((p) => p.status === "pending_manual").length;
  const received = userConsoleState.receipts
    .filter((r) => r.status === "received")
    .reduce((sum, r) => sum + Number(r.amount || 0), 0);
  return {
    profile: userConsoleState.profile,
    payRule: userConsoleState.payRule,
    stats: {
      paidOut,
      pendingManual,
      received,
      autoPayRatio: `${userConsoleState.payRule.autoPayEnabled ? "Auto" : "Manual"} <= ${
        userConsoleState.payRule.autoPayLimit
      } ${userConsoleState.profile.token}`,
    },
  };
}

async function readJsonBody(req) {
  let raw = "";
  req.on("data", (chunk) => {
    raw += chunk;
  });
  await new Promise((resolve) => req.on("end", resolve));
  if (!raw.trim()) return {};
  try {
    return JSON.parse(raw);
  } catch {
    return {};
  }
}

function normalizeSymbol(raw) {
  const cleaned = String(raw || DEFAULT_SYMBOL).trim().toUpperCase().replace(/\s+/g, "");
  const pairCode = cleaned.replace("/", "");
  if (!/^[A-Z0-9]{6,20}$/.test(pairCode)) {
    throw new Error(`Invalid symbol format: ${raw}`);
  }
  const display = cleaned.includes("/") ? cleaned : `${pairCode.slice(0, pairCode.length - 4)}/${pairCode.slice(-4)}`;
  return { display, pairCode };
}

function explorerUrl(chainId, txHash) {
  if (!txHash) return "";
  if (chainId === 11155111) return `https://sepolia.etherscan.io/tx/${txHash}`;
  if (chainId === 1) return `https://etherscan.io/tx/${txHash}`;
  return `https://explorer.invalid/tx/${txHash}`;
}

async function fetchPrice(symbol) {
  const parsed = normalizeSymbol(symbol);
  // Binance ticker endpoint supports a broad list of exchange pairs.
  const url = `https://api.binance.com/api/v3/ticker/price?symbol=${parsed.pairCode}`;
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`Price API failed: ${resp.status}`);
  const obj = await resp.json();
  const price = Number(obj?.price);
  if (!Number.isFinite(price)) throw new Error("Invalid price response");
  return {
    exchange: "binance",
    symbol: parsed.display,
    pairCode: parsed.pairCode,
    price,
  };
}

async function runPaidCall(provider, wallet, symbol, userId) {
  const callId = `call_${Date.now()}`;
  const startedAt = new Date().toISOString();
  const amount = BigInt(CHARGE_WEI);

  const userBalanceBefore = await provider.getBalance(wallet.address);
  const providerBalanceBefore = await provider.getBalance(PROVIDER_WALLET);
  const quote = await fetchPrice(symbol);

  const tx = await wallet.sendTransaction({
    to: PROVIDER_WALLET,
    value: amount,
  });
  const receipt = await tx.wait(1);

  const userBalanceAfter = await provider.getBalance(wallet.address);
  const providerBalanceAfter = await provider.getBalance(PROVIDER_WALLET);
  const completedAt = new Date().toISOString();

  const result = {
    schemaVersion: "trustchain.mvp.paid-call.v1",
    ok: true,
    callId,
    userId: String(userId || "external-user"),
    startedAt,
    completedAt,
    quote: {
      exchange: quote.exchange,
      symbol: quote.symbol,
      pairCode: quote.pairCode,
      price: quote.price,
    },
    chargedWei: amount.toString(),
    txHash: receipt.hash,
    chainId: Number(receipt.chainId),
    blockNumber: receipt.blockNumber,
    explorerUrl: explorerUrl(Number(receipt.chainId), receipt.hash),
    balances: {
      user: {
        beforeWei: userBalanceBefore.toString(),
        afterWei: userBalanceAfter.toString(),
      },
      provider: {
        beforeWei: providerBalanceBefore.toString(),
        afterWei: providerBalanceAfter.toString(),
      },
    },
    settlement: {
      chargedWei: amount.toString(),
      txHash: receipt.hash,
      chainId: Number(receipt.chainId),
      explorerUrl: explorerUrl(Number(receipt.chainId), receipt.hash),
      beforeBalanceWei: userBalanceBefore.toString(),
      afterBalanceWei: userBalanceAfter.toString(),
      beforeBalanceEth: ethers.formatEther(userBalanceBefore),
      afterBalanceEth: ethers.formatEther(userBalanceAfter),
    },
  };
  appendLog(result);
  return result;
}

async function main() {
  const hasChain = chainEnabled();
  const provider = hasChain ? new ethers.JsonRpcProvider(RPC_URL) : null;
  const wallet = hasChain ? new ethers.Wallet(USER_PRIVATE_KEY, provider) : null;

  const server = http.createServer(async (req, res) => {
    try {
      if (req.method === "OPTIONS") {
        text(res, 204, "");
        return;
      }
      const url = new URL(req.url || "/", `http://${req.headers.host}`);
      if (req.method === "GET" && !url.pathname.startsWith("/api/")) {
        if (tryServeStaticFile(url.pathname, res)) return;
        if (tryServeStaticFile("/index.html", res)) return;
        json(res, 404, { error: `Static file not found: ${url.pathname}` });
        return;
      }
      const apiPath = toCanonicalApiPath(url.pathname);
      if (!apiPath) {
        json(res, 404, { error: "Not found" });
        return;
      }

      if (req.method === "GET" && (apiPath === "/api/status" || apiPath === "/api/health")) {
        const network = hasChain ? await provider.getNetwork() : { chainId: 0n };
        json(res, 200, {
          ok: true,
          schemaVersion: "trustchain.mvp.status.v1",
          network: {
            chainId: Number(network.chainId),
          },
          userWallet: hasChain ? wallet.address : "offline-mode",
          providerWallet: PROVIDER_WALLET || "offline-mode",
          chargeWei: CHARGE_WEI,
          defaultSymbol: DEFAULT_SYMBOL,
          supportedPriceSource: "binance",
          chainEnabled: hasChain,
          environment: APP_ENV,
        });
        return;
      }

      if (req.method === "GET" && apiPath === "/api/config") {
        json(res, 200, {
          ok: true,
          schemaVersion: "trustchain.mvp.config.v1",
          pricePerCallWei: CHARGE_WEI,
          pricePerCallEth: ethers.formatEther(CHARGE_WEI),
          defaultSymbol: DEFAULT_SYMBOL,
          endpoint: getApiPath("/api/price-paid"),
          basePublicUrl: BASE_PUBLIC_URL,
        });
        return;
      }

      if (req.method === "GET" && apiPath === "/api/dashboard") {
        normalizeDashboardState();
        json(res, 200, {
          ok: true,
          schemaVersion: "trustchain.mvp.dashboard.v1",
          summary: summarizeDashboard(),
          agents: dashboardState.agents,
          bills: dashboardState.bills,
          activity: dashboardState.activity,
        });
        return;
      }

      if (req.method === "GET" && apiPath === "/api/user-console/overview") {
        json(res, 200, {
          ok: true,
          summary: summarizeUserConsole(),
          payments: userConsoleState.payments,
          receipts: userConsoleState.receipts,
        });
        return;
      }

      if (req.method === "GET" && apiPath === "/api/user-console/pay-rule") {
        json(res, 200, { ok: true, item: userConsoleState.payRule });
        return;
      }

      if (req.method === "POST" && apiPath === "/api/user-console/pay-rule") {
        const body = await readJsonBody(req);
        const autoPayEnabled = Boolean(body.autoPayEnabled);
        const autoPayLimit = assertPositiveNumber(body.autoPayLimit, "autoPayLimit");
        const hardLimit = assertPositiveNumber(body.hardLimit, "hardLimit");
        if (autoPayLimit > hardLimit) {
          throw new HttpError(400, "INVALID_ARGUMENT", "autoPayLimit must be <= hardLimit");
        }
        userConsoleState.payRule = { autoPayEnabled, autoPayLimit, hardLimit };
        pushActivity({
          agent: "用户支付策略",
          action: "更新小额自动支付规则",
          amount: autoPayLimit,
          status: "Paid",
        });
        json(res, 200, { ok: true, item: userConsoleState.payRule });
        return;
      }

      if (req.method === "POST" && apiPath === "/api/user-console/payments/create") {
        const body = await readJsonBody(req);
        const counterparty = assertNonEmptyString(body.counterparty, "counterparty");
        const amount = assertPositiveNumber(body.amount, "amount");
        const note = String(body.note || "").trim();
        const { autoPayEnabled, autoPayLimit, hardLimit } = userConsoleState.payRule;
        if (amount > hardLimit) {
          throw new HttpError(
            400,
            "PAYMENT_LIMIT_EXCEEDED",
            `amount exceeds hardLimit ${hardLimit} ${userConsoleState.profile.token}`
          );
        }
        const approvalRequired = !(autoPayEnabled && amount <= autoPayLimit);
        const item = {
          id: `PAY-${Date.now()}`,
          direction: "pay",
          counterparty,
          amount,
          status: approvalRequired ? "pending_manual" : "paid",
          note,
          createdAt: nowYmdHm(),
          approvalRequired,
        };
        userConsoleState.payments.unshift(item);
        if (!approvalRequired) {
          dashboardState.allowance.reserved = Math.max(0, Number(dashboardState.allowance.reserved || 0) - amount);
          normalizeDashboardState();
        }
        pushActivity({
          agent: counterparty,
          action: approvalRequired ? "触发大额待人工确认支付" : "执行小额自动支付",
          amount,
          status: approvalRequired ? "PendingConfirm" : "Paid",
        });
        json(res, 200, { ok: true, item });
        return;
      }

      if (req.method === "POST" && /^\/api\/user-console\/payments\/[^/]+\/(approve|reject)$/.test(apiPath)) {
        const seg = apiPath.split("/");
        const paymentId = seg[seg.length - 2];
        const action = seg[seg.length - 1];
        let item = null;
        userConsoleState.payments = userConsoleState.payments.map((p) => {
          if (p.id !== paymentId) return p;
          if (p.status !== "pending_manual") return p;
          item = { ...p, status: action === "approve" ? "paid" : "rejected", approvalRequired: false };
          return item;
        });
        if (!item) {
          throw new HttpError(404, "NOT_FOUND", "pending manual payment not found");
        }
        pushActivity({
          agent: item.counterparty,
          action: action === "approve" ? "人工确认通过支付" : "人工拒绝支付",
          amount: Number(item.amount || 0),
          status: action === "approve" ? "Paid" : "Disputed",
        });
        json(res, 200, { ok: true, item });
        return;
      }

      if (req.method === "POST" && apiPath === "/api/user-console/receipts/create") {
        const body = await readJsonBody(req);
        const from = assertNonEmptyString(body.from, "from");
        const amount = assertPositiveNumber(body.amount, "amount");
        const note = String(body.note || "").trim();
        const item = {
          id: `REC-${Date.now()}`,
          direction: "receive",
          from,
          amount,
          status: "received",
          note,
          createdAt: nowYmdHm(),
        };
        userConsoleState.receipts.unshift(item);
        pushActivity({
          agent: from,
          action: "收款到账",
          amount,
          status: "Paid",
        });
        json(res, 200, { ok: true, item });
        return;
      }

      if (req.method === "GET" && apiPath === "/api/deploy-readiness") {
        const hasChain = chainEnabled();
        const checks = [
          { key: "api.dashboard", ok: true },
          { key: "api.agents", ok: true },
          { key: "api.bills", ok: true },
          { key: "chain.enabled", ok: hasChain },
        ];
        const requiredChecks = checks.filter((c) => c.key !== "chain.enabled");
        json(res, 200, {
          ok: true,
          code: "DEPLOY_READINESS",
          message: "deploy readiness snapshot",
          data: {
            ready: requiredChecks.every((c) => c.ok),
            checks,
          },
        });
        return;
      }

      if (req.method === "GET" && apiPath === "/api/agents") {
        json(res, 200, { ok: true, items: dashboardState.agents });
        return;
      }

      if (req.method === "POST" && apiPath === "/api/agents") {
        const body = await readJsonBody(req);
        const name = assertNonEmptyString(body.name || "NewAgent", "name");
        const price = Number(body.price || 0);
        if (!Number.isFinite(price) || price < 0) {
          throw new HttpError(400, "INVALID_ARGUMENT", "price must be a non-negative number");
        }
        const item = {
          id: `agent-${Date.now()}`,
          name,
          description: String(body.description || ""),
          serviceType: String(body.serviceType || "数据查询"),
          endpoint: String(body.endpoint || ""),
          price,
          token: String(body.token || dashboardState.allowance.token),
          wallet: String(body.wallet || ""),
          successOnly: !!body.successOnly,
          refundable: !!body.refundable,
          manualConfirm: !!body.manualConfirm,
          status: "running",
          todayCalls: 0,
          todayIncome: 0,
          totalIncome: 0,
        };
        dashboardState.agents.unshift(item);
        pushActivity({
          agent: item.name,
          action: "新增收费 Agent",
          amount: item.price,
          status: "Paid",
        });
        json(res, 200, { ok: true, item });
        return;
      }

      if (req.method === "PATCH" && /^\/api\/agents\/[^/]+$/.test(apiPath)) {
        const agentId = apiPath.split("/").pop();
        const body = await readJsonBody(req);
        let targetName = "Agent";
        dashboardState.agents = dashboardState.agents.map((a) => {
          if (a.id !== agentId) return a;
          targetName = a.name;
          return { ...a, ...body };
        });
        pushActivity({
          agent: targetName,
          action: "更新 Agent 配置",
          amount: 0,
          status: "Paid",
        });
        json(res, 200, { ok: true });
        return;
      }

      if (req.method === "DELETE" && /^\/api\/agents\/[^/]+$/.test(apiPath)) {
        const agentId = apiPath.split("/").pop();
        let targetName = "Agent";
        dashboardState.agents = dashboardState.agents.filter((a) => {
          if (a.id === agentId) targetName = a.name;
          return a.id !== agentId;
        });
        pushActivity({
          agent: targetName,
          action: "删除收费 Agent",
          amount: 0,
          status: "Disputed",
        });
        json(res, 200, { ok: true });
        return;
      }

      if (req.method === "GET" && apiPath === "/api/bills") {
        const status = url.searchParams.get("status");
        const items = status ? dashboardState.bills.filter((b) => b.status === status) : dashboardState.bills;
        json(res, 200, { ok: true, items });
        return;
      }

      if (req.method === "POST" && /^\/api\/bills\/[^/]+\/(confirm|reject|settle|dispute)$/.test(apiPath)) {
        const seg = apiPath.split("/");
        const billId = seg[seg.length - 2];
        const action = seg[seg.length - 1];
        let target = "PendingConfirm";
        if (action === "confirm") target = "PendingSettle";
        if (action === "reject" || action === "dispute") target = "Disputed";
        if (action === "settle") target = "Paid";
        let touched = null;
        dashboardState.bills = dashboardState.bills.map((b) => {
          if (b.id !== billId) return b;
          touched = { ...b, status: target };
          return touched;
        });
        if (touched) {
          pushActivity({
            agent: touched.callerAgent,
            action: `账单${billId}执行${action}`,
            amount: Number(touched.amount || 0),
            status: target,
          });
        }
        json(res, 200, { ok: true });
        return;
      }

      if (req.method === "POST" && apiPath === "/api/bills/batch-settle-now") {
        let settled = 0;
        dashboardState.bills = dashboardState.bills.map((b) => {
          if (b.status === "PendingSettle" && b.payStrategy === "now") {
            settled += Number(b.amount || 0);
            return { ...b, status: "Paid" };
          }
          return b;
        });
        dashboardState.allowance.reserved = Math.max(0, Number(dashboardState.allowance.reserved || 0) - settled);
        normalizeDashboardState();
        pushActivity({
          agent: "系统批量",
          action: "批量结算立即付账单",
          amount: settled,
          status: "Paid",
        });
        json(res, 200, { ok: true, settledAmount: settled });
        return;
      }

      if (req.method === "POST" && apiPath === "/api/bills/strategy") {
        const body = await readJsonBody(req);
        const billId = assertNonEmptyString(body.billId, "billId");
        const payStrategy = assertNonEmptyString(body.payStrategy, "payStrategy");
        if (!["now", "batch"].includes(payStrategy)) {
          throw new HttpError(400, "INVALID_ARGUMENT", "payStrategy must be one of: now, batch");
        }
        dashboardState.bills = dashboardState.bills.map((b) =>
          b.id === billId ? { ...b, payStrategy } : b
        );
        json(res, 200, { ok: true });
        return;
      }

      if (req.method === "POST" && apiPath === "/api/allowance/stop") {
        dashboardState.allowance.stopped = true;
        dashboardState.allowance.active = 0;
        pushActivity({
          agent: "用户授权",
          action: "暂停 Agent 消费",
          amount: 0,
          status: "Disputed",
        });
        json(res, 200, { ok: true, allowance: dashboardState.allowance });
        return;
      }

      if (req.method === "POST" && apiPath === "/api/allowance/increase") {
        const body = await readJsonBody(req);
        const amount = assertPositiveNumber(body.amount, "amount");
        dashboardState.allowance.stopped = false;
        dashboardState.allowance.allowance += amount;
        normalizeDashboardState();
        pushActivity({
          agent: "用户授权",
          action: "增加授权额度",
          amount,
          status: "Paid",
        });
        json(res, 200, { ok: true, allowance: dashboardState.allowance });
        return;
      }

      if (req.method === "POST" && (apiPath === "/api/btc-price-paid" || apiPath === "/api/price-paid")) {
        if (!hasChain) {
          json(res, 503, {
            ok: false,
            code: "CHAIN_DISABLED",
            message: "Chain settlement env missing. Dashboard sync APIs are still available.",
            data: { required: ["RPC_URL", "USER_PRIVATE_KEY", "PROVIDER_WALLET"] },
          });
          return;
        }
        const body = await readJsonBody(req);
        const symbol = String(body.symbol || url.searchParams.get("symbol") || DEFAULT_SYMBOL);
        const userId = String(body.userId || "external-user");
        const output = await runPaidCall(provider, wallet, symbol, userId);
        json(res, 200, output);
        return;
      }

      json(res, 404, { error: "Not found" });
    } catch (err) {
      const status = Number(err?.status) || 500;
      json(res, status, {
        ok: false,
        code: err?.code || "INTERNAL_ERROR",
        message: String(err?.message || err),
        data: err?.data || null,
      });
    }
  });

  server.listen(PORT, HOST, () => {
    console.log(`MVP server listening on http://${HOST}:${PORT}`);
  });
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
