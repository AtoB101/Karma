(() => {
  const titles = { dashboard: "Dashboard", receive: "收款区", pay: "付款区", bills: "账单记录", settings: "设置" };
  const API_BASE = new URLSearchParams(window.location.search).get("apiBase") || window.location.origin;
  const API_PREFIX =
    window.__KARMA_API_PREFIX__ ||
    document.body?.dataset?.apiPrefix ||
    "/api/v1";

  let state = null;
  let polling = null;

  function showPage(pageId, btn) {
    document.querySelectorAll(".page").forEach((page) => page.classList.remove("active"));
    document.getElementById(pageId).classList.add("active");
    document.querySelectorAll(".nav button").forEach((button) => button.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById("pageTitle").innerText = titles[pageId];
  }
  window.showPage = showPage;

  function setStatus(msg, ok = true) {
    const el = document.getElementById("statusLine");
    el.textContent = msg;
    el.className = "statusline " + (ok ? "ok" : "err");
  }

  function badge(status) {
    if (status === "Paid") return '<span class="badge badge-success">已付款</span>';
    if (status === "PendingSettle") return '<span class="badge badge-info">待结算</span>';
    if (status === "PendingConfirm") return '<span class="badge badge-warning">待确认</span>';
    return '<span class="badge badge-danger">争议中</span>';
  }

  async function api(path, method = "GET", body) {
    const p = path.startsWith(API_PREFIX) ? path : `${API_PREFIX}${path}`;
    const r = await fetch(`${API_BASE}${p}`, {
      method,
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    });
    const j = await r.json();
    if (!r.ok || j.ok === false) throw new Error(j.message || j.error || `HTTP ${r.status}`);
    return j.data ?? j;
  }

  async function load() {
    const d = await api("/dashboard");
    state = d;
    render();
  }

  function render() {
    if (!state) return;
    const s = state.summary;
    const token = s.wallet.token;
    walletInfo.textContent = `Wallet：${s.wallet.address} · ${token} / USDT`;
    mIncome.textContent = `${Number(s.totals.totalIncome).toFixed(2)} ${token}`;
    mIncomeSub.textContent = `来自 ${(state.activity || []).length} 次 Agent 调用`;
    mExpense.textContent = `${Number(s.totals.totalExpense).toFixed(2)} ${token}`;
    mActive.textContent = `${Number(s.allowance.active).toFixed(2)} ${token}`;
    mPending.textContent = String(s.counts.pendingConfirm || 0);
    pToken.value = s.allowance.token;
    pAllowance.value = String(s.allowance.allowance);
    pActive.value = `${Number(s.allowance.active).toFixed(2)} ${token}`;
    pUsed.value = `${Number((s.allowance.locked || 0) + (s.allowance.reserved || 0)).toFixed(2)} ${token}`;
    pAutoUsed.value = `${Number(s.totals.totalExpense).toFixed(2)} ${token}`;

    activityRows.innerHTML =
      (state.activity || [])
        .map(
          (a) =>
            `<tr><td>${a.time}</td><td>${a.agent}</td><td>${a.action}</td><td>${Number(a.amount || 0).toFixed(2)} ${token}</td><td>${badge(a.status)}</td></tr>`
        )
        .join("") || '<tr><td colspan="5">暂无</td></tr>';

    agentList.innerHTML =
      (state.agents || [])
        .map(
          (a) =>
            `<div class="agent-card"><div><strong>${a.name}</strong><div class="agent-meta">${Number(a.price || 0).toFixed(2)} ${a.token} / 次 · 今日收入 ${Number(a.todayIncome || 0).toFixed(2)} ${a.token}</div></div><div><span class="badge ${a.status === "running" ? "badge-success" : "badge-warning"}">${a.status === "running" ? "运行中" : "暂停"}</span><div class="btn-row"><button class="btn btn-secondary" onclick="toggleAgent('${a.id}','${a.status}')">${a.status === "running" ? "暂停" : "恢复"}</button><button class="btn btn-danger" onclick="removeAgent('${a.id}')">删除</button></div></div></div>`
        )
        .join("") || '<div class="agent-meta">暂无 Agent</div>';

    const pend = (state.bills || []).filter((b) => b.status === "PendingConfirm");
    pendingRows.innerHTML =
      pend
        .map(
          (b) =>
            `<tr><td>${b.callerAgent}</td><td>${b.service}</td><td>策略检查</td><td>${Number(b.amount).toFixed(2)} ${token}</td><td><button class="btn btn-primary" onclick="billAct('${b.id}','confirm')">确认</button> <button class="btn btn-danger" onclick="billAct('${b.id}','reject')">拒绝</button></td></tr>`
        )
        .join("") || '<tr><td colspan="5">暂无待确认</td></tr>';

    billRows.innerHTML = (state.bills || [])
      .map(
        (b) =>
          `<tr><td>${b.id}</td><td>${b.callerAgent}</td><td>${b.seller}</td><td>${Number(b.amount).toFixed(2)} ${token}</td><td>${badge(b.status)}</td><td><button class="btn btn-secondary" onclick="alert('evidence:'+ '${b.id}')">查看证据</button> ${b.status === "PendingSettle" ? `<button class="btn btn-primary" onclick="billAct('${b.id}','settle')">结算</button>` : ""}</td></tr>`
      )
      .join("");
  }

  async function withAction(fn, okMsg) {
    try {
      await fn();
      await load();
      setStatus(okMsg || "操作成功", true);
    } catch (e) {
      setStatus("失败: " + e.message, false);
    }
  }

  async function toggleAgent(id, status) {
    await withAction(
      () => api(`/agents/${id}`, "PATCH", { status: status === "running" ? "paused" : "running" }),
      "Agent 状态已更新"
    );
  }
  window.toggleAgent = toggleAgent;

  async function removeAgent(id) {
    await withAction(() => api(`/agents/${id}`, "DELETE"), "Agent 已删除");
  }
  window.removeAgent = removeAgent;

  async function billAct(id, act) {
    await withAction(() => api(`/bills/${id}/${act}`, "POST", {}), `账单 ${id} 已${act}`);
  }
  window.billAct = billAct;

  btnCreateAgent.onclick = () =>
    withAction(
      () =>
        api("/agents", "POST", {
          name: rName.value || "NewAgent",
          description: rDesc.value || "",
          serviceType: rType.value || "自定义 API",
          endpoint: rEndpoint.value || "",
          price: Number(rPrice.value || 0),
          token: rToken.value || "USDC",
          wallet: rWallet.value || "",
          successOnly: true,
          refundable: false,
          manualConfirm: false,
        }),
      "收费 Agent 已创建"
    );
  btnGenerateCode.onclick = () => {
    navigator.clipboard?.writeText(
      `karma.wrapTool({ endpoint: "${rEndpoint.value || "https://api.example.com"}", price: "${rPrice.value || "0.03"}", token: "${rToken.value || "USDC"}" })`
    );
    setStatus("接入代码已复制", true);
  };
  btnIncAuth.onclick = () =>
    withAction(() => api("/allowance/increase", "POST", { amount: Number(pAllowance.value || 10) }), "授权额度已增加");
  btnStop.onclick = () => withAction(() => api("/allowance/stop", "POST", {}), "已暂停 Agent 消费");
  btnUnlock.onclick = () => setStatus("已解锁未占用额度（模拟）", true);
  btnBatchNow.onclick = () => withAction(() => api("/bills/batch-settle-now", "POST", {}), "批量结算完成");
  btnRefresh.onclick = () => withAction(() => load(), "已刷新");
  btnStopAll.onclick = () => withAction(() => api("/allowance/stop", "POST", {}), "已暂停所有 Agent 消费");

  async function boot() {
    try {
      await load();
      setStatus("前后端同步正常");
    } catch (e) {
      setStatus("初始化失败: " + e.message, false);
    }
    if (polling) clearInterval(polling);
    polling = setInterval(() => load().catch(() => {}), 8000);
  }
  boot();
})();
