/**
 * Connection bar: test API health, optional JWT exchange, persist credentials.
 */
(function (global) {
  var LS_BASE = "karma_cyber_api_base";
  var LS_KEY = "karma_cyber_api_key";
  var LS_ID = "karma_cyber_identity_id";
  var LS_JWT = "karma_console_jwt";

  function api() {
    return global.cyberKarmaApi;
  }

  function el(sel, root) {
    return (root || document).querySelector(sel);
  }

  function applyInputsToWindow(root) {
    var r = root || document.body;
    var b = el("[data-cfg=api_base]", r);
    var k = el("[data-cfg=api_key]", r);
    var i = el("[data-cfg=identity_id]", r);
    if (b && b.value.trim()) global.KARMA_API_BASE = b.value.trim();
    if (k) global.KARMA_API_KEY = k.value.trim();
    if (i && i.value.trim()) global.KARMA_IDENTITY_ID = i.value.trim();
  }

  function savePrefs(root) {
    applyInputsToWindow(root);
    try {
      localStorage.setItem(LS_BASE, global.KARMA_API_BASE || "");
      localStorage.setItem(LS_KEY, global.KARMA_API_KEY || "");
      localStorage.setItem(LS_ID, global.KARMA_IDENTITY_ID || "");
    } catch (_) {}
  }

  function parseAgentFromApiKey(key) {
    var m = String(key || "").trim().match(/^karma_([^_]+)_/);
    return m ? m[1] : "";
  }

  function setStatus(msg, ok) {
    var n = el("[data-connect-status]");
    if (!n) return;
    n.textContent = msg;
    n.style.color = ok ? "var(--ok, #4ade80)" : ok === false ? "#f87171" : "";
  }

  async function testConnection(root) {
    applyInputsToWindow(root);
    savePrefs(root);
    var a = api();
    if (!a) {
      setStatus("Missing karma-public-api.js", false);
      return;
    }
    setStatus("Connecting…", null);
    try {
      var health = await a.getHealth();
      var info = null;
      try {
        info = await a.getV1Info();
      } catch (_) {}
      var parts = ["OK", (health && health.status) || "healthy"];
      if (info && info.app_env) parts.push("env=" + info.app_env);
      if (info && info.version) parts.push("v=" + info.version);
      setStatus(parts.join(" · "), true);
      document.dispatchEvent(new CustomEvent("karma-console-connected"));
    } catch (e) {
      setStatus("Failed: " + (e.message || e), false);
    }
  }

  async function exchangeToken(root) {
    applyInputsToWindow(root);
    var a = api();
    var key = String(global.KARMA_API_KEY || "").trim();
    var agentId = parseAgentFromApiKey(key) || String(global.KARMA_IDENTITY_ID || "").trim();
    if (!agentId || !key) {
      setStatus("Need API key (karma_{agent}_{secret}) or agent id", false);
      return;
    }
    setStatus("Exchanging token…", null);
    try {
      var tok = await a.postAuthToken(agentId, key);
      try {
        sessionStorage.setItem(LS_JWT, tok.access_token || "");
      } catch (_) {}
      setStatus("JWT issued for " + (tok.agent_id || agentId), true);
    } catch (e) {
      setStatus("Token: " + (e.message || e), false);
    }
  }

  function bind(root) {
    var r = root || document.querySelector("[data-console-connect]") || document.body;
    if (!el("[data-action=connect-test]", r) && !el("[data-action=connect-save]", r)) return;

    el("[data-action=connect-test]", r)?.addEventListener("click", function () {
      testConnection(r).catch(function () {});
    });
    el("[data-action=connect-save]", r)?.addEventListener("click", function () {
      savePrefs(r);
      setStatus("Saved to localStorage", true);
      if (global.KarmaConsoleSync && global.KarmaConsoleSync.refreshAll) {
        global.KarmaConsoleSync.refreshAll().catch(function () {});
      }
    });
    el("[data-action=connect-token]", r)?.addEventListener("click", function () {
      exchangeToken(r).catch(function () {});
    });
  }

  global.KarmaConsoleConnect = { bind: bind, testConnection: testConnection, savePrefs: savePrefs };

  document.addEventListener("DOMContentLoaded", function () {
    bind(document.querySelector("[data-console-connect]"));
  });
})(window);
