/**
 * Karma Cyber Console — 一卡多身份（P1/P2/P3）整合。
 *
 * 以 pages/cyber/index.html 为唯一基准：
 *  - 侧边栏 identity-box 注入「身份档案切换器」
 *  - 「身份」页注入「身份档案管理」（创建档案 / 授权披露 / 提交 KYC / 查看身份卡）
 *  - 选中 private（企业）档案时加「涉密」徽标 + 金额模糊
 *
 * 复用 karma-public-api.js（listRoleProfiles / createRoleProfile / grantDisclosure /
 * submitKyc / getIdentityCard / activeProfileId）与 console-wallet-auth 的
 * karma-wallet-connected 事件。
 */
(function () {
  var SS_PROFILE = "karma_console_active_profile";
  var SS_PROFILES = "karma_console_profiles";
  var BADGE_ID = "karma-confidential-badge";

  function api() {
    return window.cyberKarmaApi;
  }
  function $(sel, root) {
    return (root || document).querySelector(sel);
  }

  /** Card fields are server-controlled strings; escape them before interpolating. */
  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function activeProfileId() {
    try { return sessionStorage.getItem(SS_PROFILE) || ""; } catch (_) { return ""; }
  }
  function setActiveProfileId(id) {
    try { id ? sessionStorage.setItem(SS_PROFILE, id) : sessionStorage.removeItem(SS_PROFILE); } catch (_) {}
  }
  function getProfiles() {
    try {
      var raw = sessionStorage.getItem(SS_PROFILES);
      var arr = raw ? JSON.parse(raw) : [];
      return Array.isArray(arr) ? arr : [];
    } catch (_) { return []; }
  }
  function profileLabel(p) {
    if (!p) return "";
    return (p.display_name || p.profile_id) + " · " + (p["class"] || "") + (p.visibility === "private" ? " 🔒" : "");
  }
  /** i18n with an inline fallback, so a stale cached pack never shows a raw key. */
  function tr(key, fallback) {
    try {
      var i18n = window.CYBER_I18N;
      if (i18n && i18n.t) {
        var v = i18n.t(key);
        if (v && v !== key) return v;
      }
    } catch (_) {}
    return fallback;
  }
  function shortId(id) {
    var s = String(id || "");
    return s.length > 18 ? s.slice(0, 10) + "…" + s.slice(-6) : s;
  }
  function getActiveProfile() {
    var id = activeProfileId();
    if (!id) return null;
    try {
      var raw = sessionStorage.getItem(SS_PROFILES);
      if (raw) {
        var arr = JSON.parse(raw);
        for (var i = 0; i < arr.length; i++) if (arr[i] && arr[i].profile_id === id) return arr[i];
      }
    } catch (_) {}
    return null;
  }

  // ---- 顶部「主体 / 视角」状态栏 + 切换面板 ----
  /* The topbar states on every page which master card owns the records and which
     sub-identity the console is filtering by. Without it a filtered list is
     indistinguishable from an empty account, and a user cannot tell whether a
     write acted as the master or as a sub-identity. */
  function renderScopeBar() {
    var masterEl = document.getElementById("sub-scope-master");
    var activeEl = document.getElementById("sub-scope-active");
    var master = String((window.KARMA_IDENTITY_ID || "")).trim();
    if (masterEl) {
      masterEl.textContent = master ? shortId(master) : tr("scope.none", "未连接");
      masterEl.title = master;
    }
    var pid = activeProfileId();
    var p = getActiveProfile();
    if (activeEl) {
      activeEl.textContent = pid ? (p ? profileLabel(p) : shortId(pid)) : tr("scope.master_all", "主体（全部）");
      activeEl.title = pid;
    }
    document.body.classList.toggle("sub-scope-filtered", !!pid);
  }

  function renderSubPanel() {
    var panel = document.getElementById("sub-switch-panel");
    if (!panel) return;
    var profiles = getProfiles();
    var pid = activeProfileId();
    panel.innerHTML = "";
    var rows = [{ id: "", label: tr("scope.master_all", "主体（全部）") }];
    profiles.forEach(function (p) { rows.push({ id: p.profile_id, label: profileLabel(p) }); });
    rows.forEach(function (r) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "sub-switch-item" + (r.id === pid ? " active" : "");
      b.setAttribute("role", "menuitem");
      b.setAttribute("data-profile-option", r.id);
      b.textContent = r.label;
      b.addEventListener("click", function () { setActiveProfile(r.id); closeSubPanel(); });
      panel.appendChild(b);
    });
    if (!profiles.length) {
      var empty = document.createElement("p");
      empty.className = "sub-switch-empty";
      empty.textContent = tr("scope.empty", "还没有子身份档案，可在「身份」页创建。");
      panel.appendChild(empty);
    }
  }

  function closeSubPanel() {
    var panel = document.getElementById("sub-switch-panel");
    var btn = document.getElementById("btn-switch-sub");
    if (panel) panel.hidden = true;
    if (btn) btn.setAttribute("aria-expanded", "false");
  }
  function openSubPanel() {
    var panel = document.getElementById("sub-switch-panel");
    var btn = document.getElementById("btn-switch-sub");
    if (!panel) return;
    renderSubPanel();
    panel.hidden = false;
    if (btn) btn.setAttribute("aria-expanded", "true");
  }
  function toggleSubPanel() {
    var panel = document.getElementById("sub-switch-panel");
    if (!panel) return;
    if (panel.hidden) openSubPanel(); else closeSubPanel();
  }

  /* Single entry point: every control that changes the scope goes through here,
     so the sidebar select, the topbar panel, the bills dropdown and the task
     tables can never disagree about which identity the console is showing. */
  function setActiveProfile(id) {
    var next = id || "";
    setActiveProfileId(next);
    var side = $("[data-profile-switcher] select");
    if (side && side.value !== next) side.value = next;
    var billScope = document.getElementById("bill-scope");
    if (billScope && billScope.value !== next) billScope.value = next;
    applyConfidential();
    renderScopeBar();
    renderSubPanel();
    document.dispatchEvent(new CustomEvent("karma-profile-switched", { detail: { profile_id: next } }));
  }

  function bindSwitchUI() {
    var btn = document.getElementById("btn-switch-sub");
    if (btn) {
      btn.addEventListener("click", function (ev) {
        ev.stopPropagation();
        toggleSubPanel();
      });
    }
    document.addEventListener("click", function (ev) {
      var panel = document.getElementById("sub-switch-panel");
      if (!panel || panel.hidden) return;
      if (panel.contains(ev.target)) return;
      if (btn && btn.contains(ev.target)) return;
      closeSubPanel();
    });
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") closeSubPanel();
    });
  }

  // ---- 切换器（侧边栏 identity-box）----
  function renderSwitcher(profiles) {
    var box = $(".identity-box");
    if (!box) return;
    var existing = box.querySelector("[data-profile-switcher]");
    if (existing) existing.remove();

    var wrap = document.createElement("div");
    wrap.setAttribute("data-profile-switcher", "");
    wrap.className = "profile-switcher";

    var sel = document.createElement("select");
    sel.setAttribute("aria-label", "身份角色档案");
    var none = document.createElement("option");
    none.value = "";
    none.textContent = profiles.length ? "— 选择身份档案 —" : "（无档案）";
    sel.appendChild(none);

    var active = activeProfileId();
    for (var i = 0; i < profiles.length; i++) {
      var p = profiles[i];
      var o = document.createElement("option");
      o.value = p.profile_id;
      o.textContent = (p.display_name || p.profile_id) + " · " + (p["class"] || "") + (p.visibility === "private" ? " 🔒" : "");
      if (p.profile_id === active) o.selected = true;
      sel.appendChild(o);
    }
    sel.addEventListener("change", function () {
      setActiveProfile(sel.value);
    });

    wrap.appendChild(sel);
    var sub = box.querySelector(".id-sub");
    if (sub) sub.insertAdjacentElement("afterend", wrap);
    else box.appendChild(wrap);
  }

  // ---- 涉密 ----
  function applyConfidential() {
    var p = getActiveProfile();
    var conf = !!p && p.visibility === "private";
    document.body.classList.toggle("confidential", conf);
    var badge = document.getElementById(BADGE_ID);
    if (conf) {
      if (!badge) {
        badge = document.createElement("div");
        badge.id = BADGE_ID;
        badge.className = "confidential-badge";
        badge.textContent = "🔒 涉密 · CONFIDENTIAL";
        document.body.appendChild(badge);
      }
    } else if (badge) {
      badge.remove();
    }
  }

  // ---- 档案管理（身份页）----
  function renderManage() {
    var page = document.getElementById("identity");
    if (!page) return;
    if (page.querySelector("[data-profile-manage]")) return;

    var sec = document.createElement("div");
    sec.className = "card section";
    sec.setAttribute("data-profile-manage", "");
    sec.innerHTML =
      '<div class="section-header"><div><h3>身份档案管理</h3><p>一卡多身份：创建档案、授权披露、提交 KYC、查看身份卡。</p></div></div>' +
      '<div style="display:grid;grid-template-columns:repeat(2,1fr);gap:12px;margin-top:12px">' +
      '<div class="field"><label>class</label><select id="pm-class">' +
      '<option value="individual">individual</option><option value="merchant">merchant</option><option value="enterprise">enterprise</option>' +
      '<option value="verifier">verifier</option><option value="arbitrator">arbitrator</option></select></div>' +
      '<div class="field"><label>display name</label><input id="pm-name" type="text" placeholder="我的档案" /></div>' +
      '<div class="field"><label>授权方 identity</label><input id="pm-party" type="text" placeholder="party-x" /></div>' +
      '<div class="field"><label>scope</label><select id="pm-scope"><option value="transaction">transaction（逐笔）</option><option value="ledger">ledger（整本）</option></select></div>' +
      '<div class="field"><label>task_id（transaction 必填）</label><input id="pm-task" type="text" /></div>' +
      '</div>' +
      '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px">' +
      '<button type="button" class="btn primary" id="pm-create">创建档案</button>' +
      '<button type="button" class="btn" id="pm-grant">授权披露</button>' +
      '<button type="button" class="btn" id="pm-kyc">提交 KYC</button>' +
      '<button type="button" class="btn" id="pm-card">查看身份卡</button>' +
      '<button type="button" class="btn" id="pm-reputation">查看声誉</button>' +
      '<span class="api-status" id="pm-status"></span>' +
      '</div>' +
      '<pre class="out" id="pm-out" style="margin-top:12px;max-height:240px;overflow:auto;display:none"></pre>';

    page.appendChild(sec);
    bindManage(sec);
  }

  function status(msg, ok) {
    var n = $("#pm-status");
    if (!n) return;
    n.textContent = msg;
    n.style.color = ok ? "var(--accent,#4ade80)" : "#f87171";
  }
  function out(obj) {
    var o = $("#pm-out");
    if (!o) return;
    o.textContent = typeof obj === "string" ? obj : JSON.stringify(obj, null, 2);
    o.style.display = "block";
  }

  function bindManage(sec) {
    $("#pm-create", sec).addEventListener("click", createProfile);
    $("#pm-grant", sec).addEventListener("click", grant);
    $("#pm-kyc", sec).addEventListener("click", submitKyc);
    $("#pm-card", sec).addEventListener("click", viewCard);
    $("#pm-reputation", sec).addEventListener("click", viewReputation);
  }

  async function createProfile() {
    var a = api();
    if (!a || !a.createRoleProfile) { status("缺少 API 客户端", false); return; }
    var cls = $("#pm-class").value;
    var name = $("#pm-name").value.trim();
    var body = { owner_identity_id: (window.KARMA_IDENTITY_ID || "").trim(), class: cls };
    if (name) body.display_name = name;
    status("创建中…", null);
    try {
      var p = await a.createRoleProfile(body);
      status("已创建 " + (p.profile_id || "").slice(0, 8) + "（" + cls + "）", true);
      refresh();
    } catch (e) { status("失败: " + (e.message || e), false); }
  }
  async function grant() {
    var pid = activeProfileId();
    if (!pid) { status("请先在侧边栏选择档案", false); return; }
    var party = $("#pm-party").value.trim();
    var scope = $("#pm-scope").value;
    var task = $("#pm-task").value.trim();
    if (!party) { status("请填授权方 identity", false); return; }
    var body = { authorized_identity_id: party, scope: scope };
    if (scope === "transaction") body.task_id = task || undefined;
    status("授权中…", null);
    try { await api().grantDisclosure(pid, body); status("已授权 " + party, true); }
    catch (e) { status("失败: " + (e.message || e), false); }
  }
  async function submitKyc() {
    var pid = activeProfileId();
    if (!pid) { status("请先在侧边栏选择档案", false); return; }
    status("提交 KYC…", null);
    try { await api().submitKyc(pid, { source: "cyber-console" }); status("已提交（pending）", true); }
    catch (e) { status("失败: " + (e.message || e), false); }
  }
  async function viewCard() {
    var id = (window.KARMA_IDENTITY_ID || "").trim();
    if (!id) { status("请先连接钱包", false); return; }
    status("读取身份卡…", null);
    try { var card = await api().getIdentityCard(id); status("已读取", true); out(card); }
    catch (e) { status("失败: " + (e.message || e), false); }
  }

  async function viewReputation() {
    var pid = activeProfileId();
    if (!pid) { status("请先在侧边栏选择档案", false); return; }
    status("读取声誉…", null);
    try {
      var p = await api().getRoleProfile(pid);
      var rep = p.reputation || {};
      status("声誉已读取（score=" + (rep.score != null ? rep.score : "—") + "）", true);
      out(rep);
    } catch (e) { status("失败: " + (e.message || e), false); }
  }

  async function refresh() {
    var profiles = [];
    var a = api();
    // The master identity is known as soon as SIWE returns, so draw the topbar
    // before the protected (network-bound) profile read. Otherwise the scope bar
    // still says 未连接 while the status line already says 已连接.
    renderScopeBar();
    // Role profiles are a protected read. Without a session the API answers
    // 401 by design, so skip it until the user signs in instead of logging a
    // needless 401 on every fresh visit.
    if (!window.KARMA_ACCESS_TOKEN && !window.KARMA_API_KEY) {
      renderSwitcher(profiles);
      applyConfidential();
      renderScopeBar();
      renderSubPanel();
      refreshAllocation();
      return;
    }
    try {
      if (a && a.listRoleProfiles) {
        var oid = (window.KARMA_IDENTITY_ID || "").trim();
        var body = await a.listRoleProfiles(oid);
        profiles = (body && body.profiles) || [];
      }
      try { sessionStorage.setItem(SS_PROFILES, JSON.stringify(profiles)); } catch (_) {}
    } catch (_) {}
    renderSwitcher(profiles);
    applyConfidential();
    renderScopeBar();
    renderSubPanel();
    // 额度分配 reads the profile list from sessionStorage, so it has to be
    // rebuilt whenever that list changes — otherwise a freshly created
    // sub-identity never gets an allocation row and stays at 未分配.
    refreshAllocation();
  }

  /* The card speaks two private vocabularies that mean nothing to a user:
     identity_class is user/business/agent (the ledger's axis, not the public
     role list individual/merchant/enterprise/...), verification_status is
     unverified/basic/enhanced, and status is the account state. Printing them
     raw made the card read like a debug dump. */
  var CARD_CLASS_LABELS = {
    user: "个人",
    business: "商户",
    enterprise: "企业",
    agent: "智能体",
  };
  var CARD_VERIFICATION_LABELS = {
    unverified: "未认证",
    basic: "已认证 · 基础",
    enhanced: "已认证 · 增强",
  };
  var CARD_STATUS_LABELS = {
    active: "正常",
    restricted: "受限",
    suspended: "已暂停",
    disabled: "已停用",
  };

  function cardLabel(map, value) {
    if (!value) return "—";
    return map[value] || value;
  }

  function claimCard() {
    var id = (window.KARMA_IDENTITY_ID || "").trim();
    var outEl = document.getElementById("auth-out");
    var view = document.getElementById("auth-card-view");
    if (!id) {
      if (outEl) outEl.textContent = "请先连接钱包完成认证（点「连接钱包 · 认证」）。";
      return;
    }
    if (outEl) outEl.textContent = "领取中…";
    api().getIdentityCard(id).then(function (card) {
      if (outEl) outEl.textContent = JSON.stringify(card, null, 2);
      if (view) {
        view.style.display = "block";
        view.innerHTML =
          '<div style="display:flex;gap:18px;flex-wrap:wrap">' +
          '<div><b style="font-size:11px;color:var(--text-dim)">身份 ID</b><div style="font-family:monospace">' + escapeHtml(card.identity_id || id) + '</div></div>' +
          '<div><b style="font-size:11px;color:var(--text-dim)">类别</b><div>' + escapeHtml(cardLabel(CARD_CLASS_LABELS, card.identity_class)) + '</div></div>' +
          '<div><b style="font-size:11px;color:var(--text-dim)">认证状态</b><div>' + escapeHtml(cardLabel(CARD_VERIFICATION_LABELS, card.verification_status)) + '</div></div>' +
          '<div><b style="font-size:11px;color:var(--text-dim)">账户状态</b><div>' + escapeHtml(cardLabel(CARD_STATUS_LABELS, card.status)) + '</div></div>' +
          '<div><b style="font-size:11px;color:var(--text-dim)">钱包（脱敏）</b><div style="font-family:monospace">' + escapeHtml(card.wallet || "—") + '</div></div>' +
          '</div>' +
          '<p style="margin-top:12px;color:var(--text-dim);font-size:12px">这张身份卡是你在 Karma 的通行证：认证一次即可出示给任意接入 Karma 的 agent 基础设施，用于收付验证与结算。卡内不含私钥、助记词或完整钱包地址。</p>';
      }
    }).catch(function (e) {
      if (outEl) outEl.textContent = "领取失败: " + (e.message || e);
    });
  }

  function renderAllocation() {
    var page = document.getElementById("identity");
    if (!page || page.querySelector("[data-profile-alloc]")) return;
    var sec = document.createElement("div");
    sec.className = "card section";
    sec.setAttribute("data-profile-alloc", "");
    sec.innerHTML =
      '<div class="section-header"><div><h3>额度分配</h3><p>给每个身份单独授权额度，总和不超过总锁仓；每个身份在授权额度内行事。</p></div>' +
      '<button type="button" class="btn" id="pm-alloc-refresh">刷新</button></div>' +
      '<div id="pm-alloc-list" style="margin-top:12px"></div>' +
      '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px">' +
      '<button type="button" class="btn primary" id="pm-alloc-save">保存分配</button>' +
      '<span class="api-status" id="pm-alloc-status"></span>' +
      '</div>';
    page.appendChild(sec);
    $("#pm-alloc-refresh", sec).addEventListener("click", refreshAllocation);
    $("#pm-alloc-save", sec).addEventListener("click", saveAllocation);
    refreshAllocation();
  }

  function currentProfiles() {
    try {
      return JSON.parse(sessionStorage.getItem("karma_console_profiles") || "[]");
    } catch (_) {
      return [];
    }
  }

  async function refreshAllocation() {
    var id = (window.KARMA_IDENTITY_ID || "").trim();
    var list = $("#pm-alloc-list");
    if (!list) return;
    if (!id) { list.textContent = "请先连接钱包"; return; }
    var profiles = currentProfiles();
    if (!profiles.length) { list.textContent = "还没有身份档案，请先在「身份档案管理」创建"; return; }
    var a = api();
    var allocs = {};
    try {
      var body = await a.getAllocations(id);
      (body.allocations || []).forEach(function (x) { allocs[x.profile_id] = x; });
    } catch (_) {}
    list.innerHTML = "";
    profiles.forEach(function (p) {
      var cur = allocs[p.profile_id];
      var used = cur ? ((cur.in_progress_credits || 0) + (cur.pending_settlement_credits || 0) + (cur.disputed_credits || 0)) : 0;
      var row = document.createElement("div");
      row.style.cssText = "display:grid;grid-template-columns:1fr 120px 1fr;gap:10px;align-items:center;margin-bottom:8px";
      var label = document.createElement("label");
      label.textContent = (p.display_name || p.profile_id) + " · " + (p["class"] || "");
      var input = document.createElement("input");
      input.type = "number"; input.step = "0.01"; input.min = "0"; input.style.width = "100%";
      input.dataset.allocProfile = p.profile_id;
      if (cur) input.value = String(cur.allocated_credits);
      input.placeholder = "额度";
      var usage = document.createElement("span");
      usage.className = "sub";
      usage.textContent = cur ? ("已用 " + used + " / 可用 " + (cur.available_credits || 0)) : "未分配";
      row.appendChild(label); row.appendChild(input); row.appendChild(usage);
      list.appendChild(row);
    });
  }

  async function saveAllocation() {
    var id = (window.KARMA_IDENTITY_ID || "").trim();
    var status = $("#pm-alloc-status");
    if (!id) { status.textContent = "请先连接钱包"; status.style.color = "#f87171"; return; }
    var allocations = {};
    document.querySelectorAll("[data-alloc-profile]").forEach(function (inp) {
      var v = parseFloat(inp.value);
      if (!isNaN(v) && v > 0) allocations[inp.dataset.allocProfile] = v;
    });
    if (!Object.keys(allocations).length) { status.textContent = "请至少填一个档案额度"; status.style.color = "#f87171"; return; }
    status.textContent = "保存中…"; status.style.color = "";
    try {
      await api().setAllocations(id, allocations);
      status.textContent = "已保存"; status.style.color = "var(--accent,#4ade80)";
      refreshAllocation();
    } catch (e) {
      status.textContent = "失败: " + (e.message || e); status.style.color = "#f87171";
    }
  }

  function init() {
    bindSwitchUI();
    renderScopeBar();
    renderSubPanel();
    refresh();
    renderManage();
    renderAllocation();
    var claimBtn = document.getElementById("btn-claim-card");
    if (claimBtn) claimBtn.addEventListener("click", claimCard);
    document.addEventListener("karma-wallet-connected", refresh);
    document.addEventListener("karma-session-restored", refresh);
    document.addEventListener("karma-profile-switched", function () {
      if (window.KarmaConsoleSync && window.KarmaConsoleSync.refreshAll) {
        window.KarmaConsoleSync.refreshAll().catch(function () {});
      }
    });
  }

  /* The console scope is a single source of truth; every module reads it through
     this object instead of touching sessionStorage directly. */
  window.KarmaIdentitySwitcher = {
    getActiveProfileId: activeProfileId,
    setActiveProfileId: setActiveProfile,
    getActiveProfile: getActiveProfile,
    getProfiles: getProfiles,
    profileLabel: profileLabel,
    render: function () { renderScopeBar(); renderSubPanel(); },
    refresh: refresh,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
