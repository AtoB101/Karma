/**
 * 操作台 · 「给 agent 授权」向导（锁仓之后的一条直线）。
 *
 * 2026-10-13 用户口径：这张身份卡上**已经定好的东西不再让用户重填**。
 * 子身份的类型 / 名字 / 联系方式 / 授权额度 / 单笔 / 日限 / 权限 都在
 * 「身份 · 认证 → 建立子身份」刷脸开通那一步落了库（role profile 的
 * spend_policy + allocation，见 cyber-identity-verify.js 的 createSub）。
 * 所以这一页只剩两件事：
 *
 *   1 选身份   选一张已经建好的子身份卡（边界只读展示）
 *   2 起名字   这台 agent 叫什么（钥匙必须指名 agent）
 *   → 生成 SDK 钱包 EIP-191 签名一次                 POST /runtime/create-key
 *
 * 生成前仍然按顺序落三笔服务端状态（都取自卡上那份，不取自表单）：
 *   ① 保存这张卡的边界   PUT  /v1/identities/{id}/automation-policy
 *   ② 划拨子身份额度     PUT  /v1/capacity/{id}/allocations
 *   ③ 钱包签一次 → 铸钥匙 POST /runtime/create-key
 * 收款方向还多一步：连带把它上架到 Karma 目录（行业由资质推断，见 KarmaAgents）。
 *
 * 安全边界：只用到 SIWE 会话 + 一次个人签名，不接触私钥 / 助记词；
 * 运行时密钥明文只在生成的那一次展示。
 */
(function (global) {
  "use strict";

  /* 三种身份卡的对外叫法 —— 与 cyber-identity.js 的 ROLE_LABELS 同一套
     （生活助理 / 个体助理 / 企业主体）。这里只用来在只读面板上写「类型」那一行，
     不再让用户在这一页选类型：类型在「身份 · 认证」建卡时就定了。 */
  var TYPES = {
    life: { label: "生活助理", klass: "individual" },
    sole: { label: "个体助理", klass: "merchant" },
    entity: { label: "企业主体", klass: "enterprise" },
  };
  var CLASS_TO_TYPE = { individual: "life", merchant: "sole", enterprise: "entity" };
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
    { key: "discover_agents", label: "发现可结算的 agent", hint: "自己去找能办事的人 / 商家" },
    {
      key: "place_order",
      label: "自主下单",
      hint: "在单笔上限内自己发起委托；超了要你确认",
    },
  ];
  var DEFAULT_PERMS = [
    "request_voucher",
    "submit_receipt",
    "update_progress",
    "request_settlement",
    "sync_task_status",
    "discover_agents",
    "place_order",
  ];
  var FALLBACK_RUNTIME_URL = "https://karma-network.ai";

  var state = {
    profiles: [],
    ceiling: 0,
    allocations: [],
    busy: false,
  };

  /**
   * 生成 SDK 时写进 env 的接入地址：跟着操作台里选的那台节点走。
   * 写死成厂商域名的话，用户换节点以后 agent 还在敲厂商的机器 —— 白换。
   */
  function runtimeUrl() {
    try {
      if (global.KarmaNodes && global.KarmaNodes.effectiveBase) {
        var base = String(global.KarmaNodes.effectiveBase() || "").trim().replace(/\/+$/, "");
        if (base) return base;
      }
    } catch (_) {}
    var manual = String(global.KARMA_API_BASE || "").trim().replace(/\/+$/, "");
    return manual || FALLBACK_RUNTIME_URL;
  }

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
    return TYPES[t] ? t : "life";
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
      "expire_time:" + (f.expire_time || "never"),
      "agent_name:" + (f.agent_name || "console-agent"),
      "agent_binding:" + (f.agent_binding || ""),
      // 主人签字时就把「钱钥匙给哪把 agent 公钥」钉进签名里。
      // 绑定那一刻服务端拿 agent 交来的公钥重算指纹，对不上直接拒绝。
      "agent_public_key_fingerprint:" + (f.agent_public_key_fingerprint || ""),
    ].join("\n");
  }

  /* ---------------------------------------------------------------- 渲染 */

  function permLabel(key) {
    for (var i = 0; i < PERMS.length; i += 1) {
      if (PERMS[i].key === key) return PERMS[i].label;
    }
    return key;
  }

  function typeLabelOf(profile) {
    var t = TYPES[typeOf(profile)];
    return t ? t.label : "";
  }

  /* 老卡（建卡时没记过边界）的兜底：用系统默认值顶上，面板上明说是默认值 ——
     不能让用户以为这是他自己定的。要按自己的规矩来，去「身份 · 认证」再建一张卡。 */
  var FALLBACK_SINGLE = 100;
  var FALLBACK_DAILY = 500;

  /**
   * 选中的这张卡在「身份 · 认证 → 建立子身份」那一步就把边界定好了
   * （role profile 的 spend_policy + allocation）。这里只把它读出来 —— 接入 agent 时
   * 不再让用户重填：重填等于同一套边界有两个版本，换一张卡就漂一次；而且服务端只认
   * 这份已存的策略（assert_runtime_key_matches_policy 要求钥匙与它逐条一致）。
   */
  function cardPolicy() {
    var p = selectedProfile();
    if (!p) return null;
    var policy = (p && p.spend_policy) || {};
    var savedPerms = Array.isArray(policy.permissions) ? policy.permissions.slice() : [];
    var savedSingle = Number(policy.single_limit);
    var savedDaily = Number(policy.daily_limit);
    var savedHuman = String(policy.high_risk_mode || "");
    var fromCard = savedPerms.length > 0 || savedSingle > 0 || savedDaily > 0;
    var single = isFinite(savedSingle) && savedSingle > 0 ? savedSingle : FALLBACK_SINGLE;
    var daily = isFinite(savedDaily) && savedDaily > 0 ? savedDaily : Math.max(FALLBACK_DAILY, single);
    return {
      profile: p,
      amount: allocatedOf(allocOf(p.profile_id)),
      single: single,
      daily: daily,
      human: HUMAN_LABELS[savedHuman] ? savedHuman : "above_single",
      perms: savedPerms.length ? savedPerms : DEFAULT_PERMS.slice(),
      fromCard: fromCard,
    };
  }

  function cardRow(label, value) {
    return '<li><b>' + esc(label) + "</b><span>" + esc(value) + "</span></li>";
  }

  /** 只读面板：这张卡已经定好的东西摆出来让用户看一眼，不用重填。 */
  function renderCardPanel() {
    var wrap = byId("agw-card-wrap");
    var host = byId("agw-card-list");
    var warn = byId("agw-policy-warn");
    var pol = cardPolicy();
    if (wrap) wrap.hidden = !pol;
    if (host) {
      if (!pol) {
        host.innerHTML = "";
      } else {
        var p = pol.profile;
        var did = displayIdOf(p.profile_id, profilePos(p.profile_id));
        host.innerHTML = [
          cardRow("接入身份", did + " · " + (p.display_name || p.profile_id)),
          cardRow("类型", typeLabelOf(p)),
          cardRow("授权额度 (USDC)", money(pol.amount)),
          cardRow("单笔最高 (USDC)", money(pol.single)),
          cardRow("每天累计上限 (USDC)", money(pol.daily)),
          cardRow("人工确认", HUMAN_LABELS[pol.human]),
          cardRow("权限", pol.perms.map(permLabel).join("、")),
          cardRow("责任主体", "建卡时已由你确认：这张卡替它做的事、花的钱由这张卡负责"),
        ].join("");
      }
    }
    if (warn) {
      warn.hidden = !pol || pol.fromCard;
      warn.textContent = pol && !pol.fromCard
        ? "这张卡建立时没有单独设过边界，上面这几项先用的是系统默认值：要按自己的规矩来，就在「身份 · 认证」里再建一张卡。"
        : "";
    }
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
      sel.innerHTML = '<option value="">（还没有子身份，先在「身份 · 认证」建一张卡）</option>';
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

  function renderWizard() {
    renderIdentities();
    renderCardPanel();
    var sel = byId("agw-identity");
    var empty = byId("agw-empty-wrap");
    if (empty) empty.hidden = !!(sel && sel.value);
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
    var pol = cardPolicy();
    var btn = byId("agw-generate");
    // 没选卡 / 这张卡还没分到额度：按钮亮着也是白点，直接灰掉（原因写在状态行）。
    if (btn) btn.disabled = state.busy || !identity() || !pol || !(pol.amount > 0);
    // 方向 / 行业那一行归 KarmaAgents（行业目录与硬指标表单都在它那边）。
    if (global.KarmaAgents && global.KarmaAgents.applySide) global.KarmaAgents.applySide();
  }

  /* ---------------------------------------------------------------- 数据 */

  async function load() {
    var status = byId("agw-status");
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

  /** 这张卡要在「身份 · 认证」里建 —— 这里只给一条直达的路，不就地建空白卡。 */
  function gotoIdentity() {
    try {
      if (typeof global.cyberSwitchPage === "function") global.cyberSwitchPage("identity", "life");
    } catch (_) {}
  }

  /**
   * 「agent 读到的边界」那一块：一行一个文本节点，外层 <pre> 标 data-i18n-phrase。
   *
   * PRE 默认不翻（里面常是签名原文那种数据），所以整块塞进一个 <pre> 的结果是：
   * 英语/韩语页面上这一整片留着中文 —— 中文页面对齐，别的语言全错位。
   * 两个条件缺一不可（真机各踩了一次）：
   *   * 标记要打在**被跳过的那层**（<pre>）上 —— 引擎是从文本节点往上走，遇到
   *     SKIP_TAGS 里没有标记的那一层就整棵跳过；打在里面的 <span> 上不算数。
   *   * 每行要各自占一个文本节点 —— 整块一个节点的话，{0} 模板锚定整串，咬不上。
   * 这样每一行按自己的原文查表，{0} 里的值（人名、金额、「人工确认」那句）也跟着翻。
   */
  function boundary(lines) {
    return lines.map(function (line) {
      return "<span>" + esc(line) + "</span>";
    }).join("\n");
  }

  function renderSdk(res, profile, fields, perms, amount, typeKey, displayName, agentId, reg) {
    var host = byId("agw-result");
    if (!host) return;
    var key = (res && res.runtime_key) || "";
    var did = displayIdOf(profile.profile_id, profilePos(profile.profile_id));
    var human = fields.high_risk_mode || "above_single";
    var label = TYPES[typeKey] ? TYPES[typeKey].label : TYPES[typeOf(profile)].label;
    var name = displayName || profile.display_name || label;
    // 交给 agent 的地址跟着操作台选的节点走：用户换了节点，agent 也得跟着换。
    var apiBase = runtimeUrl();
    var env = [
      "KARMA_API_BASE=" + apiBase,
      "KARMA_IDENTITY_ID=" + identity(),
      "KARMA_PROFILE_ID=" + profile.profile_id,
      "KARMA_RUNTIME_URL=" + apiBase,
      "KARMA_RUNTIME_KEY=" + key,
      "KARMA_AGENT_ID=" + agentId,
    ].join("\n");
    var apiKey = (reg && reg.credentials && reg.credentials.api_key) || "";
    host.hidden = false;
    host.innerHTML =
      '<div class="ag-result-head"><b>接入包 · ' + esc(did) + "</b>" +
      '<span class="tag ok">已生成</span>' +
      '<span class="tag">' + esc(name) + " · " + esc(label) + "</span></div>" +
      '<p class="ag-hint">把这段原样写进 agent 的环境变量。它读到身份和边界后就能开始跑；每一步收付都要过 Karma 的验证才会真正划转。</p>' +
      '<p class="ag-hint">这把钥匙在激活之前动不了钱：agent 领取时会申请绑定公钥，把 8 位匹配码给你；你在第 ③ 步「激活 · 输入匹配码」输码 + 钱包签名确认之后它才生效。匹配码 3 分钟内有效，过期就让 agent 重新申请一次，钥匙不用重铸。</p>' +
      '<div class="ag-snippet"><div class="ag-secret-label">① 运行时凭据（明文只显示这一次，请立即保存）</div>' +
      "<pre>" + esc(env) + "</pre>" +
      '<div style="display:flex;gap:8px;flex-wrap:wrap">' +
      '<button type="button" class="btn primary" id="agw-copy-env">复制接入包</button>' +
      '<button type="button" class="btn" id="agw-download-env">下载 karma-agent.env</button>' +
      "</div></div>" +
      (apiKey
        ? '<div class="ag-snippet"><div class="ag-secret-label">API Key（仅此一次明文显示，请立即保存）</div>' +
          "<pre>" + esc(apiKey) + "</pre>" +
          '<button type="button" class="btn" id="agw-copy-apikey">复制</button></div>'
        : "") +
      '<div class="ag-snippet"><div class="ag-secret-label">② agent 读到的边界</div>' +
      '<pre data-i18n-phrase>' +
      boundary([
        "身份        " + did + "（" + profile.profile_id + "）",
        "名字        " + name,
        "agent       " + agentId,
        "类型        " + label,
        "授权额度    " + money(amount) + " USDC",
        "单笔最高    " + money(fields.single_limit) + " USDC",
        "每日上限    " + money(fields.daily_limit) + " USDC",
        "人工确认    " + (HUMAN_LABELS[human] || human),
        "权限        " + perms.slice().sort().join(", "),
        "有效期至    " + (fields.expire_time ? String(fields.expire_time).slice(0, 10) : "长期有效（随时可注销）"),
      ]) + "</pre></div>" +
      '<div class="ag-next"><b>③ 让 agent 先读边界、再干活</b><pre>' +
      esc(
        "curl -s " + apiBase + "/runtime/policy \\\n  -H \"X-Karma-Runtime-Key: $KARMA_RUNTIME_KEY\"\n" +
        "curl -s " + apiBase + "/runtime/capacity \\\n  -H \"X-Karma-Runtime-Key: $KARMA_RUNTIME_KEY\""
      ) +
      "</pre></div>";
    var copy = byId("agw-copy-env");
    if (copy) copy.addEventListener("click", function () { copyText(env, copy); });
    var cak = byId("agw-copy-apikey");
    if (cak) cak.addEventListener("click", function () { copyText(apiKey, cak); });
    var dl = byId("agw-download-env");
    if (dl) dl.addEventListener("click", function () { download("karma-agent.env", env + "\n"); });
  }

  async function generate() {
    var status = byId("agw-gen-status");
    var id = identity();
    if (!id) { setStatus(status, "请先在顶部「连接钱包」完成认证", true); return; }
    var p = selectedProfile();
    if (!p) { setStatus(status, "第 1 步：先选一张已经建好的子身份", true); return; }
    // 边界只从这张卡上读 —— 表单已撤，服务端也只认卡上那份已存策略。
    var pol = cardPolicy();
    var amount = pol.amount;
    if (!(amount > 0)) {
      setStatus(status, "这张卡还没分到额度：在「身份 · 认证」建卡时给它分配额度，再来接入 agent", true);
      return;
    }
    var single = pol.single;
    var daily = pol.daily;
    var human = pol.human;
    var perms = pol.perms.slice();
    // 卡上一条权限都没有（老卡）：宁可停下来让人去补一张卡，也不拿默认值替用户签字。
    if (!perms.length) { setStatus(status, "这张卡没有可用权限：在「身份 · 认证」里重建一张卡", true); return; }
    // 钥匙必须指名一台 agent：不指名就铸不出来（服务端生产口径硬拦）。
    // 这一步也是「偷到钥匙也花不了钱」的根：码发给这台 agent、也发给你屏幕。
    var agentName = String((byId("agw-agent") || {}).value || "").trim();
    if (!agentName) {
      setStatus(status, "第 2 步：给你的 agent 起个名字（如 claw-001）—— 钥匙要指名一台 agent 才铸得出来", true);
      return;
    }
    if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(agentName)) {
      setStatus(status, "第 2 步：agent 名字只能用字母、数字、点、下划线、连字符（如 claw-001）", true);
      return;
    }
    // 一条龙第 3 步：方向 / 行业。选了收款方向就得有行业 —— 不然目录里无从定义它是干什么的。
    // 行业不再让用户选：个体 / 企业助理在建卡（资质认证）时就已经定了，这里从档案里推断。
    var sideEl = byId("ag-side");
    var side = sideEl ? sideEl.value : "buyer";
    var verticalEl = byId("ag-vertical");
    var vertical = verticalEl ? verticalEl.value : "";
    var endpointEl = byId("ag-endpoint");
    var endpoint = endpointEl ? String(endpointEl.value || "").trim() : "";
    var needRegister = side === "seller";
    if (needRegister && !vertical) {
      setStatus(status, "第 3 步：收款方向要先有一个行业 —— 资质里没读到就点上面的「改」自己选一个", true);
      return;
    }
    var type = typeOf(p);
    var effectiveName = p.display_name || typeLabelOf(p);

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

    // 硬指标必须在 renderWizard() 之前收：renderWizard → applySide →
    // renderSpecForm 会顺手把 CURRENT 清空（它自己等一会儿才回填），
    // 收晚了这一格永远是空的。
    var collected = { spec: {}, problems: [] };
    if (needRegister && side === "seller") {
      collected = global.KarmaAgents && global.KarmaAgents.collectSpec
        ? global.KarmaAgents.collectSpec()
        : { spec: {}, problems: ["请先选择行业"] };
      if (collected.problems.length) {
        setStatus(status, "还差 " + collected.problems.length + " 项：" + collected.problems.slice(0, 4).join("；"), true);
        return;
      }
    }

    state.busy = true;
    renderWizard();
    var out = byId("agw-result");
    if (out) { out.hidden = true; out.innerHTML = ""; }
    var reg = null;
    try {
      if (needRegister) {
        setStatus(status, "接入中…");
        var answers = { industry_ids: [vertical] };
        if (side === "seller") { answers.service_specs = {}; answers.service_specs[vertical] = collected.spec; }
        try {
          reg = await global.KarmaAgents.registerFromWizard({
            profileId: p.profile_id, agentName: agentName, endpoint: endpoint,
            side: side, vertical: vertical, answers: answers,
          });
        } catch (e) {
          setStatus(status, "接入失败：" + (e.message || e), true);
          return;
        }
      }

      setStatus(status, "① 保存这张卡的边界…");
      await api().putAutomationPolicy(id, {
        auto_enabled: true,
        responsibility_acknowledged: true,
        single_limit: single,
        daily_limit: daily,
        permissions: perms,
        high_risk_mode: human,
      });

      setStatus(status, "② 划拨子身份额度…");
      var next = {};
      state.allocations.forEach(function (row) {
        if (row && row.profile_id) next[row.profile_id] = Number(row.allocated_credits || 0);
      });
      next[p.profile_id] = amount;
      await api().setAllocations(id, next);

      setStatus(status, "③ 请在钱包里签名（签一次，生成凭据）…");
      var accounts = await provider.request({ method: "eth_requestAccounts" });
      var wallet = accounts && accounts[0];
      if (!wallet) throw new Error("钱包没有返回地址");
      var fields = {
        karma_identity_id: id,
        wallet_address: wallet,
        permissions: perms.slice(),
        single_limit: single,
        daily_limit: daily,
        // 人工确认模式：签进签名串，交付卡里那句「人工确认」印的就是它。
        high_risk_mode: human,
        // 不填 = 长期有效：钥匙的收口是操作台的注销按钮，不是日历。
        expire_time: "",
        agent_name: agentName,
        agent_binding: agentName,
      };
      var sig = await provider.request({ method: "personal_sign", params: [buildCreateKeyMsg(fields), wallet] });
      var res = await global.karmaRuntimeApi.runtimeCreateKey({
        wallet_address: wallet,
        karma_identity_id: id,
        wallet_signature: sig,
        permissions: perms,
        single_limit: single,
        daily_limit: daily,
        expire_time: fields.expire_time || undefined,
        agent_name: fields.agent_name,
        agent_binding: fields.agent_binding,
        agent_id: fields.agent_binding,
        profile_id: p.profile_id,
      });
      renderSdk(res, p, fields, perms, amount, type, effectiveName, agentName, reg);
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
    renderWizard();
    load();

    var sel = byId("agw-identity");
    if (sel) sel.addEventListener("change", function () { renderWizard(); });
    var goto = byId("agw-goto-identity");
    if (goto) goto.addEventListener("click", gotoIdentity);
    var go = byId("agw-generate");
    if (go) go.addEventListener("click", generate);

    ["karma-wallet-connected", "karma-session-restored"].forEach(function (name) {
      document.addEventListener(name, load);
    });
    document.addEventListener("karma-capacity-changed", load);
    document.addEventListener("karma-page-shown", function (ev) {
      if (ev && ev.detail && ev.detail.page === "agents") load();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  global.KarmaAuthorize = {
    reload: load,
    state: state,
    // KarmaAgents 的行业推断 / 硬指标表单要知道现在选的是哪张卡。
    selectedProfile: selectedProfile,
    // 这张卡上已经定好的边界（只读）：面板与单测都读它，别再各算一份。
    cardPolicy: cardPolicy,
    // The pairing panel signs with the exact same payload this wizard does, so
    // the signature builder has to be shared rather than re-implemented.
    buildCreateKeyMsg: buildCreateKeyMsg,
    pyUtcIso: pyUtcIso,
    PERMS: PERMS,
    DEFAULT_PERMS: DEFAULT_PERMS,
    // SDK env 里那个接入地址：给测试复用，别各写一份。
    runtimeUrl: runtimeUrl,
  };
})(window);
