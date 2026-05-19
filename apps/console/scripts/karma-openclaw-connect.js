/**
 * Karma Console — OpenClaw One-Click Connect
 * ===========================================
 * Auto-discovers OpenClaw gateway and Karma API, verifies connectivity,
 * generates a connection manifest for agent runtimes.
 */
(function (global) {
  "use strict";

  var LS_OC_URL = "karma_openclaw_gateway_url";
  var LS_OC_READY = "karma_openclaw_connected";

  // ── Helpers ──────────────────────────────────────────────

  function $el(sel, root) {
    return (root || document).querySelector(sel);
  }

  function $$el(sel, root) {
    return (root || document).querySelectorAll(sel);
  }

  function setStatus(el, msg, ok) {
    if (!el) return;
    el.textContent = msg;
    el.className = "status " + (ok === true ? "ok" : ok === false ? "err" : "info");
  }

  function getApi() {
    return global.cyberKarmaApi;
  }

  // ── Discovery ────────────────────────────────────────────

  function discoverOpenClawGateway() {
    var el = $el("[data-oc-gateway]");
    var val = (el && el.value.trim()) || "";
    if (val) return val;
    try {
      var saved = localStorage.getItem(LS_OC_URL);
      if (saved) return saved;
    } catch (_) {}
    // Default: same machine, standard OpenClaw port
    return "http://127.0.0.1:18789";
  }

  function discoverKarmaApi() {
    if (global.KARMA_API_BASE) return global.KARMA_API_BASE;
    var el = $el("[data-cfg=api_base]");
    if (el && el.value.trim()) return el.value.trim();
    return "http://localhost:8000";
  }

  function discoverAgentId() {
    if (global.KARMA_IDENTITY_ID) return global.KARMA_IDENTITY_ID;
    var el = $el("[data-cfg=identity_id]");
    if (el && el.value.trim()) return el.value.trim();
    // Parse from API key
    var key = String(global.KARMA_API_KEY || "").trim();
    var m = key.match(/^karma_([^_]+)_/);
    return m ? m[1] : "";
  }

  // ── Probing ──────────────────────────────────────────────

  async function probeOpenClaw(url) {
    var st = $el("[data-oc-probe-status]");
    setStatus(st, "Probing OpenClaw gateway...", null);
    try {
      var resp = await fetch(url, { method: "GET", signal: AbortSignal.timeout(5000) });
      if (resp.ok || resp.status < 500) {
        setStatus(st, "OpenClaw gateway reachable (" + resp.status + ")", true);
        return { ok: true, status: resp.status };
      }
      setStatus(st, "Gateway returned " + resp.status, false);
      return { ok: false, error: "HTTP " + resp.status };
    } catch (e) {
      setStatus(st, "Gateway unreachable: " + (e.message || e), false);
      return { ok: false, error: e.message || String(e) };
    }
  }

  async function probeKarmaApi(url) {
    var st = $el("[data-oc-karma-status]");
    setStatus(st, "Probing Karma API...", null);
    try {
      var resp = await fetch(url + "/v1/info", {
        method: "GET",
        signal: AbortSignal.timeout(5000),
      });
      if (resp.ok) {
        var info = await resp.json();
        setStatus(
          st,
          "Karma API OK — env=" + (info.app_env || "?") + " v=" + (info.version || "?"),
          true
        );
        return { ok: true, info: info };
      }
      setStatus(st, "Karma API returned " + resp.status, false);
      return { ok: false, error: "HTTP " + resp.status };
    } catch (e) {
      setStatus(st, "Karma API unreachable: " + (e.message || e), false);
      return { ok: false, error: e.message || String(e) };
    }
  }

  // ── Manifest ─────────────────────────────────────────────

  function buildManifest(runtimeUrl, apiKey, agentId, openclawGw) {
    return {
      karma_runtime_url: runtimeUrl,
      karma_api_key: apiKey,
      agent_id: agentId,
      openclaw_gateway: openclawGw || null,
      karma_version: "0.1.0",
      created_at_utc: new Date().toISOString(),
    };
  }

  function displayManifest(manifest) {
    var pre = $el("[data-oc-manifest]");
    if (!pre) return;
    pre.textContent = JSON.stringify(manifest, null, 2);
  }

  function downloadManifest(manifest) {
    var blob = new Blob([JSON.stringify(manifest, null, 2)], { type: "application/json" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "karma-connect.json";
    a.click();
    URL.revokeObjectURL(a.href);
  }

  // ── Setup instructions ───────────────────────────────────

  function showSetupInstructions(manifest) {
    var el = $el("[data-oc-instructions]");
    if (!el) return;

    var agentId = manifest.agent_id || "agent-001";
    var runtimeUrl = manifest.karma_runtime_url || "http://localhost:8000";
    var apiKey = manifest.karma_api_key || "karma_" + agentId + "_your_secret";

    el.innerHTML = [
      "<h3>Agent Runtime Setup</h3>",
      "",
      "<h4>1. Install Karma SDK</h4>",
      "<pre><code>pip install -e ./packages/karma-openclaw</code></pre>",
      "",
      "<h4>2. Set environment variables</h4>",
      "<pre><code>export KARMA_RUNTIME_URL=" + runtimeUrl + "</code></pre>",
      "<pre><code>export KARMA_API_KEY=" + maskKey(apiKey) + "</code></pre>",
      "<pre><code>export KARMA_AGENT_ID=" + agentId + "</code></pre>",
      "",
      "<h4>3. Start MCP bridge</h4>",
      "<pre><code>karma-openclaw-mcp</code></pre>",
      "",
      "<h4>4. In OpenClaw, register the MCP bridge</h4>",
      "<p>Add to your agent config:</p>",
      "<pre><code>{",
      '  "mcpServers": {',
      '    "karma": {',
      '      "command": "karma-openclaw-mcp",',
      '      "env": {',
      '        "KARMA_RUNTIME_URL": "' + runtimeUrl + '",',
      '        "KARMA_API_KEY": "' + maskKey(apiKey) + '"',
      "      }",
      "    }",
      "  }",
      "}</code></pre>",
      "",
      "<h4>5. Python SDK (one-liner)</h4>",
      "<pre><code>from karma.sdk import discover_and_connect",
      "agent = await discover_and_connect()",
      "result, receipt = await agent.run_tool(",
      '    task_id="my-task",',
      '    tool_name="browser.navigate",',
      "    tool_fn=my_fn,",
      '    input_data={"url": "https://example.com"},',
      ")</code></pre>",
    ].join("\n");
  }

  function maskKey(key) {
    if (!key || key.length < 12) return key;
    return key.slice(0, 8) + "..." + key.slice(-4);
  }

  // ── One-click action ─────────────────────────────────────

  async function oneClickConnect() {
    var gatewayUrl = discoverOpenClawGateway();
    var karmaUrl = discoverKarmaApi();
    var agentId = discoverAgentId();
    var apiKey = String(global.KARMA_API_KEY || "").trim();

    // Save gateway preference
    try { localStorage.setItem(LS_OC_URL, gatewayUrl); } catch (_) {}

    // Probe both
    var ocResult = await probeOpenClaw(gatewayUrl);
    var karmaResult = { ok: false };
    if (karmaUrl) {
      karmaResult = await probeKarmaApi(karmaUrl);
    }

    // Build manifest
    var manifest = buildManifest(karmaUrl, apiKey, agentId, gatewayUrl);
    displayManifest(manifest);
    showSetupInstructions(manifest);

    // Store connected state
    if (ocResult.ok || karmaResult.ok) {
      try { localStorage.setItem(LS_OC_READY, "true"); } catch (_) {}
      var summaryEl = $el("[data-oc-summary]");
      if (summaryEl) {
        var parts = [];
        if (ocResult.ok) parts.push("OpenClaw ✅");
        else parts.push("OpenClaw ❌");
        if (karmaResult.ok) parts.push("Karma ✅");
        else parts.push("Karma ❌");
        summaryEl.textContent = "Connection: " + parts.join(" | ");
        summaryEl.style.color = (ocResult.ok && karmaResult.ok) ? "#4ade80" : "#fbbf24";
      }
    }

    // Enable download button
    var dlBtn = $el("[data-oc-download]");
    if (dlBtn) dlBtn.disabled = false;

    return { openclaw: ocResult, karma: karmaResult, manifest: manifest };
  }

  // ── Bind UI ──────────────────────────────────────────────

  function bind(root) {
    var r = root || $el("[data-openclaw-connect]") || document.body;

    // One-click button
    $el("[data-action=oc-connect]", r)?.addEventListener("click", function () {
      oneClickConnect().catch(function (e) {
        var st = $el("[data-oc-probe-status]");
        setStatus(st, "Error: " + (e.message || e), false);
      });
    });

    // Download manifest
    $el("[data-oc-download]", r)?.addEventListener("click", function () {
      var pre = $el("[data-oc-manifest]");
      if (!pre || !pre.textContent) return;
      try {
        downloadManifest(JSON.parse(pre.textContent));
      } catch (_) {}
    });

    // Copy manifest
    $el("[data-action=oc-copy]", r)?.addEventListener("click", function () {
      var pre = $el("[data-oc-manifest]");
      if (!pre || !pre.textContent) return;
      navigator.clipboard.writeText(pre.textContent).then(function () {
        var btn = $el("[data-action=oc-copy]");
        if (btn) {
          btn.textContent = "Copied!";
          setTimeout(function () { btn.textContent = "Copy Manifest"; }, 2000);
        }
      });
    });
  }

  // ── Export ───────────────────────────────────────────────

  global.KarmaOpenClawConnect = {
    discoverOpenClawGateway: discoverOpenClawGateway,
    discoverKarmaApi: discoverKarmaApi,
    discoverAgentId: discoverAgentId,
    probeOpenClaw: probeOpenClaw,
    probeKarmaApi: probeKarmaApi,
    oneClickConnect: oneClickConnect,
    buildManifest: buildManifest,
    bind: bind,
  };

  document.addEventListener("DOMContentLoaded", function () {
    bind();
  });
})(window);
