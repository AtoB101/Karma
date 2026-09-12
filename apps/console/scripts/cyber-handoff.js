/**
 * 交付包 · Hand an agent its Karma identity.
 *
 * The owner already has everything an agent runtime needs — the bootstrap API
 * key (printed once at connect) and, with one wallet signature, a Runtime Key
 * scoped to the agent's role profile. This panel packs those into the single
 * artifact an owner actually hands over: an env file, the matching self-check
 * commands, and the switch that revokes it, instead of four console pages.
 *
 * No wallet private key or seed phrase enters this flow. The Runtime Key comes
 * from an EIP-191 personal signature, and the agent's Ed25519 key stays
 * custodied server-side (0600, revocable).
 */
(function (global) {
  var RUNTIME_URL = "https://karma-network.ai";
  var state = { agent: null, apiKey: "", runtimeKey: "", keys: null, note: "", err: "" };

  function api() { return global.cyberKarmaApi; }
  function $(sel, root) { return (root || document).querySelector(sel); }
  function identity() { return String(global.KARMA_IDENTITY_ID || "").trim(); }
  function esc(v) {
    return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function card() { return document.getElementById("ag-handoff-card"); }
  function host() { return document.getElementById("ag-handoff"); }

  /** The API key is plaintext exactly once, at connect; keep it for this tab. */
  function apiKeyFor(agentId) {
    var bag = global.KarmaAgentKeys || {};
    return String(bag[agentId] || "").trim();
  }

  function copyText(text) {
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text);
        return true;
      }
    } catch (_) {}
    try {
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
      return true;
    } catch (_) { return false; }
  }

  function download(name, text) {
    try {
      var blob = new Blob([text], { type: "text/plain;charset=utf-8" });
      var url = URL.createObjectURL(blob);
      var a = document.createElement("a");
      a.href = url;
      a.download = name;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(function () { URL.revokeObjectURL(url); }, 2000);
      return true;
    } catch (_) { return false; }
  }

  /* ---- the signed strings must match what the server rebuilds (services/runtime_wallet.py) ---- */

  function pyFloatStr(n) {
    var v = Number(n);
    if (!isFinite(v)) return String(n);
    return Number.isInteger(v) ? v.toFixed(1) : String(v);
  }

  function pyUtcIso(ms) {
    var iso = new Date(ms).toISOString();
    var m = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,3}))?Z$/.exec(iso);
    if (!m) return iso;
    var frac = (m[2] || "").padEnd(6, "0");
    return frac === "000000" ? m[1] + "+00:00" : m[1] + "." + frac + "+00:00";
  }

  function buildCreateKeyMsg(f) {
    return [
      "Karma Runtime Key Create",
      "karma_identity_id:" + f.karma_identity_id,
      "wallet_address:" + f.wallet_address,
      "permissions:" + (f.permissions || []).slice().sort().join(","),
      "single_limit:" + pyFloatStr(f.single_limit),
      "daily_limit:" + pyFloatStr(f.daily_limit),
      "expire_time:" + f.expire_time,
      "agent_name:" + (f.agent_name || "console-agent"),
      "agent_binding:" + (f.agent_binding || ""),
    ].join("\n");
  }

  function buildListKeysMsg(f) {
    return [
      "Karma Runtime Key List",
      "karma_identity_id:" + f.karma_identity_id,
      "wallet_address:" + f.wallet_address,
      "client_nonce:" + f.client_nonce,
    ].join("\n");
  }

  async function walletProvider() {
    var p = global.KarmaWalletAuth && global.KarmaWalletAuth.activeProvider && global.KarmaWalletAuth.activeProvider();
    if (p && typeof p.request === "function") return p;
    return null;
  }

  function agentProfileLabel(a) {
    var pid = a && a.scope_profile_id;
    if (!pid) return "未绑定角色档案";
    try {
      var list = JSON.parse(sessionStorage.getItem("karma_console_profiles") || "[]");
      for (var i = 0; i < list.length; i++) {
        if (list[i] && list[i].profile_id === pid) {
          return (list[i].display_name || pid) + " · " + (list[i]["class"] || "");
        }
      }
    } catch (_) {}
    return pid;
  }

  /* ---------------------------------------------------------------- render */

  function envText(a) {
    var lines = ["KARMA_AGENT_ID=" + a.agent_id];
    lines.push("KARMA_API_KEY=" + (state.apiKey || "<粘贴接入时保存的 API Key>"));
    lines.push("KARMA_RUNTIME_URL=" + RUNTIME_URL);
    if (state.runtimeKey) lines.push("KARMA_RUNTIME_KEY=" + state.runtimeKey);
    return lines.join("\n");
  }

  function selfCheckText(a) {
    return [
      "# ① 凭据自检：证明 API Key 有效（只有你自己能看到结果）",
      'curl -s -H "X-Karma-Api-Key: $KARMA_API_KEY" ' + RUNTIME_URL + "/v1/agents/mine",
      "",
      "# ② 对端核验：任何人都能用，对方成交前会查这个",
      "curl -s " + RUNTIME_URL + "/v1/agents/" + a.agent_id + "/p1-status",
    ].join("\n");
  }

  function btn(label, id, cls) {
    return '<button type="button" class="btn ' + (cls || "") + '" id="' + id + '">' + esc(label) + "</button>";
  }

  function runtimeKeyBlock() {
    if (state.runtimeKey) {
      return (
        '<div class="ag-secret"><div class="ag-secret-label">本 agent 的运行时密钥（只显示这一次，请立即连同上面的 env 一起保存）</div>' +
        "<code>" + esc(state.runtimeKey) + "</code>" +
        btn("复制", "ho-copy-rk", "primary") +
        "</div>"
      );
    }
    var out =
      '<p class="ag-hint">运行时密钥用于 agent 服务器向 Karma 请求付款码 / 提交回执 / 申请结算。' +
      "它绑定的权限与限额必须与「设置」页保存的自动授权策略完全一致，所以先保存策略再铸造。</p>" +
      '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px">' +
      btn("铸造本 agent 的运行时密钥", "ho-mint", "primary") +
      btn("读取已有密钥", "ho-list") +
      "</div>";
    if (state.keys) {
      if (!state.keys.length) {
        out += '<p class="ag-hint">这张身份卡还没有运行时密钥。</p>';
      } else {
        out +=
          '<div class="ag-snippet" style="margin-top:10px"><div class="ag-secret-label">已有密钥</div><pre>' +
          esc(
            state.keys
              .map(function (k) {
                return (
                  k.key_id +
                  " · " + (k.status || "") +
                  " · 到期 " + String(k.expire_time || "").slice(0, 10) +
                  " · " + ((k.permissions || []).join(",") || "—") +
                  " · " + (k.agent_name || "—") +
                  " · profile " + (k.profile_id || "—")
                );
              })
              .join("\n")
          ) +
          "</pre></div>";
      }
    }
    return out;
  }

  function render() {
    var h = host();
    if (!h) return;
    var a = state.agent;
    if (!a) {
      h.innerHTML = '<p class="err">' + esc(state.err || "未找到该 agent") + "</p>";
      return;
    }
    var env = envText(a);
    h.innerHTML =
      '<div class="ag-result-head"><b>' + esc(a.name || a.agent_id) + "</b>" +
      '<span class="tag ' + (a.p1_ready ? "ok" : "warn") + '">' + (a.p1_ready ? "P1 就绪" : "P1 未就绪") + "</span>" +
      '<span class="tag">' + esc(agentProfileLabel(a)) + "</span></div>" +
      '<p class="ag-hint">主体身份卡 ' + esc(a.owner_identity_id || identity() || "—") +
      " → 本 agent " + esc(a.agent_id) + "</p>" +

      '<div class="ag-snippet" style="margin-top:14px"><div class="ag-secret-label">① 环境变量 · karma-agent.env</div>' +
      "<pre>" + esc(env) + "</pre>" +
      '<div style="display:flex;gap:8px;flex-wrap:wrap">' +
      (state.apiKey ? "" : '<span class="ag-hint">本次会话没有该 agent 的 API Key 明文（只在接入时返回一次）。可重新接入一个 agent，或把占位符替换成你当时保存的值。</span>') +
      "</div>" +
      '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px">' +
      btn("复制 env", "ho-copy-env", "primary") +
      btn("下载 karma-agent.env", "ho-download") +
      "</div></div>" +

      '<div class="ag-snippet" style="margin-top:14px"><div class="ag-secret-label">② 运行时密钥（绑定本 agent）</div>' +
      runtimeKeyBlock() +
      "</div>" +

      '<div class="ag-snippet" style="margin-top:14px"><div class="ag-secret-label">③ 接入自检</div>' +
      "<pre>" + esc(selfCheckText(a)) + "</pre>" +
      '<div style="display:flex;gap:8px;flex-wrap:wrap">' +
      btn("复制命令", "ho-copy-check") +
      btn("在页面运行自检", "ho-run-check") +
      '<span class="api-status" id="ho-check-status"></span>' +
      "</div></div>" +

      '<div class="ag-next" style="margin-top:14px"><b>④ 交付说明</b><ol>' +
      "<li>把上面的 env 写进 agent 运行时的环境变量（或直接下载文件）。</li>" +
      "<li>agent 用 KARMA_AGENT_ID + KARMA_API_KEY 完成身份识别；用 KARMA_RUNTIME_KEY 请求付款码、提交回执、申请结算。</li>" +
      "<li>对方成交前会查 p1-status；这就是 Karma 对这笔收付的验证依据。</li>" +
      "<li>不再需要这个 agent 时，用下面「停用并销毁密钥」——Karma 托管的运行密钥会一并销毁。</li>" +
      "</ol></div>" +

      '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:14px">' +
      btn("停用并销毁密钥", "ho-revoke", "red") +
      btn("刷新", "ho-refresh") +
      "</div>" +

      (state.note ? '<p class="ag-hint" style="margin-top:10px">' + esc(state.note) + "</p>" : "") +
      (state.err ? '<p class="err" style="margin-top:10px">' + esc(state.err) + "</p>" : "");

    wire(a, env);
  }

  function wire(a, env) {
    var bind = function (id, fn) {
      var n = document.getElementById(id);
      if (n) n.addEventListener("click", fn);
    };
    bind("ho-copy-env", function () { state.note = copyText(env) ? "已复制 env" : "复制失败，请手动选择"; render(); });
    bind("ho-download", function () {
      state.note = download("karma-agent.env", env + "\n") ? "已下载 karma-agent.env" : "下载失败";
      render();
    });
    bind("ho-copy-rk", function () { state.note = copyText(state.runtimeKey) ? "已复制运行时密钥" : "复制失败"; render(); });
    bind("ho-copy-check", function () { state.note = copyText(selfCheckText(a)) ? "已复制自检命令" : "复制失败"; render(); });
    bind("ho-mint", function () { mint(a); });
    bind("ho-list", function () { listKeys(); });
    bind("ho-run-check", function () { runCheck(a); });
    bind("ho-revoke", function () { revoke(a); });
    bind("ho-refresh", function () { open(a.agent_id); });
  }

  function setCheckStatus(msg, ok) {
    var n = document.getElementById("ho-check-status");
    if (!n) return;
    n.textContent = msg;
    n.style.color = ok === false ? "#f87171" : ok === true ? "var(--accent,#4ade80)" : "";
  }

  async function runCheck(a) {
    setCheckStatus("核验中…");
    try {
      var st = await api().karmaFetch("/v1/agents/" + encodeURIComponent(a.agent_id) + "/p1-status", {
        method: "GET",
        headers: { Accept: "application/json" },
      });
      var ready = st && st.p1_ready === true;
      var gaps = (st && (st.gaps || st.p1_gaps)) || [];
      setCheckStatus(
        ready ? "P1 就绪：对端可以核验并成交" : "P1 未就绪，待补齐：" + (gaps.length ? gaps.join(", ") : "见原始响应"),
        ready
      );
    } catch (e) {
      setCheckStatus("核验失败：" + (e.message || e), false);
    }
  }

  async function listKeys() {
    var prov = await walletProvider();
    if (!prov) { state.err = "未检测到可用钱包，请先用右上角「连接钱包」认证"; render(); return; }
    state.err = "";
    state.note = "等待钱包签名…";
    render();
    try {
      var accounts = await prov.request({ method: "eth_requestAccounts" });
      var wallet = accounts[0];
      var nonce = "console-" + Date.now().toString(36);
      var msg = buildListKeysMsg({ karma_identity_id: identity(), wallet_address: wallet, client_nonce: nonce });
      var sig = await prov.request({ method: "personal_sign", params: [msg, wallet] });
      var r = await global.karmaRuntimeApi.runtimeListKeys({
        wallet_address: wallet,
        karma_identity_id: identity(),
        wallet_signature: sig,
        client_nonce: nonce,
      });
      state.keys = (r && r.keys) || [];
      state.note = "已读取 " + state.keys.length + " 个运行时密钥";
    } catch (e) {
      state.note = "";
      state.err = "读取失败：" + (e.message || e);
    }
    render();
  }

  async function mint(a) {
    state.err = "";
    if (!identity()) { state.err = "请先连接钱包完成认证"; render(); return; }
    var prov = await walletProvider();
    if (!prov) { state.err = "未检测到可用钱包，请先用右上角「连接钱包」认证"; render(); return; }
    state.note = "读取自动授权策略…";
    render();
    var policy = null;
    try {
      policy = await api().getAutomationPolicy(identity());
    } catch (_) {}
    if (!policy || !policy.permissions || !policy.permissions.length) {
      state.note = "";
      state.err =
        "还没有保存自动授权策略。运行密钥的权限与限额必须与策略完全一致，请先到「设置」页点「保存授权策略」，再回来铸造。";
      render();
      return;
    }
    try {
      state.note = "等待钱包签名…";
      render();
      var accounts = await prov.request({ method: "eth_requestAccounts" });
      var wallet = accounts[0];
      var expireIso = pyUtcIso(Date.now() + 7 * 86400e3);
      var fields = {
        karma_identity_id: identity(),
        wallet_address: wallet,
        permissions: policy.permissions.slice(),
        single_limit: Number(policy.single_limit) || 100,
        daily_limit: Number(policy.daily_limit) || 500,
        expire_time: expireIso,
        agent_name: a.name || a.agent_id,
        agent_binding: a.agent_id,
      };
      var sig = await prov.request({ method: "personal_sign", params: [buildCreateKeyMsg(fields), wallet] });
      var r = await global.karmaRuntimeApi.runtimeCreateKey({
        wallet_address: wallet,
        karma_identity_id: fields.karma_identity_id,
        wallet_signature: sig,
        permissions: fields.permissions,
        single_limit: fields.single_limit,
        daily_limit: fields.daily_limit,
        expire_time: expireIso,
        agent_name: fields.agent_name,
        agent_binding: a.agent_id,
        profile_id: a.scope_profile_id || undefined,
      });
      state.runtimeKey = (r && r.runtime_key) || "";
      state.keys = null;
      state.note =
        "已铸造运行时密钥（" + ((r && r.key_id) || "") + "，到期 " + String((r && r.expire_time) || "").slice(0, 10) +
        "）。明文只显示这一次，请连同 env 一起交给 agent。";
    } catch (e) {
      state.note = "";
      state.err = "铸造失败：" + (e.message || e);
    }
    render();
  }

  async function revoke(a) {
    if (!global.confirm("停用 " + a.agent_id + " 并销毁 Karma 托管的运行密钥？此操作不可撤销。")) return;
    state.note = "停用中…";
    state.err = "";
    render();
    try {
      await api().ownerRevokeAgent(a.agent_id);
      state.note = "已停用 " + a.agent_id;
      state.keys = null;
      state.runtimeKey = "";
      document.dispatchEvent(new CustomEvent("karma-agent-revoked", { detail: { agent_id: a.agent_id } }));
    } catch (e) {
      state.note = "";
      state.err = "停用失败：" + (e.message || e);
    }
    render();
  }

  async function open(agentId) {
    state.agent = null;
    state.runtimeKey = "";
    state.keys = null;
    state.note = "";
    state.err = "";
    state.apiKey = apiKeyFor(agentId);
    var c = card();
    if (c) c.hidden = false;
    if (host()) host().innerHTML = '<p class="muted">读取 agent…</p>';
    try {
      var body = await api().listMyAgents();
      var list = (body && body.agents) || [];
      for (var i = 0; i < list.length; i++) {
        if (list[i] && list[i].agent_id === agentId) state.agent = list[i];
      }
      if (!state.agent) state.err = "这张身份卡名下没有找到该 agent";
    } catch (e) {
      state.err = "读取失败：" + (e.message || e);
    }
    render();
    if (c && c.scrollIntoView) c.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function close() {
    var c = card();
    if (c) c.hidden = true;
  }

  function init() {
    document.addEventListener("click", function (ev) {
      var t = ev.target;
      if (!t || !t.closest) return;
      var openBtn = t.closest("[data-agent-handoff]");
      if (openBtn) {
        ev.preventDefault();
        open(openBtn.getAttribute("data-agent-handoff"));
        return;
      }
      if (t.closest("#ag-handoff-close")) close();
    });
    document.addEventListener("karma-agent-revoked", function () {
      if (global.KarmaAgents && global.KarmaAgents.refresh) global.KarmaAgents.refresh();
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();

  global.KarmaHandoff = { open: open, close: close };
})(window);
