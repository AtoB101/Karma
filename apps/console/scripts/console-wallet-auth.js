/**
 * Karma Console — Wallet connect + SIWE sign-in.
 *
 * ------------------------------------------------------------------ security
 * This module is built so that it CANNOT touch user secrets:
 *   - It never asks a wallet for a private key, seed phrase or mnemonic.
 *   - The only wallet RPCs it calls are eth_requestAccounts / eth_accounts /
 *     eth_chainId / personal_sign. personal_sign returns a signature and the
 *     private key never leaves the wallet.
 *   - It stores only public, non-secret data (public address, server identity
 *     id, short-lived session token) in sessionStorage.
 *   - There is no code path that reads a key, even if a wallet exposed one.
 *
 * ---------------------------------------------------------------------- flow
 *   1. Discover installed wallets (EIP-6963), else fall back to window.ethereum.
 *   2. eth_requestAccounts -> public address.
 *   3. POST /v1/auth/siwe/challenge {address} -> EIP-4361 message.
 *   4. personal_sign(message) -> signature.
 *   5. POST /v1/auth/siwe/verify {nonce, signature, address} -> identity + token.
 *
 * When no wallet is installed the module opens a wallet picker with download
 * links and mobile deep links instead of dead-ending on "no plugin detected".
 */
(function (global) {
  "use strict";

  var SS_WALLET = "karma_console_wallet";
  var SS_IDENTITY = "karma_console_identity";
  var SS_TOKEN = "karma_console_access_token";
  var SS_EXPIRES = "karma_console_token_expires_at";
  var SS_WNAME = "karma_console_wallet_name";

  var MOBILE_UA = /android|iphone|ipad|ipod|iemobile|blackberry|mobile/i.test(
    (global.navigator && global.navigator.userAgent) || ""
  );

  /* 微信 / QQ / 微博 / 飞书 / 钉钉这类内置浏览器会拦掉自定义协议和 App 跳转，
     钱包唤起链接点下去就是没反应。单独认出来，给一句人话提示＋复制链接兜底。 */
  var APP_BROWSER = /micromessenger|weibo|feishu|lark|dingtalk|douyin|toutiao|alipayclient/i.test(
    (global.navigator && global.navigator.userAgent) || ""
  );

  /* ------------------------------------------------------------------ utils */

  function apiBase() {
    var raw = global.KARMA_API_BASE;
    if (raw === undefined || raw === null || String(raw).trim() === "") {
      try {
        if (global.location && /^https?:$/.test(global.location.protocol)) {
          return global.location.origin;
        }
      } catch (_) {}
      return "http://127.0.0.1:8000";
    }
    return String(raw).trim().replace(/\/$/, "");
  }

  function all(sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  }

  function setStatus(msg, ok) {
    all("[data-wallet-status]").forEach(function (n) {
      n.textContent = msg;
      n.style.color = ok === true ? "var(--ok, #4ade80)" : ok === false ? "#f87171" : "";
    });
  }

  function shortAddr(a) {
    if (!a) return "";
    return String(a).slice(0, 6) + "…" + String(a).slice(-4);
  }

  /**
   * Announce a console event on BOTH document and window. The console is not
   * consistent about where it listens (console-sync/cyber-identity bind to
   * document), so dispatching on a single target silently drops listeners.
   */
  function emitEvent(name, detail) {
    var ev;
    try {
      ev = new CustomEvent(name, { detail: detail });
    } catch (_) {
      try { ev = new Event(name); } catch (_) { return; }
    }
    try { document.dispatchEvent(ev); } catch (_) {}
    try { global.dispatchEvent(ev); } catch (_) {}
  }

  function errText(e) {    if (!e) return "未知错误";
    if (e.code === 4001) return "你取消了授权";
    if (e.code === -32002) return "钱包里已有一个待处理的请求";
    if (e.code === 4902) return "钱包里没有这条链";
    return e.message || String(e);
  }

  function b64(obj) {
    try {
      return btoa(unescape(encodeURIComponent(JSON.stringify(obj))));
    } catch (_) {
      return "";
    }
  }

  function jwtExpiry(token) {
    try {
      var part = String(token).split(".")[1];
      if (!part) return 0;
      part = part.replace(/-/g, "+").replace(/_/g, "/");
      while (part.length % 4) part += "=";
      var payload = JSON.parse(decodeURIComponent(escape(atob(part))));
      return payload && payload.exp ? payload.exp * 1000 : 0;
    } catch (_) {
      return 0;
    }
  }

  /* --------------------------------------------------------------- sessions */

  function saveSession(wallet, identityId, accessToken, walletName) {
    try {
      sessionStorage.setItem(SS_WALLET, wallet || "");
      sessionStorage.setItem(SS_IDENTITY, identityId || "");
      sessionStorage.setItem(SS_TOKEN, accessToken || "");
      sessionStorage.setItem(SS_EXPIRES, String(accessToken ? jwtExpiry(accessToken) : 0));
      if (walletName) sessionStorage.setItem(SS_WNAME, walletName);
    } catch (_) {}
    global.KARMA_ACCESS_TOKEN = accessToken || "";
    global.KARMA_IDENTITY_ID = identityId || global.KARMA_IDENTITY_ID || "";
  }

  function clearSession() {
    try {
      [SS_WALLET, SS_IDENTITY, SS_TOKEN, SS_EXPIRES, SS_WNAME].forEach(function (k) {
        sessionStorage.removeItem(k);
      });
      sessionStorage.removeItem("karma_console_active_profile");
    } catch (_) {}
    global.KARMA_ACCESS_TOKEN = "";
  }

  function readSession() {
    try {
      return {
        wallet: sessionStorage.getItem(SS_WALLET) || "",
        identityId: sessionStorage.getItem(SS_IDENTITY) || "",
        accessToken: sessionStorage.getItem(SS_TOKEN) || "",
        expiresAt: parseInt(sessionStorage.getItem(SS_EXPIRES) || "0", 10) || 0,
        walletName: sessionStorage.getItem(SS_WNAME) || "",
      };
    } catch (_) {
      return { wallet: "", identityId: "", accessToken: "", expiresAt: 0, walletName: "" };
    }
  }

  function tokenState() {
    var s = readSession();
    if (!s.accessToken) return "none";
    if (!s.expiresAt) return "ok";
    var left = s.expiresAt - Date.now();
    if (left <= 0) return "expired";
    if (left <= 60000) return "stale";
    return "ok";
  }

  /* ---------------------------------------------------------- EIP-6963 discovery */

  var discovered = [];

  /** The provider that signed this session, so every console action signs with
   *  the same wallet the user actually picked (not a hard-coded window.ethereum). */
  var activeProviderRef = null;

  function onAnnounce(ev) {
    var d = ev && ev.detail;
    if (!d || !d.info || !d.provider) return;
    for (var i = 0; i < discovered.length; i++) {
      if (discovered[i].info.uuid === d.info.uuid) return;
    }
    discovered.push({ info: d.info, provider: d.provider });
    if (isModalOpen()) renderBody();
  }

  try {
    global.addEventListener("eip6963:announceProvider", onAnnounce);
    global.dispatchEvent(new Event("eip6963:requestProvider"));
  } catch (_) {}

  function detectLegacyName(p) {
    if (!p) return "浏览器钱包";
    if (p.isMetaMask) return "MetaMask";
    if (p.isOkxWallet || p.isOKExWallet) return "OKX Wallet";
    if (p.isRabby) return "Rabby";
    if (p.isCoinbaseWallet) return "Coinbase Wallet";
    if (p.isBitKeep) return "Bitget Wallet";
    if (p.isTokenPocket) return "TokenPocket";
    if (p.isTrust || p.isTrustWallet) return "Trust Wallet";
    if (p.isBraveWallet) return "Brave Wallet";
    if (p.isImToken) return "imToken";
    return "浏览器钱包";
  }

  function legacyEntries() {
    var eth = global.ethereum;
    if (!eth) return [];
    var list = [];
    if (Array.isArray(eth.providers) && eth.providers.length) {
      eth.providers.forEach(function (p, i) {
        if (p && typeof p.request === "function") {
          list.push({ info: { uuid: "legacy-" + i, name: detectLegacyName(p), icon: "" }, provider: p });
        }
      });
    }
    if (!list.length && typeof eth.request === "function") {
      list.push({ info: { uuid: "legacy-single", name: detectLegacyName(eth), icon: "" }, provider: eth });
    }
    return list;
  }

  function entries() {
    var out = discovered.slice();
    legacyEntries().forEach(function (e) {
      for (var i = 0; i < out.length; i++) {
        if (out[i].provider === e.provider) return;
      }
      out.push(e);
    });
    return out;
  }

  function findEntryByName(name) {
    var list = entries();
    for (var i = 0; i < list.length; i++) {
      if (list[i].info.name === name) return list[i];
    }
    return null;
  }

  /* ------------------------------------------------------- wallet catalogue */

  function consoleUrl() {
    try {
      return global.location.origin + global.location.pathname;
    } catch (_) {
      return "https://karma-network.ai/console/pages/cyber/index.html";
    }
  }

  var CATALOG = [
    {
      name: "MetaMask",
      install: "https://metamask.io/download/",
      icon: "🦊",
      deep: function (u) {
        return "https://metamask.app.link/dapp/" + u.replace(/^https?:\/\//, "");
      },
    },
    {
      name: "OKX Wallet",
      install: "https://www.okx.com/web3",
      icon: "⭕",
      deep: function (u) {
        return "okx://wallet/dapp/url?dappUrl=" + encodeURIComponent(u);
      },
    },
    {
      name: "Rabby",
      install: "https://rabby.io/",
      icon: "🐰",
    },
    {
      name: "Coinbase Wallet",
      install: "https://www.coinbase.com/wallet/downloads",
      icon: "🔵",
      deep: function (u) {
        return "https://go.cb-w.com/dapp?cb_url=" + encodeURIComponent(u);
      },
    },
    {
      name: "Bitget Wallet",
      install: "https://web3.bitget.com/wallet-download",
      icon: "🔷",
    },
    {
      name: "imToken",
      install: "https://token.im/download",
      icon: "💧",
      deep: function (u) {
        return "imtokenv2://navigate/DappView?url=" + encodeURIComponent(u);
      },
    },
    {
      name: "TokenPocket",
      install: "https://www.tokenpocket.pro/en/download/app",
      icon: "🟦",
      deep: function (u) {
        return (
          "tpoutside://pull.activity?param=" +
          b64({ url: u, action: "open", appName: "Karma Console", source: "dapp" })
        );
      },
    },
    {
      name: "Trust Wallet",
      install: "https://trustwallet.com/download",
      icon: "🛡️",
      deep: function (u) {
        return "https://link.trustwallet.com/open_url?coin_id=60&url=" + encodeURIComponent(u);
      },
    },
  ];

  /* ---------------------------------------------------------------- modal CSS */

  var CSS = [
    ".kw-overlay{position:fixed;inset:0;z-index:2147483000;display:none;align-items:center;justify-content:center;padding:20px;background:rgba(3,6,18,.72);backdrop-filter:blur(6px)}",
    ".kw-overlay.kw-open{display:flex}",
    ".kw-modal{width:100%;max-width:440px;max-height:86vh;overflow:auto;border-radius:18px;border:1px solid rgba(120,140,255,.28);background:linear-gradient(160deg,#0b1024 0%,#0a0f1f 60%,#080d1a 100%);box-shadow:0 24px 70px rgba(0,0,0,.6);color:#e8ecff;font:14px/1.5 system-ui,-apple-system,'Segoe UI',Roboto,'PingFang SC','Microsoft YaHei',sans-serif}",
    ".kw-head{display:flex;align-items:center;justify-content:space-between;padding:18px 20px 0}",
    ".kw-head h3{margin:0;font-size:17px;font-weight:650;letter-spacing:.2px}",
    ".kw-x{width:32px;height:32px;border-radius:10px;border:1px solid rgba(120,140,255,.22);background:rgba(255,255,255,.03);color:#9fb0e0;font-size:18px;line-height:1;cursor:pointer}",
    ".kw-x:hover{background:rgba(255,255,255,.08);color:#fff}",
    ".kw-sub{margin:8px 20px 0;color:#9aa8cc;font-size:12.5px}",
    ".kw-body{padding:14px 20px 4px}",
    ".kw-sec{margin:0 0 6px;font-size:11.5px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:#7d8bb5}",
    ".kw-list{display:flex;flex-direction:column;gap:8px;margin:8px 0 16px}",
    ".kw-item{display:flex;align-items:center;gap:12px;width:100%;padding:12px 14px;border-radius:13px;border:1px solid rgba(120,140,255,.2);background:rgba(255,255,255,.035);color:#e8ecff;font-size:14px;cursor:pointer;text-align:left;transition:border-color .15s,background .15s}",
    ".kw-item:hover{border-color:rgba(140,160,255,.55);background:rgba(120,140,255,.12)}",
    ".kw-ico{width:30px;height:30px;border-radius:9px;display:flex;align-items:center;justify-content:center;background:rgba(120,140,255,.14);font-size:16px;flex:0 0 auto}",
    ".kw-ico img{width:26px;height:26px;border-radius:7px;display:block}",
    ".kw-name{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}",
    ".kw-tag{font-size:11px;color:#6ee7a8;border:1px solid rgba(110,231,168,.3);background:rgba(110,231,168,.08);padding:2px 8px;border-radius:999px;flex:0 0 auto}",
    ".kw-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin:8px 0 16px}",
    ".kw-inst{display:flex;align-items:center;gap:9px;padding:11px 12px;border-radius:12px;border:1px solid rgba(120,140,255,.18);background:rgba(255,255,255,.03);color:#dbe3ff;font-size:13px;text-decoration:none}",
    ".kw-inst:hover{border-color:rgba(140,160,255,.5);background:rgba(120,140,255,.1)}",
    ".kw-chips{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0 14px}",
    ".kw-chip{display:inline-flex;align-items:center;gap:6px;padding:7px 11px;border-radius:999px;font-size:12.5px}",
    ".kw-empty{margin:6px 0 14px;padding:12px 14px;border-radius:12px;border:1px dashed rgba(255,190,120,.34);background:rgba(255,190,120,.07);color:#ffd9a8;font-size:12.5px}",
    ".kw-note{display:block;padding:0 20px 18px;color:#7d8bb5;font-size:11.5px}",
    ".kw-hint{color:#9aa8cc;font-size:12px;margin:0 0 8px}",
    ".kw-open-wallet{text-decoration:none;border-color:rgba(110,231,168,.34)}",
    ".kw-open-wallet .kw-tag{color:#6ee7a8}",
    ".kw-app{margin:0 0 14px;padding:11px 13px;border-radius:12px;border:1px solid rgba(255,190,120,.34);background:rgba(255,190,120,.08);color:#ffd9a8;font-size:12.5px}",
    ".kw-app-copy{margin-top:9px;padding:7px 12px;border-radius:9px;border:1px solid rgba(255,190,120,.42);background:rgba(255,190,120,.13);color:#ffd9a8;font-size:12px;cursor:pointer}",
    ".kw-more{margin:0 0 14px}",
    ".kw-more>summary{cursor:pointer;color:#9aa8cc;font-size:12px;padding:7px 0;list-style:none}",
    ".kw-more>summary::-webkit-details-marker{display:none}",
    ".kw-more>summary:before{content:'▸ '}",
    ".kw-more[open]>summary:before{content:'▾ '}",
    "@media(max-width:520px){.kw-grid{grid-template-columns:1fr}}"
  ].join("");

  function injectCss() {
    if (document.getElementById("kw-styles")) return;
    var s = document.createElement("style");
    s.id = "kw-styles";
    s.textContent = CSS;
    document.head.appendChild(s);
  }

  /* ------------------------------------------------------------------ modal */

  function ensureModal() {
    var node = document.getElementById("kw-overlay");
    if (node) return node;
    injectCss();
    node = document.createElement("div");
    node.id = "kw-overlay";
    node.className = "kw-overlay";
    node.setAttribute("role", "dialog");
    node.setAttribute("aria-modal", "true");
    node.innerHTML =
      '<div class="kw-modal">' +
      '<div class="kw-head"><h3>连接钱包</h3>' +
      '<button type="button" class="kw-x" data-kw-close aria-label="关闭">×</button></div>' +
      '<p class="kw-sub">用钱包签名登录。Karma 只读取你的公开地址和签名，永远不会请求私钥或助记词。</p>' +
      '<div class="kw-body" data-kw-body></div>' +
      '<span class="kw-note">🔒 全程不接触私钥 / 助记词 · 签名只用于登录，不会发起任何转账</span>' +
      "</div>";
    document.body.appendChild(node);
    node.addEventListener("click", function (ev) {
      if (ev.target === node || ev.target.closest("[data-kw-close]")) closeModal();
      var copy = ev.target.closest("[data-kw-copy]");
      if (copy) copyText(copy.getAttribute("data-kw-copy") || consoleUrl(), copy);
    });
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") closeModal();
    });
    return node;
  }

  function isModalOpen() {
    var n = document.getElementById("kw-overlay");
    return !!(n && n.classList.contains("kw-open"));
  }

  function openModal() {
    var node = ensureModal();
    renderBody();
    node.classList.add("kw-open");
    try {
      global.dispatchEvent(new Event("eip6963:requestProvider"));
    } catch (_) {}
  }

  function closeModal() {
    var n = document.getElementById("kw-overlay");
    if (n) n.classList.remove("kw-open");
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function copyText(text, btn) {
    function done() {
      if (!btn) return;
      var old = btn.textContent;
      btn.textContent = "✓ 已复制，去钱包里粘贴打开";
      setTimeout(function () {
        btn.textContent = old;
      }, 1800);
    }
    function fallback() {
      try {
        var ta = document.createElement("textarea");
        ta.value = text;
        ta.setAttribute("readonly", "");
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
        done();
      } catch (_) {}
    }
    try {
      if (global.navigator && global.navigator.clipboard && global.navigator.clipboard.writeText) {
        global.navigator.clipboard.writeText(text).then(done, fallback);
        return;
      }
    } catch (_) {}
    fallback();
  }

  function renderBody() {
    var body = document.querySelector("[data-kw-body]");
    if (!body) return;
    var list = entries();
    var url = consoleUrl();
    var html = "";

    if (APP_BROWSER) {
      html +=
        '<div class="kw-app"><div>你正在微信 / QQ 这类内置浏览器里打开本页，' +
        "它们会拦掉钱包 App 的跳转 —— 点了钱包没反应就是这个原因。" +
        "请点右上角「…」→「在浏览器打开」，再回来点对应钱包即可。" +
        '<br><button type="button" class="kw-app-copy" data-kw-copy="' +
        esc(url) +
        '">复制本页链接（粘贴到手机钱包内置浏览器）</button></div></div>';
    }

    if (list.length) {
      html += '<p class="kw-sec">已检测到的钱包</p><div class="kw-list">';
      list.forEach(function (e) {
        var icon =
          e.info.icon && /^data:image\//.test(e.info.icon)
            ? '<img src="' + esc(e.info.icon) + '" alt="" />'
            : "👛";
        html +=
          '<button type="button" class="kw-item" data-kw-pick="' +
          esc(e.info.uuid) +
          '"><span class="kw-ico">' +
          icon +
          '</span><span class="kw-name">' +
          esc(e.info.name) +
          '</span><span class="kw-tag">点此连接</span></button>';
      });
      html += "</div>";
    } else {
      html +=
        '<div class="kw-empty">' +
        (MOBILE_UA
          ? "你在手机上打开本页：点下面任一钱包，会直接唤起钱包 App，并在它内置的浏览器里载入本页。"
          : "当前浏览器没有检测到钱包插件。电脑上可安装插件，手机上可点下面的钱包唤起 App。") +
        "</div>";
    }

    function installGrid() {
      var out = '<div class="kw-grid">';
      CATALOG.slice(0, 6).forEach(function (w) {
        out +=
          '<a class="kw-inst" href="' +
          esc(w.install) +
          '" target="_blank" rel="noopener noreferrer"><span class="kw-ico">' +
          w.icon +
          "</span><span>" +
          esc(w.name) +
          "</span></a>";
      });
      return out + "</div>";
    }

    /* 手机上唯一能真正连上的路径是「让钱包打开本页」——手机浏览器里没有插件可点，
       所以手机上它排最前、做成一整行的大按钮，插件安装收进折叠项。桌面反过来：
       插件才是马上能用起来的那条路，手机唤起只是备选。之前手机上先把插件下载链接
       摆最前，用户点 MetaMask 只会跳到插件下载页，既没唤起 App 也没连上钱包。 */
    var mobile = CATALOG.filter(function (w) {
      return w.deep;
    });

    var mobileSection =
      '<p class="kw-sec">' +
      (MOBILE_UA ? "用手机钱包打开本页" : "手机钱包：唤起 App 打开本页") +
      "</p>";
    if (MOBILE_UA) {
      mobileSection += '<div class="kw-list">';
      mobile.forEach(function (w) {
        mobileSection +=
          '<a class="kw-item kw-open-wallet" href="' +
          esc(w.deep(url)) +
          '"><span class="kw-ico">' +
          w.icon +
          '</span><span class="kw-name">' +
          esc(w.name) +
          '</span><span class="kw-tag">打开</span></a>';
      });
      mobileSection += "</div>";
      mobileSection +=
        '<p class="kw-hint">点了没反应 = 这个钱包没装在手机上，先去应用商店安装。' +
        "装好后它会用钱包内置浏览器打开本页，再点右上角「连接钱包」授权即可。</p>";
    } else {
      mobileSection +=
        '<p class="kw-hint">用手机点一下，本页会在钱包 App 的内置浏览器里打开，' +
        "再点「连接钱包」授权即可。</p>";
      mobileSection += '<div class="kw-chips">';
      mobile.forEach(function (w) {
        mobileSection +=
          '<a class="kw-inst kw-chip" href="' +
          esc(w.deep(url)) +
          '"><span>' +
          w.icon +
          "</span><span>" +
          esc(w.name) +
          "</span></a>";
      });
      mobileSection += "</div>";
    }

    var installsSection = MOBILE_UA
      ? '<details class="kw-more"><summary>在电脑上使用？安装浏览器插件</summary>' +
        installGrid() +
        "</details>"
      : '<p class="kw-sec">安装钱包（浏览器插件）</p>' + installGrid();

    html += MOBILE_UA ? mobileSection + installsSection : installsSection + mobileSection;

    var s = readSession();
    if (s.wallet && tokenState() !== "ok") {
      html +=
        '<div class="kw-empty">上次的连接已过期（会话令牌有效期很短）。' +
        "重新签名一次即可继续。</div>";
    }

    body.innerHTML = html;
    all("[data-kw-pick]", body).forEach(function (btn) {
      btn.addEventListener("click", function () {
        var uuid = btn.getAttribute("data-kw-pick");
        var picked = null;
        entries().forEach(function (e) {
          if (e.info.uuid === uuid) picked = e;
        });
        if (picked) connectWith(picked);
      });
    });
  }

  /* ------------------------------------------------------------- SIWE login */

  function siweJson(path, payload) {
    return fetch(apiBase() + path, {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).then(function (res) {
      return res.text().then(function (text) {
        var body;
        try {
          body = text ? JSON.parse(text) : null;
        } catch (_) {
          body = { raw: text };
        }
        if (!res.ok) {
          var msg =
            (body && (body.detail || body.message)) ||
            (typeof body === "object" ? JSON.stringify(body) : text) ||
            res.statusText;
          var err = new Error("HTTP " + res.status + ": " + msg);
          err.status = res.status;
          err.body = body;
          throw err;
        }
        return body;
      });
    });
  }

  async function signIn(provider, account, walletName) {
    activeProviderRef = provider;
    setStatus("获取登录挑战…", null);
    var ch = await siweJson("/v1/auth/siwe/challenge", { address: account });

    setStatus("请在钱包中签名…", null);
    var signature;
    try {
      signature = await provider.request({ method: "personal_sign", params: [ch.message, account] });
    } catch (e) {
      setStatus("签名已取消", false);
      throw e;
    }

    setStatus("验证签名…", null);
    var v = await siweJson("/v1/auth/siwe/verify", {
      nonce: ch.nonce,
      signature: signature,
      address: account,
    });

    var identityId = v.identity_id || "";
    saveSession(account, identityId, v.access_token || "", walletName);
    applyIdentityToUi(account, identityId);

    setStatus("已连接 · " + shortAddr(account) + (identityId ? " · " + identityId : ""), true);
    try {
      emitEvent("karma-wallet-connected", v);
    } catch (_) {}
    return { wallet: account, identityId: identityId, verify: v };
  }

  function applyIdentityToUi(account, identityId) {
    try {
      all("[data-cfg=identity_id]").forEach(function (n) {
        if (identityId) n.value = identityId;
      });
      all("#id-card-id").forEach(function (n) {
        if (identityId && !n.value) n.value = identityId;
      });
      all("#ag-identity").forEach(function (n) {
        if (identityId && !n.value) n.value = identityId;
      });
      all("[data-wallet]").forEach(function (n) {
        n.value = account || "";
      });
      all(".id-main").forEach(function (n) {
        if (identityId) n.textContent = identityId;
      });
      all("[data-bind=wallet_address]").forEach(function (n) {
        n.textContent = shortAddr(account);
      });
      var chip = document.getElementById("top-identity-chip");
      if (chip) {
        chip.textContent = identityId ? identityId : "未连接";
        chip.style.color = identityId ? "var(--ok, #4ade80)" : "";
      }
    } catch (_) {}
  }

  async function connectWith(entry) {
    closeModal();
    var provider = entry.provider;
    var name = (entry.info && entry.info.name) || "钱包";
    setStatus("等待钱包授权…", null);

    var accounts;
    try {
      accounts = await provider.request({ method: "eth_requestAccounts" });
    } catch (e) {
      setStatus("连接失败：" + errText(e), false);
      return;
    }
    if (!accounts || !accounts.length) {
      setStatus("钱包未返回账户", false);
      return;
    }

    try {
      return await signIn(provider, accounts[0], name);
    } catch (e) {
      if (e && e.status) {
        setStatus("登录失败：" + (e.body && (e.body.detail || e.body.message) ? e.body.detail || e.body.message : e.message), false);
      }
      throw e;
    }
  }

  function connect() {
    var list = entries();
    /* 已经能看见钱包就别再让人挑一次：钱包 App 的内置浏览器里只有它自己，
       手机上也一样——多弹一层选择框只会让人觉得「点了没反应」。 */
    if (list.length === 1) return connectWith(list[0]);
    openModal();
    return Promise.resolve(null);
  }

  function disconnect() {
    clearSession();
    setStatus("已断开钱包", null);
    all(".id-main").forEach(function (n) {
      n.textContent = "—";
    });
    var chip = document.getElementById("top-identity-chip");
    if (chip) {
      chip.textContent = "未连接";
      chip.style.color = "";
    }
    try {
      emitEvent("karma-wallet-disconnected");
    } catch (_) {}
  }

  function hasWallet() {
    return entries().length > 0;
  }

  /* ------------------------------------------------- session restore / watch */

  async function restore() {
    var s = readSession();
    if (s.accessToken) {
      global.KARMA_ACCESS_TOKEN = s.accessToken;
      if (s.identityId) global.KARMA_IDENTITY_ID = s.identityId;
      if (tokenState() === "ok" && s.wallet) {
        applyIdentityToUi(s.wallet, s.identityId);
        setStatus(
          "已连接 · " + shortAddr(s.wallet) + (s.identityId ? " · " + s.identityId : ""),
          true
        );
      } else if (s.wallet) {
        setStatus("会话已过期 · 请重新连接钱包", false);
      }
      try {
        emitEvent("karma-session-restored", s);
      } catch (_) {}
    }

    var list = entries();
    if (!list.length) {
      if (!s.wallet) {
        setStatus(
          MOBILE_UA
            ? "未连接 · 点「连接钱包」用手机钱包打开本页"
            : "未检测到钱包 · 点「连接钱包」安装插件或用手机钱包打开",
          null
        );
      }
      return;
    }
    if (!s.wallet) {
      setStatus(
        "已检测到 " + ((list[0].info && list[0].info.name) || "钱包") + " · 点「连接钱包」授权登录",
        null
      );
    }

    var provider = list[0].provider;
    var current = "";
    try {
      var accts = await provider.request({ method: "eth_accounts" });
      current = accts && accts.length ? accts[0] : "";
    } catch (_) {}

    if (s.wallet && current && current.toLowerCase() === s.wallet.toLowerCase()) {
      if (tokenState() !== "ok") {
        // Session token expired but the wallet is still authorised: silently
        // re-run SIWE. This asks the wallet to sign a login message only.
        try {
          await signIn(provider, current, s.walletName || "钱包");
        } catch (_) {
          setStatus("会话已过期 · 请点连接钱包重新签名", false);
        }
      }
    } else if (s.wallet && !current) {
      setStatus("钱包已锁定或未授权 · 请重新连接", false);
    }

    try {
      provider.on && provider.on("accountsChanged", function (accts) {
        if (!accts || !accts.length) {
          disconnect();
        } else if (accts[0].toLowerCase() !== (readSession().wallet || "").toLowerCase()) {
          setStatus("钱包账号已切换 · 请重新连接", false);
          disconnect();
        }
      });
      provider.on && provider.on("chainChanged", function () {
        setStatus("网络已切换 · 如异常请重新连接", null);
      });
    } catch (_) {}
  }

  function ensureFreshToken() {
    var st = tokenState();
    if (st === "ok") return true;
    if (st !== "none") {
      setStatus("会话已过期 · 请重新连接钱包", false);
      try {
        emitEvent("karma-session-expired");
      } catch (_) {}
    }
    return false;
  }

  /* -------------------------------------------------------------------- bind */

  function bind() {
    all("[data-wallet-connect]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        try {
          var r = connect();
          if (r && r.catch) r.catch(function () {});
        } catch (_) {}
      });
    });
    all("[data-wallet-disconnect]").forEach(function (btn) {
      btn.addEventListener("click", disconnect);
    });
    restore();
  }

  /** Best available wallet provider: the one used this session, else the first
   *  discoverable wallet, else the legacy injected provider. */
  function activeProvider() {
    if (activeProviderRef && typeof activeProviderRef.request === "function") return activeProviderRef;
    var list = entries();
    if (list.length && list[0].provider) return list[0].provider;
    return global.ethereum && typeof global.ethereum.request === "function" ? global.ethereum : null;
  }

  global.KarmaWalletAuth = {
    activeProvider: activeProvider,
    connect: connect,
    connectWith: connectWith,
    disconnect: disconnect,
    readSession: readSession,
    hasWallet: hasWallet,
    entries: entries,
    openPicker: openModal,
    tokenState: tokenState,
    ensureFreshToken: ensureFreshToken,
    bind: bind,
    CATALOG: CATALOG,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind);
  } else {
    bind();
  }
})(window);
