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
 * Depends on the Karma public API being reachable at window.KARMA_API_BASE.
 */
(function (global) {
  var SS_WALLET = "karma_console_wallet";
  var SS_IDENTITY = "karma_console_identity";
  var SS_TOKEN = "karma_console_access_token";

  function apiBase() {
    return String(global.KARMA_API_BASE || "http://127.0.0.1:8000")
      .trim()
      .replace(/\/$/, "");
  }

  function el(sel, root) {
    return (root || document).querySelector(sel);
  }

  function setStatus(msg, ok) {
    var n = el("[data-wallet-status]");
    if (!n) return;
    n.textContent = msg;
    n.style.color = ok ? "var(--ok, #4ade80)" : ok === false ? "#f87171" : "";
  }

  function hasWallet() {
    return !!(global.ethereum && typeof global.ethereum.request === "function");
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

  async function connect() {
    if (!hasWallet()) {
      setStatus("未检测到 MetaMask / 钱包插件", false);
      throw new Error("Wallet not available");
    }
    var accounts;
    try {
      accounts = await global.ethereum.request({ method: "eth_requestAccounts" });
    } catch (e) {
      setStatus("已取消连接或钱包拒绝授权", false);
      throw e;
    }
    if (!accounts || !accounts.length) {
      setStatus("钱包未返回账户", false);
      throw new Error("No accounts");
    }
    var address = accounts[0];
    var identityId = "";

    try {
      setStatus("获取登录挑战…", null);
      var ch = await siweJson("/v1/auth/siwe/challenge", { address: address });

      setStatus("请在钱包中签名…", null);
      var signature;
      try {
        signature = await global.ethereum.request({
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
    clearSession();
    setStatus("已断开钱包", null);
    var idMain = el(".id-main");
    if (idMain) idMain.textContent = "—";
    document.dispatchEvent(new CustomEvent("karma-wallet-disconnected"));
  }

  function bind() {
    var btn = el("[data-wallet-connect]");
    if (btn) {
      btn.addEventListener("click", function () {
        connect().catch(function () {});
      });
    }
    var disc = el("[data-wallet-disconnect]");
    if (disc) {
      disc.addEventListener("click", disconnect);
    }

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
    bind: bind,
  };

  document.addEventListener("DOMContentLoaded", bind);
})(window);
