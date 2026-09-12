/**
 * Cyber console — navigation, i18n, API binding (capacity + settlement lookup).
 */
(function () {
  const LS_BASE = "karma_cyber_api_base";
  const LS_KEY = "karma_cyber_api_key";
  const LS_ID = "karma_cyber_identity_id";
  const LS_TASKS = "karma_console_task_ids";
  const LS_AUTO = "karma_console_auto_sync";

  const pages = {
    overview: ["page.overview.title", "page.overview.sub"],
    center: ["page.center.title", "page.center.sub"],
    tasks: ["page.tasks.title", "page.tasks.sub"],
    receipts: ["page.receipts.title", "page.receipts.sub"],
    bills: ["page.bills.title", "page.bills.sub"],
    disputes: ["page.disputes.title", "page.disputes.sub"],
    identity: ["page.identity.title", "page.identity.sub"],
    auth: ["page.auth.title", "page.auth.sub"],
    agents: ["page.agents.title", "page.agents.sub"],
    settings: ["page.settings.title", "page.settings.sub"],
  };

  function el(sel) {
    return document.querySelector(sel);
  }

  function isLocalPage() {
    const h = window.location.hostname;
    return h === "localhost" || h === "127.0.0.1" || h === "::1" || h === "";
  }

  /** A base saved during local development must not follow us onto a real host. */
  function isForeignLocalhost(base) {
    if (isLocalPage()) return false;
    try {
      const host = new URL(base, window.location.href).hostname;
      return host === "localhost" || host === "127.0.0.1" || host === "::1" || host === "0.0.0.0";
    } catch (_) {
      return false;
    }
  }

  /**
   * Effective API base for this page: a saved override, else window.KARMA_API_BASE
   * ("" = same-origin), else the local dev API on localhost and this origin in production.
   */
  function displayBase() {
    let stored = "";
    try {
      stored = localStorage.getItem(LS_BASE) || "";
    } catch (_) {}
    if (stored && !isForeignLocalhost(stored)) return stored;
    const raw = window.KARMA_API_BASE;
    if (raw === undefined || raw === null || String(raw).trim() === "") {
      return isLocalPage() ? "http://127.0.0.1:8000" : window.location.origin;
    }
    return String(raw).trim();
  }

  function loadCfgIntoInputs() {
    try {
      if (el("[data-cfg=api_base]")) el("[data-cfg=api_base]").value = displayBase();
      if (el("[data-cfg=api_key]"))
        el("[data-cfg=api_key]").value =
          sessionStorage.getItem(LS_KEY) || localStorage.getItem(LS_KEY) || window.KARMA_API_KEY || "";
      if (el("[data-cfg=identity_id]"))
        el("[data-cfg=identity_id]").value =
          sessionStorage.getItem(LS_ID) || localStorage.getItem(LS_ID) || window.KARMA_IDENTITY_ID || "";
      if (el("[data-cfg=task_ids]"))
        el("[data-cfg=task_ids]").value = localStorage.getItem(LS_TASKS) || "";
      if (el("[data-cfg=auto_sync]")) el("[data-cfg=auto_sync]").checked = localStorage.getItem(LS_AUTO) === "1";
    } catch (_) {}
  }

  function saveCfg() {
    const base = el("[data-cfg=api_base]")?.value?.trim() || "";
    const key = el("[data-cfg=api_key]")?.value?.trim() || "";
    const id = el("[data-cfg=identity_id]")?.value?.trim() || "";
    const tasks = el("[data-cfg=task_ids]")?.value?.trim() || "";
    const auto = el("[data-cfg=auto_sync]")?.checked;
    try {
      localStorage.setItem(LS_BASE, base);
      // Security: API key / identity are session-only, never persisted long-term.
      sessionStorage.setItem(LS_KEY, key);
      sessionStorage.setItem(LS_ID, id);
      localStorage.setItem(LS_TASKS, tasks);
      if (auto !== undefined) localStorage.setItem(LS_AUTO, auto ? "1" : "");
    } catch (_) {}
    window.KARMA_API_BASE = base;
    window.KARMA_API_KEY = key;
    window.KARMA_IDENTITY_ID = id;
    const mainId = el(".id-main");
    if (mainId && id) mainId.textContent = id;
    setApiStatus(window.CYBER_I18N.t("api.status_ok") + " — " + base, false);
  }

  function setApiStatus(msg, isErr) {
    const n = el("[data-api-status]");
    if (!n) return;
    n.textContent = msg;
    n.classList.toggle("err", !!isErr);
  }

  function fmtNum(x) {
    const n = Number(x);
    if (Number.isNaN(n)) return "—";
    return n.toFixed(2);
  }

  async function refreshCapacity() {
    const id = el("[data-cfg=identity_id]")?.value?.trim() || String(window.KARMA_IDENTITY_ID || "").trim();
    if (!id) {
      setApiStatus("Identity ID empty", true);
      return;
    }
    setApiStatus("…", false);
    try {
      const c = await window.cyberKarmaApi.getCapacity(id);
      const map = [
        ["[data-bind=total_locked_usdc]", c.total_locked_usdc],
        ["[data-bind=available_credits]", c.available_credits],
        ["[data-bind=in_progress_bucket]", (c.in_progress_credits || 0) + (c.reserved_credits || 0)],
        ["[data-bind=pending_settlement_credits]", c.pending_settlement_credits],
        ["[data-bind=disputed_credits]", c.disputed_credits],
      ];
      map.forEach(function (row) {
        const node = el(row[0]);
        if (node) node.textContent = fmtNum(row[1]);
      });
      setApiStatus(window.CYBER_I18N.t("api.status_ok") + " · capacity @" + new Date().toLocaleTimeString(), false);
      document.dispatchEvent(new CustomEvent("karma-capacity-changed", { detail: c }));
    } catch (e) {
      setApiStatus(String(e.message || e), true);
    }
  }

  async function fetchSettlement() {
    const tid = el("[data-cfg=task_id]")?.value?.trim();
    const out = el("[data-settlement-preview]");
    if (!tid) {
      if (out) out.textContent = "task id empty";
      return;
    }
    if (out) out.textContent = "…";
    try {
      const s = await window.cyberKarmaApi.getSettlement(tid);
      if (out) out.textContent = JSON.stringify(s, null, 2);
      setApiStatus("settlement loaded", false);
    } catch (e) {
      if (out) out.textContent = String(e.message || e);
      setApiStatus(String(e.message || e), true);
    }
  }

  /* ------------------------------------------------------------------
   * 链上锁仓（用户钱包签名，Karma 全程不接触私钥/助记词）
   *
   * 用户钱包自己签 approve + lock 两笔交易，后端只读交易回执、按链上
   * BillMinted 事件入账。选择器是 KarmaBilateral.sol / ERC-20 精确签名的
   * keccak 前 4 字节，由 tests/unit/test_chain_wallet_lock.py 对齐校验。
   * ------------------------------------------------------------------ */
  const CHAIN_SELECTORS = {
    approve: "0x095ea7b3", // approve(address,uint256)
    allowance: "0xdd62ed3e", // allowance(address,address)
    lock: "0x282d3fdf", // lock(address,uint256)
    unlock: "0x6198e339", // unlock(uint256)
  };

  let chainCache = { id: "", payload: null };

  function pad32(hex) {
    return String(hex).replace(/^0x/, "").toLowerCase().padStart(64, "0");
  }

  /** 人类金额 → 代币最小单位，走字符串运算，避免浮点误差。 */
  function toBaseUnits(amount, decimals) {
    const text = String(amount).trim();
    const m = /^(\d+)(?:\.(\d*))?$/.exec(text);
    if (!m) throw new Error("金额格式不正确：" + text);
    const frac = (m[2] || "").slice(0, decimals).padEnd(decimals, "0");
    return BigInt(m[1] + frac);
  }

  function walletProvider() {
    const auth = window.KarmaWalletAuth;
    if (!auth || typeof auth.activeProvider !== "function") return null;
    try {
      return auth.activeProvider();
    } catch (_) {
      return null;
    }
  }

  async function rpc(provider, method, params) {
    return provider.request({ method: method, params: params || [] });
  }

  async function loadChainInfo(id, force) {
    if (!force && chainCache.id === id && chainCache.payload) return chainCache.payload;
    const payload = await window.cyberKarmaApi.getChainLockState(id);
    chainCache = { id: id, payload: payload };
    return payload;
  }

  async function ensureChainId(provider, chainId) {
    const want = "0x" + Number(chainId).toString(16);
    let current = "";
    try {
      current = String((await rpc(provider, "eth_chainId")) || "").toLowerCase();
    } catch (_) {}
    if (current === want) return;
    try {
      await rpc(provider, "wallet_switchEthereumChain", [{ chainId: want }]);
    } catch (_) {
      throw new Error("请先把钱包切到 chainId " + chainId + " 的网络再重试（钱包里还没有这条链时需要先添加）");
    }
  }

  async function waitReceipt(provider, txHash, timeoutMs) {
    const deadline = Date.now() + (timeoutMs || 180000);
    while (Date.now() < deadline) {
      const receipt = await rpc(provider, "eth_getTransactionReceipt", [txHash]).catch(function () {
        return null;
      });
      if (receipt && receipt.blockNumber) return receipt;
      await new Promise(function (res) {
        setTimeout(res, 2500);
      });
    }
    throw new Error("等待链上确认超时，交易已提交：" + txHash + "（稍后刷新账单会自动入账）");
  }

  async function onchainLock(id, amount, info) {
    const chain = (info && info.chain) || {};
    const provider = walletProvider();
    if (!provider) throw new Error("未检测到钱包：请先点「连接钱包」");
    await ensureChainId(provider, chain.chain_id);
    const accounts = await rpc(provider, "eth_accounts");
    const from = accounts && accounts[0];
    if (!from) throw new Error("钱包还没有授权账户，请重新连接钱包");

    const decimals = Number(chain.token_decimals || 6);
    const units = toBaseUnits(amount, decimals);
    const token = chain.token_address;
    const contract = chain.contract_address;

    setApiStatus("检查 USDC 授权额度…", false);
    const allowance = await rpc(provider, "eth_call", [
      {
        to: token,
        data: CHAIN_SELECTORS.allowance + pad32(from) + pad32(contract),
      },
      "latest",
    ]);
    if (BigInt(allowance || "0x0") < units) {
      setApiStatus("第 1 / 2 步：在钱包里授权 " + amount + " USDC（只授权本次金额）…", false);
      const approveTx = await rpc(provider, "eth_sendTransaction", [
        {
          from: from,
          to: token,
          data: CHAIN_SELECTORS.approve + pad32(contract) + pad32(units.toString(16)),
        },
      ]);
      await waitReceipt(provider, approveTx, 180000);
    }

    setApiStatus("第 2 / 2 步：在钱包里确认锁仓 " + amount + " USDC…", false);
    const lockTx = await rpc(provider, "eth_sendTransaction", [
      {
        from: from,
        to: contract,
        data: CHAIN_SELECTORS.lock + pad32(token) + pad32(units.toString(16)),
      },
    ]);
    await waitReceipt(provider, lockTx, 240000);

    setApiStatus("链上已确认，正在入账…", false);
    const state = await window.cyberKarmaApi.claimBill(id, lockTx);
    return { state: state, txHash: lockTx, billId: units.toString() };
  }

  async function onchainUnlock(id, billId) {
    const info = await loadChainInfo(id);
    const chain = (info && info.chain) || {};
    const provider = walletProvider();
    if (!provider) throw new Error("未检测到钱包：请先点「连接钱包」");
    await ensureChainId(provider, chain.chain_id);
    const accounts = await rpc(provider, "eth_accounts");
    const from = accounts && accounts[0];
    if (!from) throw new Error("钱包还没有授权账户，请重新连接钱包");
    const tx = await rpc(provider, "eth_sendTransaction", [
      {
        from: from,
        to: chain.contract_address,
        data: CHAIN_SELECTORS.unlock + pad32(BigInt(billId).toString(16)),
      },
    ]);
    await waitReceipt(provider, tx, 240000);
    const state = await window.cyberKarmaApi.claimUnlock(id, String(billId), tx);
    return { state: state, txHash: tx };
  }

  /* ------------------------------------------------------------------
   * v2 授权额度（allowance escrow）— 资金始终留在用户自己的钱包里
   *
   * 用户只签一次 approve + commit：approve 给结算合约一个额度，commit 把
   * 「我承诺最多支付 X」登记上链，钱不转账。之后 agent 接单、验证、划转全
   * 部按 Karma 规则自动执行，用户不需要再签任何一笔；用户随时可以自己签
   * revoke 撤销，或在钱包里把 approve 改成 0 —— 那之后任何划转都不成立。
   *
   * 选择器是 KarmaAllowanceEscrow.sol / ERC-20 精确签名的 keccak 前 4 字节，
   * 由 tests/unit/test_allowance_escrow.py 对齐校验。
   * ------------------------------------------------------------------ */
  const ESCROW_SELECTORS = {
    approve: "0x095ea7b3", // approve(address,uint256)
    allowance: "0xdd62ed3e", // allowance(address,address)
    commit: "0xd6e9d0c4", // commit(address,uint256,address)
    revoke: "0x20c5429b", // revoke(uint256)
  };
  const ZERO_ADDR = "0x0000000000000000000000000000000000000000";

  let escrowCache = { id: "", payload: null };

  async function loadEscrowInfo(id, force) {
    if (!force && escrowCache.id === id && escrowCache.payload) return escrowCache.payload;
    const payload = await window.cyberKarmaApi.getEscrowState(id);
    escrowCache = { id: id, payload: payload };
    return payload;
  }

  async function onchainCommit(id, amount, info) {
    const escrow = (info && info.escrow) || {};
    const provider = walletProvider();
    if (!provider) throw new Error("未检测到钱包：请先点「连接钱包」");
    await ensureChainId(provider, escrow.chain_id);
    const accounts = await rpc(provider, "eth_accounts");
    const from = accounts && accounts[0];
    if (!from) throw new Error("钱包还没有授权账户，请重新连接钱包");

    const decimals = Number(escrow.token_decimals || 6);
    const units = toBaseUnits(amount, decimals);
    const token = escrow.token_address;
    const contract = escrow.contract_address;
    const operator = escrow.operator_address || ZERO_ADDR;

    const allowance = await rpc(provider, "eth_call", [
      { to: token, data: ESCROW_SELECTORS.allowance + pad32(from) + pad32(contract) },
      "latest",
    ]);
    if (BigInt(allowance || "0x0") < units) {
      setApiStatus("第 1 / 2 步：在钱包里确认授权额度（只授权，不转账）…", false);
      const approveTx = await rpc(provider, "eth_sendTransaction", [
        {
          from: from,
          to: token,
          data: ESCROW_SELECTORS.approve + pad32(contract) + pad32(units.toString(16)),
        },
      ]);
      await waitReceipt(provider, approveTx, 180000);
    }

    setApiStatus("第 2 / 2 步：在钱包里确认承诺 " + amount + " USDC 的支付额度…", false);
    const commitTx = await rpc(provider, "eth_sendTransaction", [
      {
        from: from,
        to: contract,
        data: ESCROW_SELECTORS.commit + pad32(token) + pad32(units.toString(16)) + pad32(operator),
      },
    ]);
    await waitReceipt(provider, commitTx, 240000);

    setApiStatus("已上链，正在登记授权…", false);
    const state = await window.cyberKarmaApi.claimCommit(id, commitTx);
    return {
      state: state,
      txHash: commitTx,
      billId: (state && state.commit && state.commit.bill_id) || "",
    };
  }

  async function onchainEscrowRevoke(id, billId) {
    const info = await loadEscrowInfo(id);
    const escrow = (info && info.escrow) || {};
    const provider = walletProvider();
    if (!provider) throw new Error("未检测到钱包：请先点「连接钱包」");
    await ensureChainId(provider, escrow.chain_id);
    const accounts = await rpc(provider, "eth_accounts");
    const from = accounts && accounts[0];
    if (!from) throw new Error("钱包还没有授权账户，请重新连接钱包");
    const tx = await rpc(provider, "eth_sendTransaction", [
      {
        from: from,
        to: escrow.contract_address,
        data: ESCROW_SELECTORS.revoke + pad32(BigInt(billId).toString(16)),
      },
    ]);
    await waitReceipt(provider, tx, 240000);
    const state = await window.cyberKarmaApi.claimEscrowRevoke(id, String(billId), tx);
    return { state: state, txHash: tx };
  }

  async function lockCapacityAction(amountOverride) {
    const id = (el("[data-cfg=identity_id]")?.value || "").trim() || window.KARMA_IDENTITY_ID || "";
    const amount =
      amountOverride === undefined || amountOverride === null
        ? Number(el("#lock-amount")?.value || 0)
        : Number(amountOverride);
    if (!id) { setApiStatus("请先连接钱包或填写 Identity ID", true); return; }
    if (!amount || amount <= 0) { setApiStatus("请填写锁仓金额", true); return; }

    let info = null;
    try {
      info = await loadChainInfo(id);
    } catch (_) {
      info = null;
    }
    let escrowInfo = null;
    try {
      escrowInfo = await loadEscrowInfo(id);
    } catch (_) {
      escrowInfo = null;
    }
    /* v2 优先：资金不转账，只是授权额度；没有 v2 时才回落到 v1 锁仓。 */
    if (escrowInfo && escrowInfo.escrow && escrowInfo.escrow.enabled) {
      if (!walletProvider()) {
        setApiStatus("授权额度需要钱包签名：请先点「连接钱包」，再回来授权", true);
        return;
      }
      try {
        const r = await onchainCommit(id, amount, escrowInfo);
        setApiStatus("已授权 " + amount + " USDC 支付额度 · 资金仍在你的钱包里", false);
        await refreshCapacity();
        document.dispatchEvent(
          new CustomEvent("karma-locked", { detail: { amount: amount, onchain: true, escrow: true } })
        );
        refreshEscrowCommits(true).catch(function () {});
        return r;
      } catch (e) {
        setApiStatus(String(e.message || e), true);
        return;
      }
    }
    if (info && info.chain && info.chain.enabled) {
      if (!walletProvider()) {
        setApiStatus("链上锁仓需要钱包签名：请先点「连接钱包」，再回来锁仓", true);
        return;
      }
      try {
        const r = await onchainLock(id, amount, info);
        setApiStatus("锁仓成功 · " + amount + " USDC 已上链并入账", false);
        await refreshCapacity();
        document.dispatchEvent(
          new CustomEvent("karma-locked", { detail: { amount: amount, onchain: true } })
        );
        refreshChainBills(true).catch(function () {});
        return r;
      } catch (e) {
        setApiStatus(String(e.message || e), true);
        return;
      }
    }

    // 链上未配置：保留台账模式，但必须明确标注，不能假装是真钱。
    setApiStatus("台账模式锁仓中…（未配置链上合约，不产生真实转账）", false);
    try {
      const r = await window.cyberKarmaApi.lockCapacity(id, amount);
      setApiStatus("已记账 · " + amount + " USDC（台账模式 · 无链上资金）", false);
      await refreshCapacity();
      document.dispatchEvent(
        new CustomEvent("karma-locked", { detail: { amount: amount, onchain: false } })
      );
      return r;
    } catch (e) {
      setApiStatus(String(e.message || e), true);
    }
  }

  /** 一键锁仓：点快捷金额就直接锁，不用再点一次按钮。 */
  function lockPreset(amount) {
    const input = el("#lock-amount");
    if (input) input.value = String(amount);
    return lockCapacityAction(amount);
  }

  /**
   * 起步引导 — 连接钱包后只需要三步。卡片在有身份卡之前不出现，
   * 每一步显示实时状态，而不是一条用户无法确认的待办。
   */
  async function renderLaunchGuide() {
    const card = el("#launch-guide");
    if (!card) return;
    const id =
      (el("[data-cfg=identity_id]")?.value || "").trim() || String(window.KARMA_IDENTITY_ID || "").trim();
    if (!id) { card.hidden = true; return; }
    const set = function (sel, txt) { const n = el(sel); if (n) n.textContent = txt; };

    let cap = null;
    try { cap = await window.cyberKarmaApi.getCapacity(id); } catch (_) {}
    let escrow = null;
    try { escrow = await window.cyberKarmaApi.getEscrowState(id); } catch (_) {}
    const ledger = cap ? Number(cap.total_locked_usdc || 0) : 0;
    // v2 是非托管的：钱一直在用户自己钱包里，capacity 台账会是 0，
    // 真正压在这张卡上的是钱包给出的有效 commit。两者取大，才不会被台账骗到。
    const committed = escrow ? Number(escrow.committed_usdc || 0) : 0;
    const locked = Math.max(ledger, committed);
    let chainInfo = null;
    try {
      chainInfo = await loadChainInfo(id);
    } catch (_) {
      chainInfo = null;
    }
    const chainOn = !!(chainInfo && chainInfo.chain && chainInfo.chain.enabled);
    if (locked <= 0) {
      set(
        "#launch-lock-state",
        chainOn
          ? "还没有授权额度（点击下面金额，钱包会签 2 笔交易；钱不转走，仍在你钱包里）"
          : "还没有锁仓"
      );
    } else if (committed > 0 && committed >= ledger) {
      set(
        "#launch-lock-state",
        "已授权额度 " + fmtNum(committed) + " USDC（非托管：USDC 一直在你钱包里，Karma 只拿到授权）"
      );
    } else if (chainOn) {
      const onchain = Number(chainInfo.onchain_locked_usdc || 0);
      const gap = locked - onchain;
      set(
        "#launch-lock-state",
        "链上锁仓 " + fmtNum(onchain) + " USDC" +
          (gap > 1e-9 ? " · 另有 " + fmtNum(gap) + " 为台账额度（无链上资金）" : " · 已 100% 链上锚定")
      );
    } else {
      set("#launch-lock-state", "已锁仓 " + fmtNum(locked) + " USDC（台账模式：未配置链上合约）");
    }

    let profiles = [];
    try {
      const pb = await window.cyberKarmaApi.listRoleProfiles(id);
      profiles = (pb && pb.profiles) || [];
    } catch (_) {}
    let allocs = [];
    try {
      const rb = await window.cyberKarmaApi.getAllocations(id);
      allocs = (rb && rb.allocations) || [];
    } catch (_) {}
    const funded = allocs.filter(function (a) { return Number(a.allocated_credits || 0) > 0; });
    if (!profiles.length) {
      set("#launch-alloc-state", "还没有子身份档案，先到「身份」页创建");
    } else if (locked <= 0) {
      set("#launch-alloc-state", profiles.length + " 个子身份 · 先完成第 1 步");
    } else {
      set("#launch-alloc-state", funded.length + " / " + profiles.length + " 个子身份已授权额度");
    }

    let agents = [];
    try {
      const ab = await window.cyberKarmaApi.listMyAgents();
      agents = (ab && ab.agents) || [];
    } catch (_) {}
    // SIWE 会给身份卡自动建一个自身台账 agent（agent_id === owner_identity_id），
    // 它不是用户接入的 agent；把它算进来会让第 3 步在刚连接时就显示「已接入」。
    const onboarded = agents.filter(function (a) { return a.agent_id !== a.owner_identity_id; });
    set("#launch-sdk-state", onboarded.length ? onboarded.length + " 个 agent 已接入" : "还没有 agent 接入");
    // 先把三步状态算完再显示，否则卡片会先闪一下「—」再变成真实数字。
    card.hidden = false;
  }

  function bindLaunchGuide() {
    document.querySelectorAll("[data-lock-preset]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const v = Number(btn.getAttribute("data-lock-preset"));
        if (v > 0) lockPreset(v);
      });
    });
  }

  /**
   * 链上锁仓记录 — 每笔真实 USDC 一个 Bill，可直接提取（unlock）。
   * 台账模式的锁仓不会出现在这里，这正是要让人一眼看清的地方。
   */
  async function refreshChainBills(force) {
    const host = el("#chain-bills");
    if (!host) return;
    const id = (el("[data-cfg=identity_id]")?.value || "").trim() || window.KARMA_IDENTITY_ID || "";
    if (!id) { host.innerHTML = ""; return; }
    let info = null;
    try {
      info = await loadChainInfo(id, !!force);
    } catch (_) {
      info = null;
    }
    const chain = (info && info.chain) || {};
    if (!chain.enabled) {
      const missing = (chain.missing_config || []).join("、");
      host.innerHTML =
        '<p class="ag-hint">链上锁仓未启用' +
        (missing ? "（缺少配置：" + missing + "）" : "") +
        '：当前锁仓走台账模式，没有真实 USDC 进入合约。</p>';
      return;
    }
    const bills = (info && info.bills) || [];
    if (!bills.length) {
      host.innerHTML =
        '<p class="ag-hint">还没有链上锁仓记录。点「增加锁仓额度」后，钱包会先签 approve、再签 lock，' +
        '确认后这里会出现真实的 Bill。</p>';
      return;
    }
    const stake = (info && info.stake) || {};
    const stakePercent = (Number(stake.required_bps || 0) / 100).toFixed(0);
    const stakeLine =
      '<p class="ag-hint">卖家质押池：空闲 ' +
      fmtNum(stake.idle_usdc) +
      " USDC · 已被订单锁定 " +
      fmtNum(stake.reserved_usdc) +
      " USDC · 每单默认质押 " +
      stakePercent +
      "% 客单价（例：100 USDC 的单需 30 USDC，接单时由 Karma 规则自动从池里锁定，不用每单签名）</p>";
    const rows = bills
      .map(function (b) {
        const link = chain.explorer_url
          ? '<a href="' + chain.explorer_url + '/tx/' + b.lock_tx_hash + '" target="_blank" rel="noopener">交易</a>'
          : "";
        const state = b.state === "locked" ? "锁仓中" : "已提取";
        const btn =
          b.state === "locked"
            ? '<button type="button" class="btn" data-unlock-bill="' + b.bill_id + '">提取</button>'
            : "";
        return (
          '<div style="display:flex;gap:10px;align-items:center;justify-content:space-between;' +
          'padding:8px 10px;border:1px solid rgba(34,211,238,0.18);border-radius:10px;margin-bottom:6px">' +
          "<span>Bill #" + b.bill_id + " · " + fmtNum(b.amount_usdc) + " USDC · " + state + "</span>" +
          '<span style="display:flex;gap:10px;align-items:center">' + link + btn + "</span></div>"
        );
      })
      .join("");
    host.innerHTML =
      '<h4 style="margin:0 0 8px">链上锁仓记录（真实 USDC）</h4>' + stakeLine + rows;
    host.querySelectorAll("[data-unlock-bill]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const billId = btn.getAttribute("data-unlock-bill");
        btn.disabled = true;
        setApiStatus("请在钱包里确认提取（unlock）…", false);
        onchainUnlock(id, billId)
          .then(function () {
            setApiStatus("已提取 Bill #" + billId + " 的 USDC", false);
            return refreshCapacity();
          })
          .then(function () {
            return refreshChainBills(true);
          })
          .catch(function (e) {
            setApiStatus(String(e.message || e), true);
            btn.disabled = false;
          });
      });
    });
  }

  /**
   * 支付授权记录（v2）— 钱一直留在用户钱包里，这里显示的是「承诺额度」。
   *
   * 每行都从链上回读：额度不足（用户把 approve 调小了、或余额不够）时会
   * 明确标成「额度不足」，不会假装这笔钱还在。
   */
  async function refreshEscrowCommits(force) {
    const host = el("#escrow-commits");
    if (!host) return;
    const id = (el("[data-cfg=identity_id]")?.value || "").trim() || window.KARMA_IDENTITY_ID || "";
    if (!id) { host.innerHTML = ""; return; }
    let info = null;
    try {
      info = await loadEscrowInfo(id, !!force);
    } catch (_) {
      info = null;
    }
    const escrow = (info && info.escrow) || {};
    if (!escrow.enabled) {
      const missing = (escrow.missing_config || []).join("、");
      host.innerHTML =
        '<h4 style="margin:0 0 8px">支付授权（资金留在你的钱包）</h4>' +
        '<p class="ag-hint">授权额度模式未启用' +
        (missing ? "（缺少配置：" + missing + "）" : "") +
        "：当前走链上锁仓模式。</p>";
      return;
    }
    const commits = (info && info.commits) || [];
    const live = commits.filter(function (c) { return c.state !== "revoked"; });
    const spent = Number((info && info.spent_usdc) || 0);
    const reserved = live.reduce(function (a, c) { return a + Number(c.reserved_usdc || 0); }, 0);
    const head =
      '<h4 style="margin:0 0 8px">支付授权（资金留在你的钱包）</h4>' +
      '<p class="ag-hint">已承诺 ' + fmtNum((info && info.committed_usdc) || 0) + " USDC · 已支付 " + fmtNum(spent) +
      " USDC · 已被订单锁定 " + fmtNum(reserved) + " USDC · 争议窗口 " +
      Number(escrow.dispute_window_seconds || 0) + " 秒" +
      (escrow.can_server_settle
        ? " · Karma 结算账户已就位（验证通过后自动划转，无需你再签名）"
        : " · 结算账户未配置：暂时需要 agent 自行提交结算") +
      "</p>";
    if (!commits.length) {
      host.innerHTML = head +
        '<p class="ag-hint">还没有授权额度。点「增加锁仓额度」后，钱包会签 approve + commit 两笔，' +
        "钱不会转走，只是允许 Karma 在你验证通过后最多划走这么多。</p>";
      return;
    }
    const rows = commits
      .map(function (c) {
        const link = escrow.explorer_url
          ? '<a href="' + escrow.explorer_url + "/tx/" + c.commit_tx_hash + '" target="_blank" rel="noopener">交易</a>'
          : "";
        const stateText =
          c.state === "revoked"
            ? "已撤销"
            : c.backed
              ? "有效"
              : "额度不足（钱包余额或授权不足）";
        const btn =
          c.state === "revoked"
            ? ""
            : '<button type="button" class="btn" data-revoke-commit="' + c.bill_id + '">撤销授权</button>';
        return (
          '<div style="display:flex;gap:10px;align-items:center;justify-content:space-between;' +
          'padding:8px 10px;border:1px solid rgba(34,211,238,0.18);border-radius:10px;margin-bottom:6px">' +
          "<span>承诺 #" + c.bill_id + " · 额度 " + fmtNum(c.amount_usdc) + " USDC · 已用 " +
          fmtNum(c.spent_usdc) + " · 可用 " + fmtNum(c.available_usdc) + " · " + stateText + "</span>" +
          '<span style="display:flex;gap:10px;align-items:center">' + link + btn + "</span></div>"
        );
      })
      .join("");
    host.innerHTML = head + rows;
    host.querySelectorAll("[data-revoke-commit]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const billId = btn.getAttribute("data-revoke-commit");
        btn.disabled = true;
        setApiStatus("请在钱包里确认撤销授权…", false);
        onchainEscrowRevoke(id, billId)
          .then(function () {
            setApiStatus("已撤销承诺 #" + billId, false);
            return refreshEscrowCommits(true);
          })
          .catch(function (e) {
            setApiStatus(String(e.message || e), true);
            btn.disabled = false;
          });
      });
    });
  }

  window.KarmaChainBills = { refresh: refreshChainBills };
  window.KarmaEscrow = { refresh: refreshEscrowCommits };

  async function releaseCapacityAction() {
    const id = (el("[data-cfg=identity_id]")?.value || "").trim() || window.KARMA_IDENTITY_ID || "";
    const amount = Number(el("#release-amount")?.value || 0);
    const note = el("#release-status");
    const say = function (msg, isErr) {
      if (note) {
        note.textContent = msg;
        note.classList.toggle("err", !!isErr);
      }
      setApiStatus(msg, isErr);
    };
    if (!id) { say("请先连接钱包或填写 Identity ID", true); return; }
    if (!amount || amount <= 0) { say("请填写释放金额", true); return; }
    const activePid =
      window.cyberKarmaApi && window.cyberKarmaApi.activeProfileId
        ? window.cyberKarmaApi.activeProfileId()
        : "";
    if (activePid) {
      say(
        "当前视角是子身份 " + String(activePid).slice(0, 12) + "…：释放额度属于主体身份卡的操作，" +
          "请先在顶部「切换子身份」里选「主体（全部）」；子身份的额度请到「身份」页 →「额度分配」下调。",
        true
      );
      return;
    }
    say("释放中…", false);
    try {
      await window.cyberKarmaApi.releaseCapacity(id, amount);
      say("已释放 " + amount + " USDC", false);
      refreshCapacity();
      // The bills ledger (released_credits) is rendered by cyber-actions.js.
      const bills = document.getElementById("btn-refresh-bills");
      if (bills) bills.click();
    } catch (e) {
      say(String(e.message || e), true);
    }
  }

  function switchPage(page) {
    document.querySelectorAll(".page").forEach(function (p) {
      p.classList.remove("active");
    });
    const sec = document.getElementById(page);
    if (sec) sec.classList.add("active");
    document.querySelectorAll(".nav button").forEach(function (b) {
      b.classList.remove("active");
    });
    const btn = document.querySelector('.nav button[data-page="' + page + '"]');
    if (btn) btn.classList.add("active");
    // 回到总览就重算起步引导：接入 agent、锁仓、授权都可能发生在别的页面。
    if (page === "overview") renderLaunchGuide().catch(function () {});
    const h = el("#pageHeading");
    const sub = el("#pageSubheading");
    if (h && sub && pages[page]) {
      h.setAttribute("data-i18n", pages[page][0]);
      sub.setAttribute("data-i18n", pages[page][1]);
      window.CYBER_I18N.applyCyberI18n();
    }
    try {
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (_) {}
    // Panels that only matter on one page (账单明细, 子身份过滤) refresh here.
    try {
      document.dispatchEvent(new CustomEvent("karma-page-shown", { detail: { page: page } }));
    } catch (_) {}
  }

  /** Exposed for `onclick` / action cards in static HTML */
  window.cyberSwitchPage = switchPage;

  function bindNav() {
    document.querySelectorAll(".nav button").forEach(function (btn) {
      btn.addEventListener("click", function () {
        switchPage(btn.getAttribute("data-page"));
      });
    });
  }

  /** Fallbacks for a cached i18n script that predates SHIPPED_LANGS. */
  const LANG_LABELS = { "zh-CN": "\u4e2d\u6587", en: "English" };
  const LANG_ORDER = ["zh-CN", "en"];

  /**
   * Offer the shipped languages, and only those.
   *
   * ja/ko/es/fr/de/pt-BR do have packs, but each covers 32 of the 224 keys, so
   * picking one leaves the page mostly English behind a localized label. The list
   * is read from i18n-cyber.js rather than hard-coded here so it cannot drift
   * away from the packs the page can actually render.
   */
  function syncLangOptions(sel) {
    const i18n = window.CYBER_I18N || {};
    const packs = Object.keys(i18n.PACKS || {});
    const labels = i18n.LANG_LABELS || LANG_LABELS;
    const shipped = (i18n.SHIPPED_LANGS || LANG_ORDER).filter(function (c) {
      return packs.indexOf(c) >= 0;
    });
    if (!shipped.length) return;
    sel.innerHTML = "";
    shipped.forEach(function (code) {
      const opt = document.createElement("option");
      opt.value = code;
      opt.textContent = labels[code] || code;
      sel.appendChild(opt);
    });
  }

  function bindLang() {
    const sel = el("#cyberLang");
    if (!sel) return;
    syncLangOptions(sel);
    sel.value = window.CYBER_I18N.getLang();
    sel.addEventListener("change", function () {
      window.CYBER_I18N.setLang(sel.value);
      window.CYBER_I18N.applyCyberI18n();
      if (window.KarmaIdentitySwitcher && window.KarmaIdentitySwitcher.render) {
        window.KarmaIdentitySwitcher.render();
      }
    });
  }

  function bindActions() {
    el("[data-action=save-cfg]")?.addEventListener("click", function () {
      saveCfg();
    });
    el("[data-action=refresh-api]")?.addEventListener("click", function () {
      saveCfg();
      refreshCapacity();
    });
    el("[data-action=fetch-settlement]")?.addEventListener("click", function () {
      saveCfg();
      fetchSettlement();
    });
    el("[data-action=lock-capacity]")?.addEventListener("click", function () {
      saveCfg();
      lockCapacityAction();
    });
    el("[data-action=release-capacity]")?.addEventListener("click", function () {
      saveCfg();
      releaseCapacityAction();
    });
  }

  function bindAiToggle() {
    const aiToggle = document.getElementById("aiAgentToggle");
    const aiStatus = document.getElementById("aiAgentStatus");
    if (aiToggle && aiStatus) {
      aiToggle.addEventListener("change", function () {
        aiStatus.textContent = aiToggle.checked ? "开启 / ON" : "关闭 / OFF";
      });
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    loadCfgIntoInputs();
    const baseVal = el("[data-cfg=api_base]")?.value?.trim();
    if (baseVal) window.KARMA_API_BASE = baseVal;
    window.KARMA_API_KEY = el("[data-cfg=api_key]")?.value?.trim();
    window.KARMA_IDENTITY_ID = el("[data-cfg=identity_id]")?.value?.trim();
    const mainId = el(".id-main");
    if (mainId && window.KARMA_IDENTITY_ID) mainId.textContent = window.KARMA_IDENTITY_ID;

    window.CYBER_I18N.applyCyberI18n();
    bindLang();
    bindNav();
    document.querySelectorAll("[data-go]").forEach(function (node) {
      node.addEventListener("click", function () {
        switchPage(node.getAttribute("data-go") || "overview");
      });
    });
    bindActions();
    bindAiToggle();
    bindLaunchGuide();
    switchPage("overview");
    setApiStatus(window.CYBER_I18N.t("api.status_idle"), false);
    renderLaunchGuide().catch(function () {});
    refreshEscrowCommits().catch(function () {});
  });

  /* 起步引导跟着会话走：连接钱包、恢复会话、锁仓、授权额度都会改变当前处于第几步。 */
  window.KarmaLaunchGuide = { refresh: renderLaunchGuide };
  [
    "karma-wallet-connected",
    "karma-session-restored",
    "karma-capacity-changed",
    "karma-locked",
    "karma-alloc-changed",
    "karma-agent-connected",
  ].forEach(function (name) {
    document.addEventListener(name, function () {
      renderLaunchGuide().catch(function () {});
      refreshChainBills().catch(function () {});
      refreshEscrowCommits().catch(function () {});
    });
  });

  // 账单页才需要链上明细；切过去时刷新一次，避免总览页多发请求。
  document.addEventListener("karma-page-shown", function (ev) {
    if (ev && ev.detail && ev.detail.page === "bills") {
      refreshChainBills().catch(function () {});
      refreshEscrowCommits().catch(function () {});
    }
  });
})();
