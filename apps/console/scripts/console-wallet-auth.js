/**
 * Karma Console — Wallet Connect + SIWE sign-in (no private keys, no mnemonics).
 *
 * Flow:
 *   1. Connect browser wallet (eth_requestAccounts) → get address. The wallet
 *      never exposes private key / mnemonic; it only returns the public address
 *      and, on demand, a signature.
 *   2. POST /v1/auth/siwe/challenge {address} → returns a server-signed
 *      EIP-4361 challenge message (nonce + expiry).
 *   3. personal_sign the challenge message → 0x signature.
 *   4. POST /v1/auth/siwe/verify {nonce, signature, address} → server verifies
 *      the signature and returns { identity_id, wallet, ... }.
 *   5. Store only non-secret session data (wallet address + identity id) in
 *      sessionStorage — cleared when the tab/browser closes. Never store any
 *      key, secret, private key, or mnemonic anywhere in browser storage.
 *
 * Supported providers:
 *   - injected  : window.ethereum (MetaMask / 其他已注入的 EVM 钱包)
 *   - bitpie    : Bitpie App via WalletConnect（扫码 / URI），若检测到
 *                 window.bitpie.ethereum 注入则优先使用注入通道
 *
 * Depends on the Karma public API being reachable at window.KARMA_API_BASE.
 */
(function (global) {
  var SS_WALLET = "karma_console_wallet";
  var SS_IDENTITY = "karma_console_identity";
  var SS_TOKEN = "karma_console_access_token";
  var PROVIDER_KEY = "karma_console_wallet_provider";
  var SEPOLIA_CHAIN_ID = 11155111;
  var WC_PROJECT_ID_FALLBACK = "REPLACE_WITH_WALLETCONNECT_PROJECT_ID";
  var WC_PROJECT_ID = null;
  var WC_SDK_URL = "https://unpkg.com/@walletconnect/ethereum-provider@2.17.2/dist/index.umd.js";

  var state = { wcProvider: null };

  function apiBase() {
    return String(global.KARMA_API_BASE || "http://127.0.0.1:8000")
      .trim()
      .replace(/\/$/, "");
  }

  function el(sel, root) {
    return (root || document).querySelector(sel);
  }

  function els(sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  }

  function setStatus(msg, ok) {
    els("[data-wallet-status]").forEach(function (n) {
      n.textContent = msg;
      n.style.color = ok ? "var(--ok, #4ade80)" : ok === false ? "#f87171" : "";
    });
  }

  function injectedProvider() {
    return global.ethereum && typeof global.ethereum.request === "function"
      ? global.ethereum
      : null;
  }

  function bitpieInjectedProvider() {
    var bp = global.bitpie || global.Bitpie || {};
    return bp.ethereum && typeof bp.ethereum.request === "function"
      ? bp.ethereum
      : null;
  }

  function hasWallet() {
    return !!(injectedProvider() || bitpieInjectedProvider() || global.WalletConnectEthereumProvider);
  }

  function saveSession(wallet, identityId, accessToken) {
    try {
      sessionStorage.setItem(SS_WALLET, wallet || "");
      sessionStorage.setItem(SS_IDENTITY, identityId || "");
      sessionStorage.setItem(SS_TOKEN, accessToken || "");
      global.KARMA_ACCESS_TOKEN = accessToken || "";
    } catch (_) {}
  }

  function clearSession() {
    try {
      sessionStorage.removeItem(SS_WALLET);
      sessionStorage.removeItem(SS_IDENTITY);
      sessionStorage.removeItem(SS_TOKEN);
    } catch (_) {}
    global.KARMA_ACCESS_TOKEN = "";
  }

  function readSession() {
    try {
      return {
        wallet: sessionStorage.getItem(SS_WALLET) || "",
        identityId: sessionStorage.getItem(SS_IDENTITY) || "",
        accessToken: sessionStorage.getItem(SS_TOKEN) || "",
      };
    } catch (_) {
      return { wallet: "", identityId: "", accessToken: "" };
    }
  }

  async function siweJson(path, payload) {
    var res = await fetch(apiBase() + path, {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    var text = await res.text();
    var body;
    try {
      body = text ? JSON.parse(text) : null;
    } catch (_) {
      body = { raw: text };
    }
    if (!res.ok) {
      var msg =
        (body && (body.detail || body.message)) || (typeof body === "object" ? JSON.stringify(body) : text) || res.statusText;
      var err = new Error("HTTP " + res.status + ": " + msg);
      err.status = res.status;
      err.body = body;
      throw err;
    }
    return body;
  }

  function normalizeChainId(cid) {
    if (typeof cid === "string" && cid.indexOf(":") !== -1) return Number(cid.split(":")[1]);
    return Number(cid);
  }

  function readProviderPref() {
    try {
      return localStorage.getItem(PROVIDER_KEY) || "";
    } catch (_) {
      return "";
    }
  }

  function saveProviderPref(id) {
    try {
      localStorage.setItem(PROVIDER_KEY, id || "injected");
    } catch (_) {}
  }

  function getSelectedProviderId() {
    var sel = el("[data-wallet-provider]");
    if (sel && sel.value) {
      return sel.value === "walletconnect" ? "bitpie" : sel.value;
    }
    return readProviderPref() || "injected";
  }

  async function resolveProjectId() {
    if (WC_PROJECT_ID) return WC_PROJECT_ID;
    var explicit = global.KARMA_WC_PROJECT_ID;
    if (explicit && explicit !== WC_PROJECT_ID_FALLBACK) {
      WC_PROJECT_ID = explicit;
      return WC_PROJECT_ID;
    }
    try {
      var res = await fetch(apiBase() + "/v1/info");
      if (res.ok) {
        var data = await res.json();
        var wc = data && data.walletconnect;
        var pid = wc && (wc.project_id || wc.projectId);
        if (pid && pid !== WC_PROJECT_ID_FALLBACK) {
          WC_PROJECT_ID = pid;
          return WC_PROJECT_ID;
        }
      }
    } catch (_) {}
    WC_PROJECT_ID = WC_PROJECT_ID_FALLBACK;
    return WC_PROJECT_ID;
  }

  function loadWalletConnectSdk() {
    if (global.WalletConnectEthereumProvider) {
      return Promise.resolve(global.WalletConnectEthereumProvider);
    }
    return new Promise(function (resolve, reject) {
      var script = document.createElement("script");
      script.src = WC_SDK_URL;
      script.async = true;
      script.onload = function () {
        resolve(global.WalletConnectEthereumProvider);
      };
      script.onerror = function () {
        reject(new Error("WalletConnect SDK 加载失败（请检查网络或 CDN 可达性）"));
      };
      (document.head || document.documentElement).appendChild(script);
    });
  }

  async function getWalletConnectProvider() {
    if (state.wcProvider) return state.wcProvider;

    await loadWalletConnectSdk();
    var ns = global.WalletConnectEthereumProvider || {};
    var EthereumProvider = ns.EthereumProvider || ns.default || ns;
    if (typeof EthereumProvider.init !== "function") {
      throw new Error("WalletConnect SDK 未正确加载");
    }

    var provider = await EthereumProvider.init({
      projectId: await resolveProjectId(),
      chains: [SEPOLIA_CHAIN_ID],
      optionalChains: [SEPOLIA_CHAIN_ID],
      showQrModal: true,
      metadata: {
        name: "Karma Console",
        description: "Karma AI Agent non-custodial settlement",
        url: global.location && global.location.origin && global.location.origin !== "null" ? global.location.origin : "http://127.0.0.1:8000",
        icons: [],
      },
    });

    provider.on("display_uri", function (uri) {
      setStatus("比特派：请使用 Bitpie App 扫描二维码或复制 URI 连接", null);
      document.dispatchEvent(new CustomEvent("karma-wallet-uri", { detail: uri }));
    });
    provider.on("accountsChanged", function (accounts) {
      if (accounts && accounts[0]) {
        setStatus("已切换账户 · " + shortAddr(accounts[0]), true);
      }
    });
    provider.on("chainChanged", function () {
      var cid = normalizeChainId(provider.chainId);
      if (cid !== SEPOLIA_CHAIN_ID) {
        setStatus("注意：当前网络 chainId " + cid + "，Karma 使用 Sepolia (11155111)", false);
      }
    });
    provider.on("disconnect", function () {
      state.wcProvider = null;
      clearSession();
      setStatus("比特派钱包已断开", null);
      var idMain = el(".id-main");
      if (idMain) idMain.textContent = "—";
      document.dispatchEvent(new CustomEvent("karma-wallet-disconnected"));
    });

    state.wcProvider = provider;
    return provider;
  }

  async function resolveProvider(providerId) {
    providerId = providerId || getSelectedProviderId();
    saveProviderPref(providerId);

    if (providerId === "bitpie" || providerId === "walletconnect") {
      var injected = bitpieInjectedProvider();
      if (injected) return { provider: injected, kind: "injected" };
      return { provider: await getWalletConnectProvider(), kind: "walletconnect" };
    }

    var provider = injectedProvider();
    if (!provider) {
      setStatus("未检测到 MetaMask / 钱包插件", false);
      throw new Error("Wallet not available");
    }
    return { provider: provider, kind: "injected" };
  }

  async function requestAccounts(resolved) {
    if (resolved.kind === "walletconnect") {
      var p = resolved.provider;
      var accounts = p.accounts && p.accounts.length ? p.accounts : await p.enable();
      if (!accounts || !accounts.length) throw new Error("No accounts");
      return accounts[0];
    }
    var accs = await resolved.provider.request({ method: "eth_requestAccounts" });
    if (!accs || !accs.length) throw new Error("No accounts");
    return accs[0];
  }

  async function connect(providerId) {
    var resolved;
    try {
      setStatus("检测钱包…", null);
      resolved = await resolveProvider(providerId);
    } catch (e) {
      setStatus(e && e.message ? e.message : "无法初始化钱包", false);
      throw e;
    }

    var address;
    try {
      address = await requestAccounts(resolved);
    } catch (e) {
      setStatus("已取消连接或钱包拒绝授权", false);
      throw e;
    }

    var identityId = "";

    try {
      setStatus("获取登录挑战…", null);
      var ch = await siweJson("/v1/auth/siwe/challenge", { address: address });

      setStatus("请在钱包中签名…", null);
      var signature;
      try {
        signature = await resolved.provider.request({
          method: "personal_sign",
          params: [ch.message, address],
        });
      } catch (e) {
        setStatus("签名已取消", false);
        throw e;
      }

      setStatus("验证签名…", null);
      var v = await siweJson("/v1/auth/siwe/verify", {
        nonce: ch.nonce,
        signature: signature,
        address: address,
      });

      identityId = v.identity_id || "";
      var accessToken = v.access_token || "";
      saveSession(address, identityId, accessToken);

      // Reflect onto the console's global identity so reads work without a key.
      try {
        global.KARMA_IDENTITY_ID = identityId || global.KARMA_IDENTITY_ID;
        var idInput = el("[data-cfg=identity_id]");
        if (idInput && identityId) idInput.value = identityId;
        var walletInput = el("[data-wallet]");
        if (walletInput) walletInput.value = address;
        var idMain = el(".id-main");
        if (idMain && identityId) idMain.textContent = identityId;
      } catch (_) {}

      setStatus(
        "已连接 · " + shortAddr(address) + (identityId ? " · " + identityId : ""),
        true
      );
      document.dispatchEvent(new CustomEvent("karma-wallet-connected", { detail: v }));
      return { wallet: address, identityId: identityId, verify: v };
    } catch (e) {
      throw e;
    }
  }

  function shortAddr(a) {
    if (!a) return "";
    return String(a).slice(0, 6) + "…" + String(a).slice(-4);
  }

  function disconnect() {
    if (state.wcProvider && typeof state.wcProvider.disconnect === "function") {
      try {
        state.wcProvider.disconnect();
      } catch (_) {}
    }
    state.wcProvider = null;
    clearSession();
    setStatus("已断开钱包", null);
    var idMain = el(".id-main");
    if (idMain) idMain.textContent = "—";
    document.dispatchEvent(new CustomEvent("karma-wallet-disconnected"));
  }

  function bind() {
    els("[data-wallet-connect]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        connect(getSelectedProviderId()).catch(function () {});
      });
    });

    els("[data-wallet-disconnect]").forEach(function (disc) {
      disc.addEventListener("click", disconnect);
    });

    els("[data-wallet-provider]").forEach(function (sel) {
      sel.value = readProviderPref() || "injected";
      sel.addEventListener("change", function () {
        saveProviderPref(sel.value);
      });
    });

    // Restore a live session label on load.
    var s = readSession();
    if (s.accessToken) global.KARMA_ACCESS_TOKEN = s.accessToken;
    if (s.wallet) {
      setStatus("已连接 · " + shortAddr(s.wallet) + (s.identityId ? " · " + s.identityId : ""), true);
      if (s.identityId) {
        try {
          var idInput = el("[data-cfg=identity_id]");
          if (idInput && !idInput.value.trim()) idInput.value = s.identityId;
          var idMain = el(".id-main");
          if (idMain) idMain.textContent = s.identityId;
        } catch (_) {}
      }
    }
  }

  global.KarmaWalletAuth = {
    connect: connect,
    disconnect: disconnect,
    readSession: readSession,
    hasWallet: hasWallet,
    getSelectedProviderId: getSelectedProviderId,
    getProvider: resolveProvider,
    requestAccounts: requestAccounts,
    bind: bind,
  };

  document.addEventListener("DOMContentLoaded", bind);
})(window);