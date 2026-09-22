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
  var FALLBACK_RUNTIME_URL = "https://karma-network.ai";
  var state = { agent: null, apiKey: "", runtimeKey: "", keys: null, note: "", err: "", pendingKeyId: "" };

  /**
   * 交付给 agent 的接入地址：跟着操作台里选的那台节点走。
   *
   * 这个地址会被写进 agent 的 env、也会出现在自检 curl 里。写死成厂商域名的话，
   * 用户在自己的操作台里换了节点，agent 拿到的还是厂商的地址 —— 那就白换了。
   */
  function runtimeUrl() {
    try {
      if (global.KarmaNodes && global.KarmaNodes.effectiveBase) {
        var base = String(global.KarmaNodes.effectiveBase() || "").trim().replace(/\/+$/, "");
        if (base) return base;
      }
    } catch (_) {}
    return FALLBACK_RUNTIME_URL;
  }

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

  /* 匹配码激活：用户在操作台敲下 agent 显示的那串码，签名确认后绑定才生效。 */
  function normalizeCode(v) {
    var compact = String(v == null ? "" : v).toUpperCase().replace(/[^0-9A-Z]/g, "");
    return compact.length === 8 ? compact.slice(0, 4) + "-" + compact.slice(4) : compact;
  }

  function buildConfirmBindMsg(f) {
    return [
      "Karma Runtime Key Bind Confirm",
      "key_id:" + f.key_id,
      "karma_identity_id:" + f.karma_identity_id,
      "wallet_address:" + f.wallet_address,
      "activation_code:" + f.activation_code,
      "client_nonce:" + f.client_nonce,
    ].join("\n");
  }

  function buildRejectBindMsg(f) {
    return [
      "Karma Runtime Key Bind Reject",
      "key_id:" + f.key_id,
      "karma_identity_id:" + f.karma_identity_id,
      "wallet_address:" + f.wallet_address,
      "client_nonce:" + f.client_nonce,
    ].join("\n");
  }

  /* 一键取消绑定：摘掉 agent 公钥，钥匙回到「未激活」。服务端按同一格式重建。 */
  function buildUnbindKeyMsg(f) {
    return [
      "Karma Runtime Key Unbind",
      "key_id:" + f.key_id,
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
    // env 文件是机器读的，占位符统一用英文，避免英文页面里混进中文。
    lines.push("KARMA_API_KEY=" + (state.apiKey || "<paste the API key you saved when the agent connected>"));
    lines.push("KARMA_RUNTIME_URL=" + runtimeUrl());
    if (state.runtimeKey) lines.push("KARMA_RUNTIME_KEY=" + state.runtimeKey);
    return lines.join("\n");
  }

  /**
   * 未激活提示：时限只在匹配码上（3 分钟），钥匙本身不设到期 —— 没输对码就一直不能用。
   * 拼成一整句（不掺变量）才翻得到，见 i18n-phrase。
   */
  function activationHintText() {
    return (
      "这把钥匙还没激活，现在不能动钱。agent 用 /runtime/bind-key 申请接入后会把 8 位匹配码给你，" +
      "你到「设置 → 接入确认」输码 + 钱包签名确认之后它才生效；匹配码 3 分钟内有效，" +
      "过期就让 agent 重新申请一次（钥匙不用重铸）。"
    );
  }

  function selfCheckText(a) {
    return [
      "# ① 凭据自检：证明 API Key 有效（只有你自己能看到结果）",
      'curl -s -H "X-Karma-Api-Key: $KARMA_API_KEY" ' + runtimeUrl() + "/v1/agents/mine",
      "",
      "# ② 对端核验：任何人都能用，对方成交前会查这个",
      "curl -s " + runtimeUrl() + "/v1/agents/" + a.agent_id + "/p1-status",
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
          // 每段文字都单独成节点：<pre> 里的整串会被翻译引擎跳过，
          // 拆成元素之后「 · 到期 」这种碎片才翻得到。
          '<div class="ag-snippet" style="margin-top:10px"><div class="ag-secret-label">已有密钥</div>' +
          '<div class="ag-key-list">' +
          state.keys
            .map(function (k) {
              return (
                '<div class="ag-key-line">' +
                "<span>" + esc(k.key_id) + "</span>" +
                "<span> · </span>" +
                "<span>" + esc(k.status || "") + "</span>" +
                (k.activation_required ? "<span> · </span><span>" + esc("未激活（等匹配码）") + "</span>" : "") +
                "<span> · 到期 </span>" +
                "<span>" + esc(String(k.expire_time || "").slice(0, 10)) + "</span>" +
                "<span> · </span>" +
                "<span>" + esc((k.permissions || []).join(",") || "—") + "</span>" +
                "<span> · </span>" +
                "<span>" + esc(k.agent_name || "—") + "</span>" +
                "<span> · profile </span>" +
                "<span>" + esc(k.profile_id || "—") + "</span>" +
                "</div>"
              );
            })
            .join("") +
          "</div></div>" +
          bindingHint(state.keys);
      }
    }
    return out;
  }

  // 绑没绑 agent 公钥是用户唯一看得懂的安全状态：绑了以后，光有钥匙字符串花不了钱。
  // 单独一段、整句文案 —— 别塞进上面那串 <pre> 里，那样翻译引擎取不到整段。
  function bindingHint(keys) {
    var live = (keys || []).filter(function (k) { return (k.status || "") === "active"; });
    if (!live.length) return "";
    state.pendingKeyId = "";
    var out = "";
    // ① 有 agent 申请了、还没输码：这是用户在操作台唯一要做的事，放最上面。
    var waiting = live.filter(function (k) {
      return k.pending_binding && !k.pending_binding.expired;
    });
    if (waiting.length) {
      var k = waiting[0];
      var pb = k.pending_binding || {};
      state.pendingKeyId = k.key_id;
      out +=
        '<div class="ag-snippet" style="margin-top:10px">' +
        '<div class="ag-secret-label">有一个 agent 正在申请接入这把密钥（还没生效）</div>' +
        '<p class="ag-hint">让 agent 把它拿到的那串匹配码显示给你，抄进下面的框里。签名确认之后，' +
        "这个 agent 才能用这把密钥；在确认之前它花钱的请求一律被拒。</p>" +
        '<p class="ag-hint">这把钥匙现在还没激活：没走完这一步，谁都拿它花不了钱。</p>' +
        '<p class="ag-hint">agent 公钥指纹：' + esc(pb.agent_fingerprint || "—") +
        " · 匹配码有效至 " + esc(String(pb.expires_at || "").slice(0, 16).replace("T", " ")) +
        " · 还能试 " + esc(pb.attempts_left == null ? "—" : pb.attempts_left) + " 次</p>" +
        '<input id="ho-bind-code" type="text" inputmode="latin" autocomplete="off" spellcheck="false"' +
        ' maxlength="9" placeholder="XXXX-XXXX" value="" />' +
        '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px">' +
        btn("确认绑定（要钱包签名）", "ho-bind-confirm", "primary") +
        btn("拒绝这次接入", "ho-bind-reject", "red") +
        "</div>" +
        (waiting.length > 1
          ? '<p class="ag-hint">还有 ' + esc(waiting.length - 1) + " 个待确认请求，处理完这个再点「读取已有密钥」。</p>"
          : "") +
        "</div>";
    } else {
      var stale = live.filter(function (k) { return k.pending_binding && k.pending_binding.expired; });
      if (stale.length) {
        out +=
          '<p class="ag-hint">有一个 agent 的接入申请已经过期没有确认（匹配码 3 分钟有效）：' +
          "让 agent 重新申请一次，会把新的匹配码给你。</p>";
      }
    }
    // ② 绑定总状态：绑了以后光有钥匙字符串花不了钱。
    var unbound = live.filter(function (k) { return (k.key_binding || "service") !== "agent"; });
    if (!unbound.length) {
      out += '<p class="ag-hint">运行时密钥已绑定 agent 公钥：每个请求都要 agent 私钥签名，光有钥匙不能办事</p>';
    } else {
      out +=
        '<p class="ag-hint">运行时密钥还没绑定 agent 公钥：agent 首次接入时会申请绑定，' +
        "你在操作台输入它给的匹配码之后才生效；在绑定生效前光有钥匙就能用。</p>";
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
      '<div class="ag-check-lines">' +
      selfCheckText(a)
        .split("\n")
        .map(function (line) { return "<div>" + (line ? esc(line) : "&nbsp;") + "</div>"; })
        .join("") +
      "</div>" +
      '<div style="display:flex;gap:8px;flex-wrap:wrap">' +
      btn("复制命令", "ho-copy-check") +
      btn("在页面运行自检", "ho-run-check") +
      '<span class="api-status" id="ho-check-status"></span>' +
      "</div></div>" +

      '<div class="ag-next" style="margin-top:14px"><b>④ 交付说明</b><ol>' +
      "<li>把上面的 env 写进 agent 运行时的环境变量（或直接下载文件）。</li>" +
      "<li>agent 用 KARMA_AGENT_ID + KARMA_API_KEY 完成身份识别；用 KARMA_RUNTIME_KEY 请求付款码、提交回执、申请结算。</li>" +
      "<li>第一次动用这把钥匙的钱之前，agent 会申请绑定自己的公钥并把 8 位匹配码给你；你到「设置 → 接入确认」输码 + 钱包签名确认，它才能真正付款（在那之前一律被拒）。</li>" +
      "<li>对方成交前会查 p1-status；这就是 Karma 对这笔收付的验证依据。</li>" +
      "<li>不再需要这个 agent 时，用下面「停用并销毁密钥」——Karma 托管的运行密钥会一并销毁。</li>" +
      "</ol></div>" +

      '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:14px">' +
      btn("停用并销毁密钥", "ho-revoke", "red") +
      btn("刷新", "ho-refresh") +
      "</div>" +

      (state.note ? '<p class="ag-hint" style="margin-top:10px">' + esc(state.note) + "</p>" : "") +
      (state.activationHint ? '<p class="ag-hint" style="margin-top:6px">' + esc(state.activationHint) + "</p>" : "") +
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
    bind("ho-bind-confirm", function () { confirmBind(); });
    bind("ho-bind-reject", function () { rejectBind(); });
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

  // agent 把匹配码给主人 → 主人在这里输码 + 钱包签名 → 绑定才落库。
  async function confirmBind() {
    var keyId = state.pendingKeyId;
    if (!keyId) { state.err = "没有待确认的接入请求，先点「读取已有密钥」"; render(); return; }
    var input = document.getElementById("ho-bind-code");
    var code = normalizeCode(input ? input.value : "");
    if (!/^[0-9A-Z]{4}-[0-9A-Z]{4}$/.test(code)) {
      state.err = "匹配码是 8 位（形如 XXXX-XXXX），请照 agent 显示的原样抄一遍";
      render();
      return;
    }
    var prov = await walletProvider();
    if (!prov) { state.err = "未检测到可用钱包，请先用右上角「连接钱包」认证"; render(); return; }
    state.err = "";
    state.note = "等待钱包签名…";
    render();
    try {
      var accounts = await prov.request({ method: "eth_requestAccounts" });
      var wallet = accounts[0];
      var nonce = "console-" + Date.now().toString(36);
      var msg = buildConfirmBindMsg({
        key_id: keyId,
        karma_identity_id: identity(),
        wallet_address: wallet,
        activation_code: code,
        client_nonce: nonce,
      });
      var sig = await prov.request({ method: "personal_sign", params: [msg, wallet] });
      var r = await global.karmaRuntimeApi.runtimeConfirmBindKey({
        key_id: keyId,
        karma_identity_id: identity(),
        wallet_address: wallet,
        wallet_signature: sig,
        activation_code: code,
        client_nonce: nonce,
      });
      await listKeys();
      state.note =
        "已确认绑定：" + ((r && r.agent_fingerprint) || "—") +
        "。这个 agent 之后每个请求都要私钥签名，被偷走的钥匙单独没用。";
    } catch (e) {
      state.note = "";
      state.err = "确认失败：" + (e.message || e);
    }
    render();
  }

  async function rejectBind() {
    var keyId = state.pendingKeyId;
    if (!keyId) { state.err = "没有待确认的接入请求"; render(); return; }
    if (!global.confirm("拒绝这次接入？这个 agent 拿到的匹配码会作废，密钥本身不受影响。")) return;
    var prov = await walletProvider();
    if (!prov) { state.err = "未检测到可用钱包，请先用右上角「连接钱包」认证"; render(); return; }
    state.err = "";
    state.note = "等待钱包签名…";
    render();
    try {
      var accounts = await prov.request({ method: "eth_requestAccounts" });
      var wallet = accounts[0];
      var nonce = "console-" + Date.now().toString(36);
      var msg = buildRejectBindMsg({
        key_id: keyId,
        karma_identity_id: identity(),
        wallet_address: wallet,
        client_nonce: nonce,
      });
      var sig = await prov.request({ method: "personal_sign", params: [msg, wallet] });
      await global.karmaRuntimeApi.runtimeRejectBindKey({
        key_id: keyId,
        karma_identity_id: identity(),
        wallet_address: wallet,
        wallet_signature: sig,
        client_nonce: nonce,
      });
      await listKeys();
      state.note = "已拒绝这次接入。要重新接入，让 agent 再申请一次。";
    } catch (e) {
      state.note = "";
      state.err = "拒绝失败：" + (e.message || e);
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
        agent_id: a.agent_id,
        profile_id: a.scope_profile_id || undefined,
      });
      state.runtimeKey = (r && r.runtime_key) || "";
      state.keys = null;
      state.note =
        "已铸造运行时密钥（" + ((r && r.key_id) || "") + "，到期 " + String((r && r.expire_time) || "").slice(0, 10) +
        "）。明文只显示这一次，请连同 env 一起交给 agent。";
      // 未激活的钥匙说清楚「现在花不了钱 + 差哪一步 + 期限」。
      // 单独成一个文本节点（下面 render 里那个 <p>），拼进 note 会让整段翻不到。
      state.activationHint = activationHintText();
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
    state.activationHint = "";
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

  // 匹配码激活的签名消息只写一份：设置页那张「接入确认」卡片（cyber-bind-requests.js）
  // 也用这几个函数，两边各抄一套的话，服务端一改就静默失配。
  global.KarmaHandoff = {
    open: open,
    close: close,
    normalizeCode: normalizeCode,
    buildConfirmBindMsg: buildConfirmBindMsg,
    buildRejectBindMsg: buildRejectBindMsg,
    buildUnbindKeyMsg: buildUnbindKeyMsg,
    walletProvider: walletProvider,
    // 交付包里那个接入地址：给测试和「配对接入」面板复用，别各写一份。
    runtimeUrl: runtimeUrl,
  };
})(window);
