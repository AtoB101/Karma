/**
 * Karma Cyber Console — Agent 接入（身份卡 → 基础设施）
 *
 * 主链路：认证一次拿到身份卡 → 锁定资金 → 给角色档案授权额度 → agent 接入 →
 * Karma 负责该 agent 的收付验证与结算。
 *
 * 安全边界：
 *  - 全程不接触用户钱包私钥 / 助记词（只用到 SIWE 签发的会话 token）
 *  - agent 的运行密钥由服务端生成并托管（0600、可吊销），浏览器只拿到公开信息
 *  - bootstrap API Key 仅此一次明文返回，页面做一次性展示 + 复制
 */
(function () {
  function api() {
    return window.cyberKarmaApi;
  }
  function $(sel, root) {
    return (root || document).querySelector(sel);
  }
  function $$(sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  }
  function identity() {
    return (window.KARMA_IDENTITY_ID || "").trim();
  }
  /**
   * 行业目录标题、行业硬指标（service_specs）表单都收在 karma-service-spec.js 里：
   * 「接入一个 Agent」和「配对码接入」必须渲染同一份表单，各写一套迟早会漂。
   */
  function spec() {
    return window.KarmaServiceSpec;
  }

  function indTitle(row, fallback) {
    var s = spec();
    if (s) return s.industryTitle(row, fallback);
    return (row && (row.title_zh || row.title_en)) || fallback;
  }

  function esc(v) {
    return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function usd(v) {
    var n = Number(v);
    return isFinite(n) ? n.toFixed(2) : "";
  }

  // ---------- 我的 Agent ----------

  /** Human-readable names for the P1 readiness gate keys. */
  var GAP_LABELS = {
    directory_active: "目录未激活",
    identity_class_set: "身份类别未设置",
    owner_identity_bound: "未绑定主人身份",
    owner_identity_active: "主人身份未激活",
    public_key_bound: "未绑定公钥",
    public_key_not_platform_default: "使用的是平台默认公钥",
    profile_card_present: "缺少能力档案",
    service_specs_valid: "履约硬指标不合规",
    boundary_complete: "责任边界不完整",
    responsibility_acknowledged: "未签认责任",
    responsibility_attestation_valid: "责任签认无效",
    boundary_hash_consistent: "边界哈希不一致",
    ack_bound_to_live_boundary: "签认未绑定当前边界",
    reputation_initialized: "声誉台账未初始化",
    ownership_consistent: "归属不一致",
  };

  function gapText(gaps) {
    return (gaps || [])
      .map(function (g) {
        return GAP_LABELS[g] || g;
      })
      .join("、");
  }

  function renderAgentRow(a, allocatedAmount) {
    // The ledger agent SIWE creates for the card itself is not an onboarded
    // agent: it has no profile card / boundary, so P1 badges would be pure
    // noise. Present it for what it is.
    var isSelfAgent = a.agent_id === a.owner_identity_id;
    var ready = a.p1_ready === true;
    var gaps = gapText(a.p1_gaps);

    // The card's own agent carries the internal ledger class ("user") and has no
    // runtime key of its own, so neither the class tag nor a custody tag applies.
    var tags = isSelfAgent
      ? '<span class="tag">身份代理 · 自动创建</span>'
      : '<span class="tag">' + esc(a.identity_class || "—") + "</span>";
    if (!isSelfAgent) {
      if (allocatedAmount > 0) {
        tags += '<span class="tag ok">已授权 ' + esc(usd(allocatedAmount)) + " USDC</span>";
      } else if (ready && a.scope_profile_id) {
        tags += '<span class="tag ok">已授权</span>';
      }
      tags += ready
        ? '<span class="tag ok">P1 就绪</span>'
        : '<span class="tag warn">P1 未就绪</span>';
      tags +=
        a.key_custody === "server_side_revocable"
          ? '<span class="tag">密钥托管·可吊销</span>'
          : '<span class="tag muted">外部密钥</span>';
    }

    var sub = isSelfAgent
      ? "这是你身份卡自带的付款代理账本 — 连接商家 agent 时自动使用，无需配置。"
      : "角色 " + esc(a.role || "—") +
        " · 接入路径 " + esc(a.connect_path || "—") +
        " · 档案 " + esc(a.scope_profile_id || "未绑定") +
        (allocatedAmount > 0 ? " · 已授权 " + esc(usd(allocatedAmount)) + " USDC" : "");
    if (!isSelfAgent && !ready && gaps) {
      sub += ' · <span class="err">待补齐：' + esc(gaps) + "</span>";
    }

    // Only onboarded agents get inline controls; the self agent is not configurable.
    var actions = isSelfAgent
      ? ""
      : '<div class="agent-row-actions">' +
        '<button type="button" class="btn primary" data-agent-handoff="' + esc(a.agent_id) + '">⚡ 生成接入包 · 交给 agent</button>' +
        '<input type="number" min="0" step="0.01" placeholder="授权额度 USDC" data-alloc-live="' +
        esc(a.scope_profile_id || "") + '" data-agent="' + esc(a.agent_id) + '" />' +
        '<button type="button" class="btn" data-agent-alloc="' + esc(a.agent_id) + '">授权额度</button>' +
        '<button type="button" class="btn red" data-agent-revoke="' + esc(a.agent_id) + '">停用并销毁密钥</button>' +
        "</div>";

    return (
      '<div class="agent-row' + (isSelfAgent ? " self" : "") + '"' +
      (isSelfAgent ? "" : ' data-agent-row="' + esc(a.agent_id) + '"') + ">" +
      '<div class="agent-row-main">' +
      "<b>" + esc(a.name || a.agent_id) + "</b>" +
      "<code>" + esc(a.agent_id) + "</code>" +
      tags +
      "</div>" +
      '<div class="agent-row-sub">' + sub + "</div>" +
      actions +
      "</div>"
    );
  }

  async function refreshAgents() {
    var list = $("#ag-list");
    var status = $("#ag-list-status");
    if (!list) return;
    var id = identity();
    if (!id) {
      list.innerHTML = '<p class="muted">请先在顶部「连接钱包」完成认证，拿到身份卡后这里会列出你的 agent。</p>';
      return;
    }
    list.innerHTML = '<p class="muted">读取中…</p>';
    try {
      var body = await api().listMyAgents();
      var agents = body.agents || [];
      var allocRows = [];
      try {
        var allocBody = await api().getAllocations(id);
        allocRows = (allocBody && allocBody.allocations) || [];
      } catch (_) {}
      var allocById = {};
      allocRows.forEach(function (row) {
        if (row && row.profile_id) allocById[row.profile_id] = Number(row.allocated_credits || 0);
      });
      if (!agents.length) {
        list.innerHTML = '<p class="muted">这张身份卡还没有接入任何 agent。用下面的一键接入，30 秒建一个。</p>';
      } else {
        list.innerHTML = agents
          .map(function (a) {
            return renderAgentRow(a, allocById[a.scope_profile_id] || 0);
          })
          .join("");
      }
      if (status) status.textContent = "共 " + agents.length + " 个";
    } catch (e) {
      list.innerHTML = '<p class="err">读取失败：' + esc(e.message || e) + "</p>";
    }
  }

  async function allocateForAgent(agentId) {
    var input = $('[data-alloc-live][data-agent="' + agentId + '"]');
    var profileId = input && input.getAttribute("data-alloc-live");
    var status = $("#ag-list-status");
    if (!profileId) {
      if (status) {
        status.textContent = "该 agent 未绑定角色档案，无法分配额度";
        status.classList.add("err");
      }
      return;
    }
    var amount = Number(input.value);
    if (!amount || amount <= 0) {
      if (status) status.textContent = "请填写额度金额";
      return;
    }
    if (status) {
      status.textContent = "授权中…";
      status.classList.remove("err");
    }
    try {
      await api().setAllocations(identity(), buildAllocations(profileId, amount));
      if (status) status.textContent = "已授权 " + amount + " USDC → " + profileId;
      refreshAgents();
    } catch (e) {
      if (status) {
        status.textContent = "授权失败：" + (e.message || e);
        status.classList.add("err");
      }
    }
  }

  /** Read every allocation input on the page so a save never silently zeroes the others. */
  function buildAllocations(changedProfileId, amount) {
    var out = {};
    $$("[data-alloc-live]").forEach(function (node) {
      var pid = node.getAttribute("data-alloc-live");
      var v = Number(node.value);
      if (pid && v > 0) out[pid] = v;
    });
    if (changedProfileId) out[changedProfileId] = amount;
    return out;
  }

  async function revokeAgent(agentId) {
    var status = $("#ag-list-status");
    if (!window.confirm("停用 " + agentId + " 并销毁 Karma 托管的运行密钥？此操作不可撤销。")) return;
    if (status) status.textContent = "停用中…";
    try {
      await api().ownerRevokeAgent(agentId);
      if (status) status.textContent = "已停用 " + agentId;
      refreshAgents();
    } catch (e) {
      if (status) status.textContent = "停用失败：" + (e.message || e);
    }
  }

  // ---------- 接入向导 ----------

  var INDUSTRIES = null;
  var CURRENT = null;
  /* 行业那一行归这里（2026-10-13 用户口径）：行业**不再让用户选** ——
     个体助理取营业执照上的经营范围、企业助理取主体认证里的服务类别，
     用服务端同一套关键词匹配（/v1/standards/onboarding/suggest-industries）推出来；
     推不出来才把选择器露出来让人点「改」自己挑，不能把流程卡死。 */
  var VERT = { profileKey: null, inferred: "" };

  async function loadIndustries() {
    var sel = $("#ag-vertical");
    if (!sel) return;
    if (INDUSTRIES) return;
    sel.innerHTML = '<option value="">读取行业目录…</option>';
    try {
      var body = await api().listOnboardingIndustries();
      INDUSTRIES = body.industries || body.items || [];
      var groups = {};
      INDUSTRIES.forEach(function (i) {
        var g = i.group || "other";
        (groups[g] = groups[g] || []).push(i);
      });
      var html = '<option value="">请选择行业</option>';
      Object.keys(groups).forEach(function (g) {
        html += '<optgroup label="' + esc(g) + '">';
        groups[g].forEach(function (i) {
          html += '<option value="' + esc(i.industry_id) + '">' +
            esc(indTitle(i, i.industry_id)) + "</option>";
        });
        html += "</optgroup>";
      });
      sel.innerHTML = html;
      sel.disabled = false;
    } catch (e) {
      sel.innerHTML = '<option value="">行业目录读取失败</option>';
    }
  }

  /** 渲染哪一个行业的硬指标由调用方决定；渲染 / 回填 / 收集都在 karma-service-spec.js。 */
  async function renderSpecForm(industryId) {
    var host = $("#ag-spec-form");
    if (!host || !spec()) return;
    CURRENT = null;
    if (!industryId) {
      host.innerHTML = "";
      return;
    }
    host.innerHTML = '<p class="muted">读取行业必填项…</p>';
    try {
      var body = await api().getOnboardingIndustry(industryId);
      var ind = body.industry || body;
      spec().renderForm(host, ind);
      CURRENT = ind;
    } catch (e) {
      host.innerHTML = '<p class="err">读取失败：' + esc(e.message || e) + "</p>";
    }
  }

  function fillFromExample() {
    var host = $("#ag-spec-form");
    if (spec() && host) spec().fillFromExample(host);
  }

  /** 表单 -> service_specs 契约。problems 非空就别提交，服务端也会拿同一套规则再拒一次。 */
  function collectSpec() {
    var host = $("#ag-spec-form");
    if (spec() && CURRENT && host) return spec().collect(host);
    return { spec: {}, problems: ["请先选择行业"] };
  }
  /** 资质文本：行业就从这张卡上读（营业执照经营范围 / 主营产品 / 服务类别…）。 */
  function profileIndustryText(p) {
    if (!p) return "";
    var bag = (p && p.kyc_payload) || {};
    var parts = [];
    ["business_name", "business_scope", "main_products", "service_scope",
      "service_category", "legal_name", "entity_name"].forEach(function (k) {
      if (bag[k]) parts.push(String(bag[k]));
    });
    return parts.join(" ");
  }

  /** 资质文本 → 行业目录里的 industry_id（服务端同一套规则）。推不出来回空串。 */
  async function inferVertical(p) {
    var text = profileIndustryText(p);
    if (!text) return "";
    try {
      var body = await api().suggestIndustries(text);
      var rows = (body && body.suggestions) || [];
      if (rows.length && rows[0].industry_id) return String(rows[0].industry_id);
    } catch (_) {}
    return "";
  }

  function industryTitleById(id) {
    var rows = INDUSTRIES || [];
    for (var i = 0; i < rows.length; i += 1) {
      if (rows[i] && rows[i].industry_id === id) return indTitle(rows[i], id);
    }
    return String(id || "");
  }

  function selectedCard() {
    var a = window.KarmaAuthorize;
    try { return a && a.selectedProfile ? a.selectedProfile() : null; } catch (_) { return null; }
  }

  function setVerticalNote(text) {
    var note = $("#agw-vertical-note");
    if (note) note.textContent = text;
  }

  function openVerticalPicker(open) {
    var pick = $("#ag-vertical-pick");
    if (pick) pick.hidden = !open;
  }

  /**
   * 方向 / 行业那两行的唯一入口：切到收款才要行业，行业本身从卡上的资质推。
   * 推不出来（卡上没留经营范围，比如生活助理）就把选择器露出来，说明白为什么。
   */
  async function applySide() {
    var sideSel = $("#ag-side");
    var seller = !!(sideSel && sideSel.value === "seller");
    var row = $("#ag-vertical-row");
    var wrap = $("#ag-spec-wrap");
    if (row) row.hidden = !seller;
    if (wrap) wrap.hidden = !seller;
    if (!seller) { openVerticalPicker(false); return; }
    if (!INDUSTRIES) await loadIndustries();
    var card = selectedCard();
    var key = (card && card.profile_id) || "";
    if (VERT.profileKey !== key) {
      VERT.profileKey = key;
      VERT.inferred = await inferVertical(card);
    }
    var sel = $("#ag-vertical");
    if (sel && !sel.value && VERT.inferred) sel.value = VERT.inferred;
    var current = sel ? sel.value : "";
    if (!current) {
      openVerticalPicker(true);
      setVerticalNote("资质里没有读到行业，点「改」选一个");
      return;
    }
    openVerticalPicker(false);
    setVerticalNote(VERT.inferred === current
      ? industryTitleById(current) + "（来自资质认证）"
      : industryTitleById(current));
    await renderSpecForm(current);
  }

  /**
   * 一条龙第 3 步选完方向 / 行业后，选收款方向时把它注册进 Karma 目录。
   * 复用同一个 agent 名：目录里的 agent_id 与运行时钥匙的 agent_binding 是同一个值，
   * 事后「我的助理 Agent」与「交付包」才能按同一个 id 找到它。凭据由 Karma
   * 服务端托管，浏览器只拿到一次明文。
   */
  async function registerFromWizard(opts) {
    var res = await api().ownerConnect({
      side: opts.side,
      vertical: opts.vertical,
      display_name: opts.agentName,
      owner_identity_id: identity(),
      endpoint_url: opts.endpoint || undefined,
      scope_profile_id: opts.profileId || undefined,
      answers: opts.answers || {},
      agent_id: opts.agentName,
      mint_api_key: true,
    });
    try {
      var creds = (res && res.credentials) || {};
      var aid = (res && res.agent && res.agent.agent_id) || opts.agentName;
      if (creds.api_key) {
        var bag = window.KarmaAgentKeys || (window.KarmaAgentKeys = {});
        bag[aid] = creds.api_key;
      }
    } catch (_) {}
    // 起步引导数的第 3 步是「真正接入的 agent」，注册成功要让它立刻更新。
    document.dispatchEvent(new CustomEvent("karma-agent-connected", {
      detail: { agent_id: (res && res.agent && res.agent.agent_id) || opts.agentName },
    }));
    refreshAgents();
    return res;
  }


  function init() {
    if (!$("#agents")) return;
    loadIndustries();
    refreshAgents();

    var sideSel = $("#ag-side");
    if (sideSel) sideSel.addEventListener("change", function () { applySide(); });
    applySide();
    var vertSel = $("#ag-vertical");
    if (vertSel) {
      vertSel.addEventListener("change", function () {
        // 用户自己点「改」挑的：不再标「来自资质认证」，硬指标表单跟着换。
        setVerticalNote(industryTitleById(vertSel.value));
        renderSpecForm(vertSel.value);
      });
    }
    var vertEdit = $("#agw-vertical-edit");
    if (vertEdit) vertEdit.addEventListener("click", function () { openVerticalPicker(true); });
    var refresh = $("#ag-list-refresh");
    if (refresh) refresh.addEventListener("click", function () { refreshAgents(); });

    document.addEventListener("karma-wallet-connected", function () {
      refreshAgents();
    });
    document.addEventListener("karma-session-restored", function () {
      refreshAgents();
    });
    // 新建的子身份卡要能在这个下拉里直接选到，不然刚认证完还得刷新整页。
    document.addEventListener("karma-capacity-changed", function () {
      refreshAgents();
    });

    document.addEventListener("click", function (ev) {
      var t = ev.target;
      if (!t || !t.getAttribute || !t.closest) return;
      var row = t.closest("[data-agent-row]");
      if (row && !t.closest("button, input, select, textarea, a, .agent-row-actions")) {
        var rowAgentId = row.getAttribute("data-agent-row");
        if (rowAgentId && window.KarmaHandoff && window.KarmaHandoff.open) {
          window.KarmaHandoff.open(rowAgentId, true);
        }
        return;
      }
      var rev = t.getAttribute("data-agent-revoke");
      if (rev) { revokeAgent(rev); return; }
      var alloc = t.getAttribute("data-agent-alloc");
      if (alloc) { allocateForAgent(alloc); }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  window.KarmaAgents = {
    refresh: refreshAgents,
    registerFromWizard: registerFromWizard,
    collectSpec: collectSpec,
    // 方向 / 行业那一行由这里画（授权向导选完卡会喊一声 applySide）。
    applySide: applySide,
    inferVertical: inferVertical,
  };
})();
