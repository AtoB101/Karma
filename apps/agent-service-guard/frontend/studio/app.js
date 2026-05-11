import {
  loadState,
  saveState,
  createAgent,
  escapeHtml,
  safeText,
  adjustVoluntaryLock,
} from "./store.js?v=20260507a";
import { syncUnifiedState } from "./sync.js?v=20260507a";
import * as api from "./api-client.js";

const AUTH_SESSION_KEY = "karma_web3_session";

const state = loadState();

const view = document.getElementById("view");
const navRoot = document.getElementById("nav-main");
const syncLine = document.getElementById("sync-line");
const toast = document.getElementById("toast");
const walletPill = document.getElementById("wallet-pill");
const logoutBtn = document.getElementById("logout-btn");
const pageTitle = document.getElementById("page-title");
const pageSub = document.getElementById("page-sub");

const NAV = [
  ["overview", "首页总览", "一个界面完成：收款、锁仓、交付、证据、争议、结算、信誉。"],
  ["services", "收款服务", "管理受保护服务与收费规则。"],
  ["orders", "订单管理", "受保护订单与状态机字段（与 DATA_CONTRACT 对齐）。"],
  ["locks", "锁仓资金", "买家锁款、最低责任金、超额信任锁仓。"],
  ["settlement", "待结算", "可结算金额与待办。"],
  ["evidence", "证据中心", "EvidenceBundle 公开展示字段。"],
  ["disputes", "争议处理", "争议状态与调解占位接口。"],
  ["risk", "风险告警", "调用 POST /risk/check 与展示结果。"],
  ["trust", "信誉档案", "Trust badge + POST /score/seller。"],
];

let currentNav = "overview";
let syncTimer = null;

function loadSession() {
  try {
    const fromTab = sessionStorage.getItem(AUTH_SESSION_KEY);
    if (fromTab) return JSON.parse(fromTab);
    const legacy = localStorage.getItem(AUTH_SESSION_KEY);
    if (legacy) {
      sessionStorage.setItem(AUTH_SESSION_KEY, legacy);
      localStorage.removeItem(AUTH_SESSION_KEY);
      return JSON.parse(legacy);
    }
    return null;
  } catch {
    return null;
  }
}

function clearAuthSession() {
  try {
    sessionStorage.removeItem(AUTH_SESSION_KEY);
    localStorage.removeItem(AUTH_SESSION_KEY);
  } catch (_) {}
}

function requireSession() {
  const session = loadSession();
  if (!session || !session.wallet) {
    location.href = "../web3-login.html?target=studio%2Findex.html";
    return null;
  }
  if (session.loginMethod !== "walletconnect-v2-qr") {
    clearAuthSession();
    location.href = "../web3-login.html?target=studio%2Findex.html";
    return null;
  }
  return session;
}

function shortAddr(a) {
  if (!a || a.length < 12) return a || "—";
  return `${a.slice(0, 6)}…${a.slice(-4)}`;
}

function formatMoney(n, ccy = "") {
  const x = Number(n);
  if (!Number.isFinite(x)) return "—";
  return (ccy ? `${x.toLocaleString()} ${ccy}` : `$${x.toLocaleString()}`).trim();
}

function showToast(msg, type = "ok") {
  toast.textContent = msg;
  toast.className = `toast show ${type}`;
  setTimeout(() => {
    toast.className = "toast";
  }, 2800);
}

function badgeClass(level) {
  const u = String(level || "").toUpperCase();
  if (u === "HIGH") return "red";
  if (u === "MEDIUM") return "yellow";
  return "green";
}

function tagForDispute(ds) {
  if (ds === "OPEN") return { cls: "red", text: "争议处理中" };
  if (ds === "RESOLVED") return { cls: "green", text: "争议已结束" };
  if (ds === "REJECTED") return { cls: "yellow", text: "争议已驳回" };
  return { cls: "blue", text: "等待买家确认" };
}

function renderKarmaBffPanel() {
  return `
<div class="panel" id="karma-bff-panel">
  <div class="panel-head"><h3>OpenManus · Karma BFF 状态</h3><span class="tag blue">只读</span></div>
  <p class="muted">同步 <code>GET /public/status/:traceId</code>，不携带 <code>BFF_INTEGRATION_SECRET</code>。写入与 HMAC 在后端 / OpenManus。</p>
  <div class="input-row" style="margin-top:8px">
    <input type="text" id="karma-bff-trace-input" placeholder="trace_id" style="flex:1;min-width:200px" autocomplete="off" />
    <button type="button" class="secondary" id="karma-bff-refresh-btn">同步状态</button>
  </div>
  <pre id="karma-bff-status-out" class="code-inline" style="margin-top:10px;min-height:3rem">—</pre>
  <p class="muted" style="margin-top:8px">买家锁仓说明：<span id="karma-bff-lock-link">—</span></p>
</div>`;
}

function renderOverview(u) {
  const ls = u.lockSummary;
  const st = u.stats;
  return `
<div class="hero">
  <div>
    <h3>今天你只需要处理这几件事</h3>
    <p>系统已经把资金状态、订单状态、证据状态和风险状态统一展示。卖家不用理解复杂链上字段，只要知道：哪笔钱锁着，哪笔钱能结算，哪笔订单需要补证，哪里需要处理争议。</p>
    <div class="actions">
      <button type="button" class="primary" data-action="scroll-orders">创建受保护订单</button>
      <button type="button" class="secondary" data-action="nav-locks">增加锁仓</button>
      <button type="button" class="secondary" data-action="nav-locks">减少锁仓</button>
      <button type="button" class="secondary" data-action="nav-settlement">查看待结算</button>
      <button type="button" class="secondary" data-action="nav-disputes">处理争议</button>
    </div>
  </div>
  <div class="lock-box">
    <div class="lock-item"><span>买家已锁金额</span><b class="tag blue">${formatMoney(ls.buyerLocked, ls.currency)}</b></div>
    <div class="lock-item"><span>强制最低责任金</span><b class="tag yellow">${formatMoney(ls.mandatoryMinBond, ls.currency)}</b></div>
    <div class="lock-item"><span>卖家主动超额锁仓</span><b class="tag green">${formatMoney(ls.sellerVoluntaryExcess, ls.currency)}</b></div>
    <div class="lock-item"><span>可减少锁仓</span><b class="tag purple">${formatMoney(ls.reducibleExcess, ls.currency)}</b></div>
    <div class="lock-item"><span>可结算金额</span><b class="tag green">${formatMoney(ls.settleable, ls.currency)}</b></div>
  </div>
</div>
<div class="stats">
  <div class="stat"><span>今日收入</span><strong>${formatMoney(st.todayIncome)}</strong></div>
  <div class="stat"><span>待结算</span><strong>${formatMoney(st.pendingSettlement)}</strong></div>
  <div class="stat"><span>最低责任金</span><strong>${formatMoney(st.minBond)}</strong></div>
  <div class="stat"><span>超额锁仓</span><strong>${formatMoney(st.excessLock)}</strong></div>
  <div class="stat"><span>保障等级</span><strong>${escapeHtml(st.trustLevel)}</strong></div>
  <div class="stat"><span>争议冻结</span><strong>${formatMoney(st.disputeFrozen)}</strong></div>
</div>
${renderKarmaBffPanel()}
<div class="layout">
  <div>
    ${renderFundingPanel(u)}
    ${renderOrdersPanel(u, 2)}
    ${renderStateMachine()}
  </div>
  <div>
    ${renderTodos(u)}
    ${renderTrustPanel(u)}
    ${renderEvidencePanel(u)}
    ${renderRiskPanel(u)}
  </div>
</div>`;
}

function renderFundingPanel(u) {
  const ls = u.lockSummary;
  const pct = ls.mandatoryMinBond ? Math.min(100, Math.round((ls.mandatoryMinBond / (ls.buyerLocked || 1)) * 100)) : 62;
  return `
<div class="panel">
  <div class="panel-head"><h3>统一资金控制</h3><span class="tag green">核心操作区</span></div>
  <div class="wallet-grid">
    <div class="wallet-card">
      <h4>最低责任金</h4>
      <p>系统强制锁定，用于违约赔付。订单完成后自动解锁，争议期间自动冻结。</p>
      <strong>${formatMoney(ls.mandatoryMinBond, ls.currency)}</strong>
      <span class="tag yellow">不可低于最低要求</span>
      <div class="progress"><div class="bar-yellow" style="width:${pct}%"></div></div>
    </div>
    <div class="wallet-card">
      <h4>超额信任锁仓</h4>
      <p>卖家自愿增加，用来提高买家信任。超过最低责任金的部分可以减少。</p>
      <strong>${formatMoney(ls.sellerVoluntaryExcess, ls.currency)}</strong>
      <span class="tag green">可增加 / 可减少</span>
      <div class="input-row">
        <input type="number" step="1" min="0" id="lock-delta-input" placeholder="输入金额，例如 500 USDT" />
        <button type="button" class="add" id="lock-add-btn">增加锁仓</button>
        <button type="button" class="reduce" id="lock-reduce-btn">减少锁仓</button>
      </div>
    </div>
  </div>
</div>`;
}

function renderServicesPanel(u) {
  const rows = u.services
    .map((s) => {
      const sid = escapeHtml(s.service_id);
      const name = escapeHtml(s.service_name || s.service_id);
      const price = s.price;
      const ccy = escapeHtml(s.currency || "USDC");
      const calls = s._mock_calls_today ?? "—";
      const okr = s._mock_success_pct ?? "—";
      const pend = s._mock_pending_usd ?? 0;
      const ano = s._mock_anomaly ?? 0;
      return `
<div class="service" data-service-id="${sid}">
  <div class="service-top"><div><h4>${name}</h4><small>${escapeHtml(s.description || s.service_type || "")} · 自动证据已开启</small></div><div class="amount">${price} ${ccy} / 次</div></div>
  <span class="tag green">${escapeHtml(s.status || "running")}</span>
  <div class="service-grid">
    <div class="box"><span>今日调用</span><b>${calls} 次</b></div>
    <div class="box"><span>成功率</span><b style="color:#34D399">${okr}%</b></div>
    <div class="box"><span>待结算</span><b>$${pend}</b></div>
    <div class="box"><span>异常调用</span><b style="color:#FBBF24">${ano} 次</b></div>
  </div>
  <div class="buttons">
    <button type="button" class="main" data-svc-copy="${sid}">复制服务入口</button>
    <button type="button" data-svc-api="get">刷新服务</button>
  </div>
</div>`;
    })
    .join("");
  return `
<div class="panel">
  <div class="panel-head"><h3>我的收款服务</h3><span class="tag blue">服务入口</span></div>
  <div class="card-create">
    <h4 style="margin-bottom:12px;font-size:15px">新建受保护服务（调用 POST /services）</h4>
    <div class="input-row" style="grid-template-columns:1fr 1fr 1fr auto">
      <input id="new-svc-name" placeholder="服务名称" />
      <input id="new-svc-price" type="number" step="0.01" min="0.01" placeholder="价格" />
      <input id="new-svc-ccy" placeholder="币种 USDC" value="USDC" />
      <button type="button" class="add" id="new-svc-btn">创建</button>
    </div>
  </div>
  ${rows || "<p class=\"muted\">暂无服务。可填写上方创建，或由后端 GET /services 同步。</p>"}
</div>`;
}

function renderOrdersPanel(u, limit = 0) {
  const list = limit ? u.orders.slice(0, limit) : u.orders;
  return `
<div class="panel">
  <div class="panel-head"><h3>受保护订单</h3><span class="tag blue">DATA_CONTRACT 字段</span></div>
  ${list.map(renderOrderCard).join("")}
</div>`;
}

function renderOrderCard(o) {
  const tag = tagForDispute(o.dispute_status);
  const oid = escapeHtml(o.order_id);
  return `
<div class="order" data-order-id="${oid}">
  <div class="order-top">
    <div><h4>${escapeHtml(o.service_name || "Service")}</h4><small>订单 #${oid} · pay:${escapeHtml(o.payment_status)} · del:${escapeHtml(o.delivery_status)}</small></div>
    <div class="amount">${o.price} ${escapeHtml(o.currency || "USDC")}</div>
  </div>
  <div class="tag ${tag.cls}">${tag.text}</div>
  <div class="grid">
    <div class="box"><span>payment_status</span><b>${escapeHtml(o.payment_status)}</b></div>
    <div class="box"><span>delivery_status</span><b>${escapeHtml(o.delivery_status)}</b></div>
    <div class="box"><span>dispute_status</span><b>${escapeHtml(o.dispute_status)}</b></div>
    <div class="box"><span>settlement_status</span><b>${escapeHtml(o.settlement_status)}</b></div>
    <div class="box"><span>seller_bond</span><b>${escapeHtml(String(o.seller_bond_amount ?? "—"))}</b></div>
  </div>
  <div class="buttons">
    <button type="button" class="main" data-order-sync="${oid}">拉取订单 GET</button>
    <button type="button" data-order-deliver="${oid}">提交交付 POST</button>
    <button type="button" class="danger" data-order-risk="${oid}">风险检查</button>
  </div>
</div>`;
}

function renderStateMachine() {
  return `
<div class="panel">
  <div class="panel-head"><h3>统一订单状态机</h3><span class="tag green">公开枚举</span></div>
  <div class="timeline">
    <div class="step"><div class="step-dot"></div><div><b>Buyer Locked</b><p>payment_status: MOCK_LOCKED / LOCKED</p></div></div>
    <div class="step"><div class="step-dot"></div><div><b>Seller Minimum Bond</b><p>seller_bond_status: MOCK_LOCKED / LOCKED</p></div></div>
    <div class="step"><div class="step-dot"></div><div><b>Optional Trust Lock</b><p>超额锁仓可增减（本地演示 + 未来 API）</p></div></div>
    <div class="step"><div class="step-dot wait"></div><div><b>Evidence Review</b><p>delivery_status · evidence_hash</p></div></div>
    <div class="step"><div class="step-dot off"></div><div><b>Released / Frozen / Refunded</b><p>settlement_status · dispute_status</p></div></div>
  </div>
</div>`;
}

function renderTodos(u) {
  return `
<div class="panel">
  <div class="panel-head"><h3>现在需要处理</h3></div>
  <div class="todo">
    ${u.todos
      .map(
        (t) => `
<div class="todo-card"><p>${escapeHtml(t.title)}</p><small>${escapeHtml(t.detail)}</small></div>`
      )
      .join("")}
  </div>
</div>`;
}

function renderTrustPanel(u) {
  const tb = u.trustBadge || {};
  return `
<div class="panel">
  <div class="panel-head"><h3>Trust Badge</h3></div>
  <div class="todo">
    <div class="todo-card"><p>当前等级：${escapeHtml(tb.band || u.stats.trustLevel)}</p><small>${escapeHtml(tb.narrative || "")}</small></div>
    <div class="todo-card"><p>最低保障：${tb.min_guarantee_pct ?? 30}%</p><small>系统强制规则</small></div>
    <div class="todo-card"><p>额外保障：+${tb.extra_guarantee_pct ?? 16}%</p><small>来自超额锁仓</small></div>
  </div>
</div>`;
}

function renderEvidencePanel(u) {
  return `
<div class="panel">
  <div class="panel-head"><h3>自动证据中心</h3></div>
  <div class="todo">
    ${u.evidence
      .map(
        (e) => `
<div class="todo-card">
  <p>${escapeHtml(e.input_summary || e.evidence_id)}</p>
  <small>${escapeHtml(e.output_summary || "")} · ${escapeHtml(e.execution_status || "")} · hash: ${escapeHtml((e.evidence_hash || "").slice(0, 18))}…</small>
</div>`
      )
      .join("")}
  </div>
</div>`;
}

function renderRiskPanel(u) {
  return `
<div class="panel">
  <div class="panel-head"><h3>风险告警</h3></div>
  <div class="todo">
    ${u.riskAlerts
      .map(
        (r) => `
<div class="todo-card">
  <p><span class="tag ${badgeClass(r.risk_level)}">${escapeHtml(r.risk_level || "LOW")}</span> ${escapeHtml(r.title)}</p>
  <small>${escapeHtml(r.detail)}</small>
</div>`
      )
      .join("")}
  </div>
</div>`;
}

function renderLocksPage(u) {
  return renderFundingPanel(u) + `<div class="panel"><div class="panel-head"><h3>锁仓说明</h3></div><p class="muted" style="line-height:1.7">调整仅更新本地演示状态；生产环境应对接合约/托管 API。同步仍会覆盖服务器返回的 lock_summary。</p></div>`;
}

function renderSettlementPage(u) {
  const ls = u.lockSummary;
  return `
<div class="panel">
  <div class="panel-head"><h3>待结算</h3><span class="tag green">${formatMoney(ls.settleable, ls.currency)}</span></div>
  <p class="muted" style="line-height:1.7">settlement_status 为 UNSETTLED 的订单将由后端规则推进。此处展示 dashboard 聚合值。</p>
</div>
${renderTodos(u)}`;
}

function renderEvidencePage(u) {
  return renderEvidencePanel(u);
}

function renderDisputesPage(u) {
  const dis = u.orders.filter((o) => o.dispute_status === "OPEN");
  return `
<div class="panel">
  <div class="panel-head"><h3>争议中的订单</h3></div>
  ${dis.length ? dis.map(renderOrderCard).join("") : "<p class=\"muted\">当前无 OPEN 争议。</p>"}
</div>
<div class="panel">
  <div class="panel-head"><h3>调解建议（POST /dispute/recommend-resolution）</h3></div>
  <p class="muted">选择订单后调用占位接口（私有引擎实现）。</p>
  <div class="input-row" style="grid-template-columns:1fr 1fr auto;margin-top:12px">
    <input id="rec-order" placeholder="order_id" value="${dis[0]?.order_id || ""}" />
    <input id="rec-dispute" placeholder="dispute_id (mock)" value="dsp_mock" />
    <button type="button" class="add" id="rec-btn">获取建议</button>
  </div>
  <pre id="rec-out" class="code-inline" style="margin-top:12px;display:none"></pre>
</div>`;
}

function renderRiskPage(u) {
  return `
${renderRiskPanel(u)}
<div class="panel">
  <div class="panel-head"><h3>主动巡检 POST /risk/check</h3></div>
  <button type="button" class="primary" id="risk-refresh-btn">对当前首单发起风险检查</button>
  <pre id="risk-out" class="code-inline" style="margin-top:12px;display:none"></pre>
</div>`;
}

function renderTrustPage(u, wallet) {
  const sc = u.sellerScore;
  return `
${renderTrustPanel(u)}
<div class="panel">
  <div class="panel-head"><h3>卖家评分 POST /score/seller</h3></div>
  <p class="muted">wallet: ${escapeHtml(shortAddr(wallet))}</p>
  <pre id="score-out" class="code-inline" style="display:${sc ? "block" : "none"}">${sc ? escapeHtml(JSON.stringify(sc, null, 2)) : ""}</pre>
  <button type="button" class="secondary" id="score-refresh-btn" style="margin-top:10px">重新拉取</button>
</div>`;
}

function renderMain() {
  const u = state.unified;
  const title = NAV.find(([k]) => k === currentNav);
  pageTitle.textContent = title ? title[1] : "Karma";
  pageSub.textContent = title ? title[2] : "";

  let html = "";
  if (currentNav === "overview") html = renderOverview(u);
  else if (currentNav === "services") html = renderServicesPanel(u);
  else if (currentNav === "orders") html = renderOrdersPanel(u, 0) + renderStateMachine();
  else if (currentNav === "locks") html = renderLocksPage(u);
  else if (currentNav === "settlement") html = renderSettlementPage(u);
  else if (currentNav === "evidence") html = renderEvidencePage(u);
  else if (currentNav === "disputes") html = renderDisputesPage(u);
  else if (currentNav === "risk") html = renderRiskPage(u);
  else if (currentNav === "trust") html = renderTrustPage(u, loadSession()?.wallet || "");

  view.innerHTML = html;
  bindActions();
}

function updateSyncLine() {
  const m = state.unified.syncMeta || {};
  const t = m.lastSyncAt ? new Date(m.lastSyncAt).toLocaleString() : "从未";
  const src = m.lastSource || "local";
  const err = m.lastError ? ` · ${m.lastError}` : "";
  syncLine.textContent = `同步: ${t} · 源: ${src}${err}`;
}

async function runSync() {
  const session = loadSession();
  if (!session?.wallet) return;
  syncLine.textContent = "同步中…";
  const r = await syncUnifiedState(state, session.wallet);
  saveState(state);
  updateSyncLine();
  if (r.error) showToast("同步失败，使用本地演示数据", "warn");
  else if (r.source === "api") showToast("已与服务器对齐", "ok");
  renderMain();
}

function bindNav() {
  navRoot.querySelectorAll("button[data-nav]").forEach((btn) => {
    btn.addEventListener("click", () => {
      currentNav = btn.getAttribute("data-nav");
      navRoot.querySelectorAll("button[data-nav]").forEach((b) => b.classList.toggle("active", b === btn));
      renderMain();
    });
  });
}

function bindActions() {
  view.querySelectorAll("[data-action]").forEach((el) => {
    el.addEventListener("click", () => {
      const a = el.getAttribute("data-action");
      if (a === "scroll-orders") {
        currentNav = "orders";
        navRoot.querySelector('[data-nav="orders"]')?.click();
      }
      if (a === "nav-locks") navRoot.querySelector('[data-nav="locks"]')?.click();
      if (a === "nav-settlement") navRoot.querySelector('[data-nav="settlement"]')?.click();
      if (a === "nav-disputes") navRoot.querySelector('[data-nav="disputes"]')?.click();
    });
  });

  document.getElementById("lock-add-btn")?.addEventListener("click", () => {
    const v = Number(document.getElementById("lock-delta-input")?.value || 0);
    if (!adjustVoluntaryLock(state, v) || v <= 0) return showToast("请输入有效增加金额", "error");
    saveState(state);
    showToast("已增加本地演示锁仓");
    renderMain();
  });
  document.getElementById("lock-reduce-btn")?.addEventListener("click", () => {
    const v = Number(document.getElementById("lock-delta-input")?.value || 0);
    if (!adjustVoluntaryLock(state, -v) || v <= 0) return showToast("可减少金额不足", "error");
    saveState(state);
    showToast("已减少本地演示锁仓");
    renderMain();
  });

  document.getElementById("karma-bff-refresh-btn")?.addEventListener("click", async () => {
    const tid = safeText(document.getElementById("karma-bff-trace-input")?.value || "", 160);
    const out = document.getElementById("karma-bff-status-out");
    const linkEl = document.getElementById("karma-bff-lock-link");
    if (!tid) return showToast("请输入 trace_id", "error");
    if (out) out.textContent = "加载中…";
    if (linkEl) linkEl.textContent = "—";
    try {
      const { fetchKarmaBffPublicStatus } = await import("./karma-bff-status.js");
      const r = await fetchKarmaBffPublicStatus(tid);
      if (out) out.textContent = JSON.stringify(r, null, 2);
      const base = String(window.KARMA_BFF_PUBLIC_BASE || "")
        .trim()
        .replace(/\/$/, "");
      if (linkEl) {
        if (base && r.ok) {
          const lockHref =
            r.body && r.body.buyer_lock_page_url
              ? String(r.body.buyer_lock_page_url)
              : `${base}/public/lock/${encodeURIComponent(tid)}`;
          linkEl.innerHTML = `<a href="${escapeHtml(lockHref)}" target="_blank" rel="noopener noreferrer">打开锁仓说明页</a>`;
        } else if (!base) {
          linkEl.textContent = "请在 karma-bff-config.js 中配置 KARMA_BFF_PUBLIC_BASE";
        } else {
          linkEl.textContent = "状态异常或 BFF 不可达";
        }
      }
      try {
        sessionStorage.setItem("karma_bff_last_trace", tid);
      } catch (_) {}
    } catch (e) {
      if (out) out.textContent = String(e && e.message ? e.message : e);
      showToast("BFF 状态拉取失败", "warn");
    }
  });
  try {
    const last = sessionStorage.getItem("karma_bff_last_trace");
    const inp = document.getElementById("karma-bff-trace-input");
    if (inp && last) inp.value = last;
  } catch (_) {}

  document.getElementById("new-svc-btn")?.addEventListener("click", async () => {
    const session = loadSession();
    const name = safeText(document.getElementById("new-svc-name")?.value || "", 80);
    const price = Number(document.getElementById("new-svc-price")?.value || 0);
    const currency = safeText(document.getElementById("new-svc-ccy")?.value || "USDC", 10);
    if (!name || price <= 0) return showToast("请填写服务名与价格", "error");
    const payload = {
      service_name: name,
      service_type: "agent_api",
      price,
      currency,
      seller_bond_rate: 0.3,
      refund_policy: "standard",
      description: "",
    };
    const res = await api.createService(payload, session?.wallet);
    if (res.ok && res.body?.service_id) {
      state.unified.services.unshift({ ...payload, service_id: res.body.service_id, status: "running" });
      saveState(state);
      showToast("服务端已创建服务", "ok");
    } else {
      createAgent(state, { name, price });
      saveState(state);
      showToast("后端不可用：已写入本地演示服务", "warn");
    }
    renderMain();
  });

  view.querySelectorAll("[data-svc-copy]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.getAttribute("data-svc-copy");
      const link = new URL(`../pay/${encodeURIComponent(id)}`, location.href).href;
      try {
        await navigator.clipboard.writeText(link);
        showToast("付款链接已复制（占位路径 pay/{service_id}）");
      } catch {
        showToast("复制失败", "error");
      }
    });
  });

  view.querySelectorAll("[data-order-sync]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.getAttribute("data-order-sync");
      const res = await api.getOrder(id);
      const pre = view.querySelector(`[data-order-id="${CSS.escape(id)}"]`);
      if (res.ok && res.body) {
        const idx = state.unified.orders.findIndex((o) => o.order_id === id);
        if (idx >= 0) state.unified.orders[idx] = { ...state.unified.orders[idx], ...res.body };
        saveState(state);
        showToast("订单已刷新", "ok");
      } else showToast("GET /orders/:id 不可用", "warn");
      renderMain();
    });
  });

  view.querySelectorAll("[data-order-deliver]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.getAttribute("data-order-deliver");
      const session = loadSession();
      const res = await api.postDeliver(
        id,
        { evidence_summary: "mock delivery", output_hash: "0x" + "0".repeat(64) },
        session?.wallet
      );
      if (res.ok) showToast("交付 POST 已发送", "ok");
      else showToast("交付接口不可用（本地演示）", "warn");
      await runSync();
    });
  });

  view.querySelectorAll("[data-order-risk]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.getAttribute("data-order-risk");
      const o = state.unified.orders.find((x) => x.order_id === id);
      if (!o) return;
      const session = loadSession();
      const payload = {
        order_id: id,
        service_type: o.service_type || "agent_api",
        price: o.price,
        currency: o.currency || "USDC",
        seller_wallet: session?.wallet || "",
        buyer_wallet: o.buyer_wallet || "0x0000000000000000000000000000000000000000",
      };
      const res = await api.postRiskCheck(payload);
      showToast(res.ok ? "risk/check 已返回" : "risk/check 不可用", res.ok ? "ok" : "warn");
    });
  });

  document.getElementById("rec-btn")?.addEventListener("click", async () => {
    const orderId = document.getElementById("rec-order")?.value?.trim();
    const disputeId = document.getElementById("rec-dispute")?.value?.trim();
    const out = document.getElementById("rec-out");
    const res = await api.postDisputeRecommend({
      dispute_id: disputeId,
      order_id: orderId,
      evidence_hash: "0xmock",
      reason_code: "QUALITY",
    });
    out.style.display = "block";
    out.textContent = JSON.stringify(res.body || { status: res.status }, null, 2);
  });

  document.getElementById("risk-refresh-btn")?.addEventListener("click", async () => {
    const o = state.unified.orders[0];
    if (!o) return showToast("无订单", "warn");
    const session = loadSession();
    const res = await api.postRiskCheck({
      order_id: o.order_id,
      service_type: o.service_type || "agent_api",
      price: o.price,
      currency: o.currency,
      seller_wallet: session?.wallet || "",
      buyer_wallet: o.buyer_wallet || "0x0",
    });
    const out = document.getElementById("risk-out");
    out.style.display = "block";
    out.textContent = JSON.stringify(res.body || { http: res.status }, null, 2);
  });

  document.getElementById("score-refresh-btn")?.addEventListener("click", async () => {
    const session = loadSession();
    if (!session?.wallet) return;
    const res = await api.postScoreSeller({ seller_wallet: session.wallet, period_days: 30 });
    if (res.ok && res.body) state.unified.sellerScore = res.body;
    saveState(state);
    renderMain();
  });
}

function initNavDom() {
  navRoot.innerHTML = NAV.map(
    ([key, label]) =>
      `<button type="button" class="${key === currentNav ? "active" : ""}" data-nav="${escapeHtml(key)}">${escapeHtml(label)}</button>`
  ).join("");
  bindNav();
}

function boot() {
  const session = requireSession();
  if (!session) return;
  if (walletPill) walletPill.textContent = shortAddr(session.wallet);
  if (state.unified.sellerStats) state.unified.sellerStats.seller_wallet = session.wallet;
  initNavDom();
  updateSyncLine();
  renderMain();
  document.getElementById("sync-now-btn")?.addEventListener("click", () => runSync());
  syncTimer = window.setInterval(() => runSync(), 45000);
  void runSync();
}

logoutBtn?.addEventListener("click", () => {
  clearAuthSession();
  if (syncTimer) clearInterval(syncTimer);
  location.href = "../web3-login.html?target=studio%2Findex.html";
});

boot();
