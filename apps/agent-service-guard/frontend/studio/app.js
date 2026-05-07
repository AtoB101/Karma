import {
  loadState,
  saveState,
  createAgent,
  updateAllowance,
  updatePushConfig,
  escapeHtml,
  safeText,
} from "./store.js?v=20260506c";

const state = loadState();
const NAV = [
  ["dashboard", "📊 仪表板"],
  ["receive", "💰 收款区 · 开店"],
  ["pay", "💸 付款区 · 授权"],
  ["bills", "📜 账单 & 争议"],
  ["trust", "🏆 Karma 信誉分"],
  ["settings", "⚡ Sparky 设置"],
];

const view = document.getElementById("view");
const nav = document.getElementById("nav");
const title = document.getElementById("page-title");
const toast = document.getElementById("toast");
const walletPill = document.getElementById("wallet-pill");
const logoutBtn = document.getElementById("logout-btn");

const AUTH_SESSION_KEY = "karma_web3_session";

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

function showToast(msg, type = "ok") {
  toast.textContent = msg;
  toast.className = `toast show ${type}`;
  setTimeout(() => {
    toast.className = "toast";
  }, 2400);
}

function setPage(page) {
  location.hash = `#${page}`;
  render();
}

function currentPage() {
  return (location.hash.replace("#", "") || "dashboard");
}

function renderNav(page) {
  nav.innerHTML = NAV.map(([k, label]) => `<button class="nav-item ${k === page ? "active" : ""}" data-page="${k}">${label}</button>`).join("");
  nav.querySelectorAll("[data-page]").forEach((el) => {
    el.addEventListener("click", () => setPage(el.dataset.page));
  });
}

function renderDashboard() {
  const session = loadSession() || {};
  const signaturePreview = session.signature ? `${session.signature.slice(0, 18)}...` : "N/A";
  return `
    <div class="card">
      <h3>Karma Agent Studio</h3>
      <div class="muted">公开版用户端（演示）</div>
      <div class="muted">Web3 登录：${escapeHtml(session.loginMethod || "unknown")} · Chain: ${escapeHtml(session.chainId || "unknown")}</div>
      <div class="muted">签名摘要：${escapeHtml(signaturePreview)}</div>
    </div>
    <div class="row">
      <div class="card"><strong>总收入</strong><div>1,280.45 USDC</div></div>
      <div class="card"><strong>总支出</strong><div>342.80 USDC</div></div>
      <div class="card"><strong>可用额度</strong><div>902.65 USDC</div></div>
      <div class="card"><strong>待确认账单</strong><div>12</div></div>
    </div>
  `;
}

function renderReceive() {
  const cards = state.agents
    .map((a) => `<div class="card">
      <div><strong>${escapeHtml(a.name)}</strong> <span class="muted">信誉分 ${a.trust}</span></div>
      <div class="muted">价格 ${a.price} USDC · 调用 ${a.totalCalls}</div>
      <div><code>${escapeHtml(a.shareLink)}</code></div>
      <button data-copy="${escapeHtml(a.shareLink)}">复制收款链接</button>
    </div>`)
    .join("");
  return `
    <div class="card">
      <h3>创建 Agent</h3>
      <div class="row">
        <input id="new-agent-name" placeholder="Agent 名称" />
        <input id="new-agent-price" type="number" step="0.01" min="0.01" placeholder="单次价格 USDC" />
      </div>
      <div style="margin-top:10px"><button id="create-agent-btn">一键注册新 Agent</button></div>
    </div>
    ${cards}
  `;
}

function renderPay() {
  const rows = state.allowances
    .map(
      (a) => `<tr>
      <td>${escapeHtml(a.agentName)}</td>
      <td><input data-agent="${a.agentId}" data-key="perTxLimit" type="number" step="0.01" value="${a.perTxLimit}"></td>
      <td><input data-agent="${a.agentId}" data-key="dailyLimit" type="number" step="0.01" value="${a.dailyLimit}"></td>
      <td>${a.usedThisMonth}/${a.totalAssigned}</td>
    </tr>`
    )
    .join("");
  return `<div class="card"><h3>额度配置</h3><table><thead><tr><th>Agent</th><th>单笔上限</th><th>日累计上限</th><th>使用</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function renderBills() {
  const rows = state.bills.map((b) => `<tr><td>${escapeHtml(b.id)}</td><td>${escapeHtml(b.caller)}</td><td>${escapeHtml(b.receiver)}</td><td>${b.amount} USDC</td><td>${escapeHtml(b.status)}</td></tr>`).join("");
  return `<div class="card"><h3>账单与争议</h3><table><thead><tr><th>ID</th><th>调用方</th><th>收款方</th><th>金额</th><th>状态</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function renderTrust() {
  return state.agents.map((a) => `<div class="card"><strong>${escapeHtml(a.name)}</strong><div class="muted">信誉分 ${a.trust} · ${a.trust >= 70 ? "自动微额" : "需人工确认"}</div></div>`).join("");
}

function renderSettings() {
  const cfg = state.pushConfig;
  return `<div class="card">
    <h3>Sparky 推送配置</h3>
    <div class="muted">安全策略：不在浏览器持久化保存 token，仅保存通道与接收目标。</div>
    <div class="row" style="margin-top:10px">
      <select id="push-channel">
        <option value="whatsapp" ${cfg.channel === "whatsapp" ? "selected" : ""}>WhatsApp</option>
        <option value="telegram" ${cfg.channel === "telegram" ? "selected" : ""}>Telegram</option>
        <option value="wechat" ${cfg.channel === "wechat" ? "selected" : ""}>微信</option>
      </select>
      <input id="push-destination" value="${escapeHtml(cfg.destination)}" placeholder="手机号 / chat_id / openid" />
    </div>
    <div class="row" style="margin-top:10px">
      <input id="push-token" placeholder="临时 token（不会写入 localStorage）" />
      <button id="save-push">保存配置</button>
      <button id="test-push">发送测试</button>
    </div>
  </div>`;
}

function bindPageEvents(page) {
  if (page === "receive") {
    document.getElementById("create-agent-btn")?.addEventListener("click", () => {
      const name = safeText(document.getElementById("new-agent-name")?.value || "", 40);
      const price = Number(document.getElementById("new-agent-price")?.value || 0);
      if (!name || !Number.isFinite(price) || price <= 0) return showToast("请输入有效 Agent 名称与价格", "error");
      createAgent(state, { name, price });
      saveState(state);
      showToast("Agent 创建成功");
      render();
    });
    view.querySelectorAll("[data-copy]").forEach((el) => {
      el.addEventListener("click", async () => {
        await navigator.clipboard.writeText(el.dataset.copy || "");
        showToast("收款链接已复制");
      });
    });
  }
  if (page === "pay") {
    view.querySelectorAll("input[data-agent]").forEach((el) => {
      el.addEventListener("change", () => {
        const next = Number(el.value || 0);
        if (next < 0) return;
        updateAllowance(state, el.dataset.agent, el.dataset.key, next);
        saveState(state);
        showToast("额度已更新");
      });
    });
  }
  if (page === "settings") {
    document.getElementById("save-push")?.addEventListener("click", () => {
      const channel = document.getElementById("push-channel").value;
      const destination = safeText(document.getElementById("push-destination").value, 64);
      updatePushConfig(state, { channel, destination });
      saveState(state);
      showToast("配置已保存（未持久化 token）");
    });
    document.getElementById("test-push")?.addEventListener("click", async () => {
      const token = document.getElementById("push-token").value.trim();
      const payload = { channel: state.pushConfig.channel, destination: state.pushConfig.destination, message: "Sparky test ping" };
      try {
        await fetch("/api/notifications/test", {
          method: "POST",
          headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
          body: JSON.stringify(payload),
        });
        showToast("已发送测试请求（mock）");
      } catch {
        showToast("测试请求已触发（本地无后端）", "warn");
      }
    });
  }
}

function render() {
  const session = requireSession();
  if (!session) return;
  if (walletPill) walletPill.textContent = session.wallet;
  const page = NAV.map(([k]) => k).includes(currentPage()) ? currentPage() : "dashboard";
  title.textContent = NAV.find(([k]) => k === page)?.[1] || "Karma Agent Studio";
  renderNav(page);
  if (page === "dashboard") view.innerHTML = renderDashboard();
  if (page === "receive") view.innerHTML = renderReceive();
  if (page === "pay") view.innerHTML = renderPay();
  if (page === "bills") view.innerHTML = renderBills();
  if (page === "trust") view.innerHTML = renderTrust();
  if (page === "settings") view.innerHTML = renderSettings();
  bindPageEvents(page);
}

window.addEventListener("hashchange", render);
logoutBtn?.addEventListener("click", () => {
  clearAuthSession();
  location.href = "../web3-login.html?target=studio%2Findex.html";
});
render();
