/**
 * Karma Console / agent page — onboarding authorization wallet adapter.
 *
 * 把 cyber-onboarding-flow.js 的 wallet_sign 步骤接到真实钱包：
 *   owner_identity 与 runtime_key_mint 两步都会调用
 *   personal_sign(payload.sign_message)，拿到 { address, signature } 回传。
 *
 * 安全边界（与 console-wallet-auth.js 同一口径）：
 *   - 只调 eth_requestAccounts / eth_accounts / personal_sign；
 *   - 从不索要私钥 / 助记词；personal_sign 的签名过程私钥不出钱包；
 *   - 只在内存里流转公钥地址与签名，不落盘。
 *
 * Provider 解析顺序：
 *   1. KarmaWalletAuth.activeProvider()          （操作台已连接的钱包）
 *   2. KarmaWalletAuth.entries()                 （EIP-6963 发现的钱包）
 *   3. window.ethereum                           （MetaMask 等注入式钱包）
 *   4. WalletConnect                             （需 window.KARMA_WC_PROJECT_ID）
 *
 * 暴露 global.KarmaOnboardingWallet.sign(payload, onSigned, onError)。
 * payload 为 prompt.payload（含 sign_message），或直接传字符串。
 */
(function (global) {
  "use strict";

  var WC_SDK_URL = "https://unpkg.com/@walletconnect/ethereum-provider@2.17.2/dist/index.umd.js";
  var wcProviderRef = null;

  function walletAuth() {
    return global.KarmaWalletAuth || null;
  }

  function discoveredProviders() {
    var auth = walletAuth();
    if (auth && typeof auth.entries === "function") {
      try {
        var list = auth.entries();
        if (list && list.length) return list;
      } catch (_) {}
    }
    return [];
  }

  function injectedProvider() {
    var auth = walletAuth();
    if (auth && typeof auth.activeProvider === "function") {
      try {
        var p = auth.activeProvider();
        if (p) return p;
      } catch (_) {}
    }
    var list = discoveredProviders();
    if (list.length === 1) return list[0].provider;
    return global.ethereum || null;
  }

  async function currentAccount() {
    var auth = walletAuth();
    if (auth && typeof auth.readSession === "function") {
      try {
        var s = auth.readSession();
        if (s && s.wallet) return s.wallet;
      } catch (_) {}
    }
    var provider = injectedProvider();
    if (!provider || typeof provider.request !== "function") return null;
    try {
      var accts = await provider.request({ method: "eth_accounts" });
      return accts && accts.length ? accts[0] : null;
    } catch (_) {
      return null;
    }
  }

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var s = global.document.createElement("script");
      s.src = src;
      s.onload = function () { resolve(); };
      s.onerror = function () { reject(new Error("walletconnect-sdk-load-failed")); };
      global.document.head.appendChild(s);
    });
  }

  async function walletConnectProvider() {
    if (wcProviderRef) return wcProviderRef;
    var projectId = global.KARMA_WC_PROJECT_ID;
    if (!projectId || String(projectId).trim() === "") {
      throw new Error("walletconnect-project-id-missing");
    }
    var wc = global.EthereumProvider;
    if (!wc) {
      await loadScript(WC_SDK_URL);
      wc = global.EthereumProvider;
    }
    if (!wc) throw new Error("walletconnect-sdk-missing");
    wcProviderRef = await wc.init({
      projectId: String(projectId).trim(),
      chains: [11155111],
      showQrModal: true,
    });
    return wcProviderRef;
  }

  async function resolveProvider() {
    var p = injectedProvider();
    if (p && typeof p.request === "function") return p;
    try {
      return await walletConnectProvider();
    } catch (e) {
      throw e;
    }
  }

  async function requestAccounts(provider) {
    var accts = await provider.request({ method: "eth_requestAccounts" });
    if (!accts || !accts.length) throw new Error("wallet-returned-no-account");
    return accts[0];
  }

  /**
   * 对 signMessage 做 personal_sign，成功后 onSigned({address, signature})。
   */
  async function sign(payload, onSigned, onError) {
    try {
      var signMessage = (typeof payload === "string") ? payload : (payload && payload.sign_message);
      if (!signMessage) throw new Error("sign-message-required");
      var account = await currentAccount();
      var provider = null;

      if (!account) {
        var auth = walletAuth();
        if (auth && typeof auth.connect === "function") {
          await auth.connect();
          account = await currentAccount();
        }
      }

      if (!account) {
        provider = await resolveProvider();
        account = await requestAccounts(provider);
      }

      if (!provider) provider = await resolveProvider();
      var signature = await provider.request({
        method: "personal_sign",
        params: [String(signMessage), account],
      });

      onSigned({ address: account, signature: signature });
    } catch (e) {
      if (typeof onError === "function") onError(e);
      else throw e;
    }
  }

  global.KarmaOnboardingWallet = {
    sign: sign,
    currentAccount: currentAccount,
    resolveProvider: resolveProvider,
  };
})(typeof window !== "undefined" ? window : this);
