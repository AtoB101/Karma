/**
 * 操作台 · 「给 agent 授权」向导（锁仓之后的一条直线）。
 *
 * 这些动作原本散在「身份」页的额度分配、「设置」页的自动授权策略、以及「交付包」
 * 的运行时密钥铸造里，用户要在三张卡之间来回跳。这里按顺序收成 4 步 + 1 个按钮：
 *
 *   1 选身份    选一个子身份（没有就先建）        POST /v1/identity/role-profiles
 *   2 授权额度  从主身份锁仓里划额度              PUT  /v1/capacity/{id}/allocations
 *   3 定类型    生活 / 工作 / 企业助理            PUT  /v1/identity/role-profiles/{pid}
 *   4 划边界    权限 + 单笔/日上限 + 人工确认     PUT  /v1/identities/{id}/automation-policy
 *   → 生成 SDK  钱包 EIP-191 签名一次             POST /runtime/create-key
 *
 * 安全边界：只用到 SIWE 会话 + 一次个人签名，不接触私钥 / 助记词；
 * 运行时密钥明文只在生成的那一次展示。
 */
(function (global) {
  "use strict";

  var TYPES = {
    life: { label: "生活助理", klass: "individual" },
    work: { label: "工作助理", klass: "individual" },
    company: { label: "企业商业助理", klass: "enterprise" },
  };
  var CLASS_TO_TYPE = { individual: "life", merchant: "work", enterprise: "company" };
  var HUMAN_LABELS = {
    above_single: "超过单笔最高时找我确认",
    always: "每一笔都找我确认",
    off: "全部自动，不再确认",
  };
  /* 必须与 services/runtime_key_service.py 的 ALLOWED_PERMISSIONS 一致。 */
  var PERMS = [
    { key: "request_voucher", label: "请求付款授权", hint: "替你去要一份资金凭证" },
    { key: "verify_voucher", label: "核验付款凭证", hint: "确认对方的凭证真实、已锁定" },
    { key: "submit_receipt", label: "提交执行回执", hint: "交付后写入证据哈希" },
    { key: "update_progress", label: "更新任务进度", hint: "写进度节点" },
    { key: "request_settlement", label: "申请结算", hint: "验证通过后请求划转" },
    { key: "sync_task_status", label: "同步任务状态", hint: "读本身份相关的任务" },
  ];
  var DEFAULT_PERMS = [
    "request_voucher",
    "submit_receipt",
    "update_progress",
    "request_settlement",
    "sync_task_status",
  ];
  var RUNTIME_URL = "https://karma-network.ai";

  var state = { profiles: [], ceiling: 0, allocations: [], typeTouched: false, busy: false };

  function api() { return global.cyberKarmaApi; }
  function byId(id) { return document.getElementById(id); }
  function identity() { return String(global.KARMA_IDENTITY_ID || "").trim(); }
  function esc(v) {
    return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function money(n) {
    var v = Number(n);
    return isFinite(v) ? v.toFixed(2) : "0.00";
  }
  function setStatus(node, msg, isErr) {
    if (!node) return;
    node.textContent = msg || "";
    node.classList.toggle("err", !!isErr);
  }
  function profilePos(profileId) {
    for (var i = 0; i < state.profiles.length; i += 1) {
      if (state.profiles[i] && state.profiles[i].profile_id === profileId) return i + 1;
    }
    return 0;
  }
  function displayIdOf(realId, pos) {
    try {
      if (global.KarmaDisplayId && global.KarmaDisplayId.of) return global.KarmaDisplayId.of(realId, pos);
    } catch (_) {}
    return String(realId || "");
  }
  function typeOf(profile) {
    var t = profile && CLASS_TO_TYPE[profile["class"]];
    return TYPES[t] ? t : "work";
  }
  function selectedProfile() {
    var sel = byId("agw-identity");
    var pid = sel ? sel.value : "";
    for (var i = 0; i < state.profiles.length; i += 1) {
      if (state.profiles[i] && state.profiles[i].profile_id === pid) return state.profiles[i];
    }
    return null;
  }
  function allocOf(profileId) {
    for (var i = 0; i < state.allocations.length; i += 1) {
      if (state.allocations[i] && state.allocations[i].profile_id === profileId) return state.allocations[i];
    }
    return null;
  }
  function allocatedOf(a) { return a ? Number(a.allocated_credits || 0) : 0; }
  function inUseOf(a) {
    if (!a) return 0;
    return (
      Number(a.in_progress_credits || 0) +
      Number(a.pending_settlement_credits || 0) +
      Number(a.disputed_credits || 0)
    );
  }
  function otherAllocated(profileId) {
    var total = 0;
    state.allocations.forEach(function (a) {
      if (a && a.profile_id !== profileId) total += allocatedOf(a);
    });
    return total;
  }
  function checkedPerms() {
    return Array.prototype.slice
      .call(document.querySelectorAll("[data-agw-perm]"))
      .filter(function (n) { return n.checked; })
      .map(function (n) { return n.getAttribute("data-agw-perm"); });
  }
  function selectedType() {
    var n = document.querySelector('input[name="agw-type"]:checked');
    return n ? n.value : "";
  }

  function copyText(text, btn) {
    var done = function () {
      if (!btn) return;
      var old = btn.textContent;
      btn.textContent = "已复制";
      setTimeout(function () { btn.textContent = old; }, 1500);
    };
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, function () {});
        return;
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
      done();
    } catch (_) {}
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
    } catch (_) {}
  }

  /* ---- 签名串必须与服务端 services/runtime_wallet.py 重建的一模一样 ---- */

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

  /* ---------------------------------------------------------------- 渲染 */

  function renderPerms() {
    var host = byId("agw-perms");
    if (!host || host.getAttribute("data-ready") === "1") return;
    host.innerHTML = PERMS.map(function (p) {
      var on = DEFAULT_PERMS.indexOf(p.key) !== -1;
      return (
        '<label class="agw-perm"><input type="checkbox" data-agw-perm="' + esc(p.key) + '"' +
        (on ? " checked" : "") + " /><b>" + esc(p.label) + "</b><span>" + esc(p.hint) + "</span></label>"
      );
    }).join("");
    host.setAttribute("data-ready", "1");
  }

  function renderIdentities() {
    var sel = byId("agw-identity");
    if (!sel) return;
    var keep = sel.value;
    if (!identity()) {
      sel.innerHTML = '<option value="">（先在顶部连接钱包）</option>';
      return;
    }
    if (!state.profiles.length) {
      sel.innerHTML = '<option value="">（还没有子身份，展开下面「新建一个子身份」）</option>';
      return;
    }
    sel.innerHTML = state.profiles
      .map(function (p) {
        var did = displayIdOf(p.profile_id, profilePos(p.profile_id));
        var label = did + " · " + (p.display_name || p.profile_id) + (p.visibility === "private" ? " 🔒" : "");
        return '<option value="' + esc(p.profile_id) + '">' + esc(label) + "</option>";
      })
      .join("");
    var stillThere = state.profiles.some(function (p) { return p.profile_id === keep; });
    if (stillThere) sel.value = keep;
  }

  function renderTypeRadios() {
    if (state.typeTouched && selectedType()) return;
    var want = typeOf(selectedProfile());
    var node = document.querySelector('input[name="agw-type"][value="' + want + '"]');
    if (node) node.checked = true;
  }

  function renderAmountNote() {
    var note = byId("agw-amount-note");
    if (!note) return;
    if (!identity()) { note.textContent = "先在顶部连接钱包。"; return; }
    var p = selectedProfile();
    if (!p) { note.textContent = "先在第 1 步选一个子身份。"; return; }
    var a = allocOf(p.profile_id);
    var mine = allocatedOf(a);
    var used = inUseOf(a);
    var others = otherAllocated(p.profile_id);
    var room = Math.max(0, state.ceiling - others);
    note.textContent =
      "总锁仓 " + money(state.ceiling) + " USDC · 其它子身份已占 " + money(others) +
      " · 这个身份最多可授权 " + money(room) +
      (mine > 0 ? "（当前 " + money(mine) + "，其中 " + money(used) + " 正在使用）" : "");
  }

  function renderWizard() {
    renderPerms();
    renderIdentities();
    renderTypeRadios();
    renderAmountNote();
    var note = byId("agw-identity-note");
    if (note) {
      var p = selectedProfile();
      if (!p) {
        note.textContent = "";
      } else {
        var did = displayIdOf(p.profile_id, profilePos(p.profile_id));
        note.textContent =
          "身份 " + did + " · " + (p.display_name || p.profile_id) +
          (p.visibility === "private" ? " · 🔒 明细保密" : "");
      }
    }
    var btn = byId("agw-generate");
    if (btn) btn.disabled = state.busy || !identity();
  }

  /* ---------------------------------------------------------------- 数据 */

  async function load() {
    var status = byId("agw-status");
    renderPerms();
    if (!identity() || !api()) {
      state.profiles = [];
      state.allocations = [];
      state.ceiling = 0;
      renderWizard();
      setStatus(status, "未连接钱包");
      return;
    }
    setStatus(status, "读取身份与额度…");
    try {
      var profilesBody = await api().listRoleProfiles(identity());
      state.profiles = (profilesBody && profilesBody.profiles) || [];
      try { sessionStorage.setItem("karma_console_profiles", JSON.stringify(state.profiles)); } catch (_) {}
    } catch (e) {
      setStatus(status, "身份读取失败：" + (e.message || e), true);
    }
    try {
      var allocBody = await api().getAllocations(identity());
      state.allocations = (allocBody && allocBody.allocations) || [];
      state.ceiling = Number((allocBody && allocBody.locked_usdc) || 0);
    } catch (_) {
      try {
        var cap = await api().getCapacity(identity());
        state.ceiling = Number((cap && cap.total_locked_usdc) || 0);
      } catch (_) {}
    }
    renderWizard();
    setStatus(
      status,
      state.profiles.length ? "已读取 " + state.profiles.length + " 个子身份" : "还没有子身份，先新建一个"
    );
  }

  /** 新建/授权会改变别的卡（切换器、身份页额度表）要读的数据，喊它们重读。 */
  async function refreshOthers() {
    try {
      if (global.KarmaIdentitySwitcher && global.KarmaIdentitySwitcher.refresh) {
        await global.KarmaIdentitySwitcher.refresh();
      }
    } catch (_) {}
    try { document.dispatchEvent(new CustomEvent("karma-alloc-changed")); } catch (_) {}
  }

  async function createProfile() {
    var status = byId("agw-new-status");
    if (!identity()) { setStatus(status, "先在顶部连接钱包", true); return; }
    var nameEl = byId("agw-new-name");
    var name = (nameEl && nameEl.value ? nameEl.value : "").trim();
    var type = byId("agw-new-type") ? byId("agw-new-type").value : "life";
    var t = TYPES[type] || TYPES.life;
    setStatus(status, "创建中…");
    try {
      var created = await api().createRoleProfile({
        owner_identity_id: identity(),
        "class": t.klass,
        display_name: name || t.label,
      });
      if (nameEl) nameEl.value = "";
      setStatus(status, "已创建");
      await load();
      var sel = byId("agw-identity");
      if (sel && created && created.profile_id) sel.value = created.profile_id;
      renderWizard();
      await refreshOthers();
    } catch (e) {
      setStatus(status, "创建失败：" + (e.message || e), true);
    }
  }

  function renderSdk(res, profile, fields, perms, amount) {
    var host = byId("agw-result");
    if (!host) return;
    var key = (res && res.runtime_key) || "";
    var did = displayIdOf(profile.profile_id, profilePos(profile.profile_id));
    var human = byId("agw-human") ? byId("agw-human").value : "above_single";
    var apiBase = String(global.KARMA_API_BASE || "") || RUNTIME_URL;
    var env = [
      "KARMA_API_BASE=" + apiBase,
      "KARMA_IDENTITY_ID=" + identity(),
      "KARMA_PROFILE_ID=" + profile.profile_id,
      "KARMA_RUNTIME_URL=" + RUNTIME_URL,
      "KARMA_RUNTIME_KEY=" + key,
    ].join("\n");
    host.hidden = false;
    host.innerHTML =
      '<div class="ag-result-head"><b>Karma 授权 SDK · ' + esc(did) + "</b>" +
      '<span class="tag ok">已生成</span>' +
      '<span class="tag">' + esc(TYPES[typeOf(profile)].label) + "</span></div>" +
      '<p class="ag-hint">把这段原样写进 agent 的环境变量。它读到身份和边界后就能开始跑；每一步收付都要过 Karma 的验证才会真正划转。</p>' +
      '<div class="ag-snippet"><div class="ag-secret-label">① 运行时凭据（明文只显示这一次，请立即保存）</div>' +
      "<pre>" + esc(env) + "</pre>" +
      '<div style="display:flex;gap:8px;flex-wrap:wrap">' +
      '<button type="button" class="btn primary" id="agw-copy-env">复制 SDK</button>' +
      '<button type="button" class="btn" id="agw-download-env">下载 karma-agent.env</button>' +
      "</div></div>" +
      '<div class="ag-snippet"><div class="ag-secret-label">② agent 读到的边界</div><pre>' +
      esc(
        "身份        " + did + "（" + profile.profile_id + "）\n" +
        "类型        " + TYPES[typeOf(profile)].label + "\n" +
        "授权额度    " + money(amount) + " USDC\n" +
        "单笔最高    " + money(fields.single_limit) + " USDC\n" +
        "每日上限    " + money(fields.daily_limit) + " USDC\n" +
        "人工确认    " + (HUMAN_LABELS[human] || human) + "\n" +
        "权限        " + perms.slice().sort().join(", ") + "\n" +
        "有效期至    " + String(fields.expire_time).slice(0, 10)
      ) + "</pre></div>" +
      '<div class="ag-next"><b>③ 让 agent 先跑这一条自检</b><pre>' +
      esc("curl -s " + RUNTIME_URL + "/runtime/permissions \\\n  -H \"X-Karma-Runtime-Key: $KARMA_RUNTIME_KEY\"") +
      "</pre></div>";
    var copy = byId("agw-copy-env");
    if (copy) copy.addEventListener("click", function () { copyText(env, copy); });
    var dl = byId("agw-download-env");
    if (dl) dl.addEventListener("click", function () { download("karma-agent.env", env + "\n"); });
  }

  async function generate() {
    var status = byId("agw-gen-status");
    var id = identity();
    if (!id) { setStatus(status, "请先在顶部「连接钱包」完成认证", true); return; }
    var p = selectedProfile();
    if (!p) { setStatus(status, "第 1 步：先选一个子身份（没有就新建一个）", true); return; }
    var amount = Number(byId("agw-amount").value);
    if (!isFinite(amount) || amount <= 0) { setStatus(status, "第 2 步：请填授权额度（大于 0）", true); return; }
    var single = Number(byId("agw-single").value);
    var daily = Number(byId("agw-daily").value);
    if (!(single > 0)) { setStatus(status, "第 4 步：单笔最高要大于 0", true); return; }
    if (!(daily > 0) || daily + 1e-9 < single) {
      setStatus(status, "第 4 步：每天累计上限不能小于单笔最高", true);
      return;
    }
    var perms = checkedPerms();
    if (!perms.length) { setStatus(status, "第 4 步：至少勾一项权限", true); return; }
    if (!byId("agw-ack").checked) { setStatus(status, "第 4 步：请先勾选责任确认", true); return; }
    var type = selectedType() || typeOf(p);
    var human = byId("agw-human").value;

    var others = otherAllocated(p.profile_id);
    if (others + amount > state.ceiling + 1e-9) {
      setStatus(
        status,
        "额度超了：其它子身份已占 " + money(others) + "，总锁仓 " + money(state.ceiling) +
          "，这个身份最多 " + money(Math.max(0, state.ceiling - others)),
        true
      );
      return;
    }
    var used = inUseOf(allocOf(p.profile_id));
    if (amount + 1e-9 < used) {
      setStatus(status, "这个身份已有 " + money(used) + " 在执行 / 待结算，额度不能降到它以下", true);
      return;
    }
    var provider =
      global.KarmaWalletAuth && global.KarmaWalletAuth.activeProvider && global.KarmaWalletAuth.activeProvider();
    if (!provider || typeof provider.request !== "function") {
      setStatus(status, "没检测到钱包插件，请用顶部「连接钱包」重新连一次", true);
      return;
    }

    state.busy = true;
    renderWizard();
    var out = byId("agw-result");
    if (out) { out.hidden = true; out.innerHTML = ""; }
    try {
      if (state.typeTouched) {
        setStatus(status, "① 写入子身份类型…");
        var t = TYPES[type] || TYPES.life;
        var h = Object.assign({}, api().headers(), { "Content-Type": "application/json" });
        await api().karmaFetch("/v1/identity/role-profiles/" + encodeURIComponent(p.profile_id), {
          method: "PUT",
          headers: h,
          body: JSON.stringify({ "class": t.klass, display_name: t.label }),
        });
      }

      setStatus(status, "② 保存权限与边界…");
      await api().putAutomationPolicy(id, {
        auto_enabled: true,
        responsibility_acknowledged: true,
        single_limit: single,
        daily_limit: daily,
        permissions: perms,
        high_risk_mode: human,
      });

      setStatus(status, "③ 划拨子身份额度…");
      var next = {};
      state.allocations.forEach(function (row) {
        if (row && row.profile_id) next[row.profile_id] = Number(row.allocated_credits || 0);
      });
      next[p.profile_id] = amount;
      await api().setAllocations(id, next);

      setStatus(status, "④ 请在钱包里签名（签一次，生成凭据）…");
      var accounts = await provider.request({ method: "eth_requestAccounts" });
      var wallet = accounts && accounts[0];
      if (!wallet) throw new Error("钱包没有返回地址");
      var fields = {
        karma_identity_id: id,
        wallet_address: wallet,
        permissions: perms.slice(),
        single_limit: single,
        daily_limit: daily,
        expire_time: pyUtcIso(Date.now() + 7 * 86400e3),
        agent_name: p.display_name || TYPES[type].label,
        agent_binding: "",
      };
      var sig = await provider.request({ method: "personal_sign", params: [buildCreateKeyMsg(fields), wallet] });
      var res = await global.karmaRuntimeApi.runtimeCreateKey({
        wallet_address: wallet,
        karma_identity_id: id,
        wallet_signature: sig,
        permissions: perms,
        single_limit: single,
        daily_limit: daily,
        expire_time: fields.expire_time,
        agent_name: fields.agent_name,
        profile_id: p.profile_id,
      });
      renderSdk(res, p, fields, perms, amount);
      setStatus(status, "✅ 已生成，交付包在下面");
      await load();
      refreshOthers();
    } catch (e) {
      var msg = e && e.message ? e.message : String(e);
      setStatus(status, "生成失败：" + msg, true);
      if (out) {
        out.hidden = false;
        out.innerHTML = '<p class="err">生成失败：' + esc(msg) + "</p>";
      }
    } finally {
      state.busy = false;
      renderWizard();
    }
  }

  function init() {
    if (!byId("ag-wizard")) return;
    renderPerms();
    renderWizard();
    load();

    var sel = byId("agw-identity");
    if (sel) {
      sel.addEventListener("change", function () {
        state.typeTouched = false;
        renderWizard();
      });
    }
    var createBtn = byId("agw-new");
    if (createBtn) createBtn.addEventListener("click", createProfile);
    var go = byId("agw-generate");
    if (go) go.addEventListener("click", generate);

    Array.prototype.slice.call(document.querySelectorAll("[data-agw-preset]")).forEach(function (chip) {
      chip.addEventListener("click", function () {
        var input = byId("agw-amount");
        if (!input) return;
        var v = chip.getAttribute("data-agw-preset");
        if (v === "all") {
          var p = selectedProfile();
          var room = p ? Math.max(0, state.ceiling - otherAllocated(p.profile_id)) : 0;
          input.value = room > 0 ? String(Math.round(room * 100) / 100) : "";
        } else {
          input.value = v;
        }
        renderAmountNote();
      });
    });

    document.addEventListener("change", function (ev) {
      var t = ev.target;
      if (t && t.name === "agw-type") {
        state.typeTouched = true;
      }
    });

    ["karma-wallet-connected", "karma-session-restored"].forEach(function (name) {
      document.addEventListener(name, function () {
        state.typeTouched = false;
        load();
      });
    });
    document.addEventListener("karma-capacity-changed", function () { load(); });
    document.addEventListener("karma-page-shown", function (ev) {
      if (ev && ev.detail && ev.detail.page === "agents") load();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  global.KarmaAuthorize = { reload: load, state: state };
})(window);