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
  function esc(v) {
    return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  /** Mirrors api/routes/agents.py + agent_onboarding_template._validate_service_specs. */
  function isPricePath(path) {
    var p = String(path || "");
    return (
      p.slice(-8) === "currency" ||
      p.indexOf("price") !== -1 ||
      p.slice(-4) === "fare" ||
      p.slice(-4) === "_fee" ||
      p.slice(-7) === "per_km" ||
      p.slice(-11) === "per_minute" ||
      p.slice(-10) === "unit_price" ||
      p.slice(-14) === "rate_or_fixed" ||
      p.slice(-9) === "base_fare" ||
      p.slice(-6) === "amount" ||
      p.indexOf("nightly_rate") !== -1
    );
  }

  function pathKey(path) {
    return "spec::" + String(path || "").replace(/\./g, "__");
  }

  // ---------- 我的 Agent ----------

  function renderAgentRow(a) {
    var ready = a.p1_ready === true;
    var cls = ready ? "ok" : "warn";
    var gaps = (a.p1_gaps || []).join(", ");
    var keyTag = a.key_custody === "server_side_revocable"
      ? '<span class="tag">密钥托管·可吊销</span>'
      : '<span class="tag muted">外部密钥</span>';
    return (
      '<div class="agent-row">' +
      '<div class="agent-row-main">' +
      '<b>' + esc(a.name || a.agent_id) + "</b>" +
      '<code>' + esc(a.agent_id) + "</code>" +
      '<span class="tag">' + esc(a.identity_class || "—") + "</span>" +
      '<span class="tag ' + cls + '">' + (ready ? "P1 就绪" : "P1 未就绪") + "</span>" +
      keyTag +
      "</div>" +
      '<div class="agent-row-sub">' +
      "角色 " + esc(a.role || "—") +
      " · 接入路径 " + esc(a.connect_path || "—") +
      " · 档案 " + esc(a.scope_profile_id || "未绑定") +
      (gaps ? " · <span class=\"err\">缺 " + esc(gaps) + "</span>" : "") +
      "</div>" +
      '<div class="agent-row-actions">' +
      '<input type="number" min="0" step="0.01" placeholder="授权额度 USDC" data-alloc-live="' + esc(a.scope_profile_id || "") + '" data-agent="' + esc(a.agent_id) + '" />' +
      '<button type="button" class="btn" data-agent-alloc="' + esc(a.agent_id) + '">授权额度</button>' +
      '<button type="button" class="btn red" data-agent-revoke="' + esc(a.agent_id) + '">停用并销毁密钥</button>' +
      "</div>" +
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
      if (!agents.length) {
        list.innerHTML = '<p class="muted">这张身份卡还没有接入任何 agent。用下面的一键接入，30 秒建一个。</p>';
      } else {
        list.innerHTML = agents.map(renderAgentRow).join("");
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
            esc(i.title_zh || i.title_en || i.industry_id) + "</option>";
        });
        html += "</optgroup>";
      });
      sel.innerHTML = html;
      sel.disabled = false;
    } catch (e) {
      sel.innerHTML = '<option value="">行业目录读取失败</option>';
    }
  }

  function renderSpecField(req) {
    var path = req.path;
    var type = req.type || "string";
    var label = req.description_zh || req.description_en || path;
    var hint = req.description_zh && req.description_zh !== path ? path : "";
    var key = pathKey(path);
    var common = ' data-spec-path="' + esc(path) + '" id="' + esc(key) + '"';

    if (type === "object" || path === "business_hours") {
      return (
        '<div class="field ag-spec-field" data-spec-object="' + esc(path) + '">' +
        "<label>" + esc(label) + " <code>" + esc(path) + "</code></label>" +
        '<div class="ag-inline">' +
        '<input type="text" data-spec-part="timezone" placeholder="时区，如 Asia/Shanghai" />' +
        '<label class="ag-check"><input type="checkbox" data-spec-part="24_7" checked /> 7×24</label>' +
        "</div>" +
        '<input type="text" data-spec-part="weekly" placeholder="非 7×24 时填营业时间，如 Mon-Sun 09:00-22:00" />' +
        "</div>"
      );
    }
    if (type === "array") {
      return (
        '<div class="field ag-spec-field">' +
        "<label>" + esc(label) + " <code>" + esc(path) + "</code></label>" +
        '<textarea rows="2" data-spec-type="array"' + common + ' placeholder="每行一项 / 或用逗号分隔"></textarea>' +
        "</div>"
      );
    }
    if (type === "boolean") {
      return (
        '<div class="field ag-spec-field">' +
        "<label>" + esc(label) + " <code>" + esc(path) + "</code></label>" +
        '<select data-spec-type="boolean"' + common + '><option value="true">是</option><option value="false">否</option></select>' +
        "</div>"
      );
    }
    if (type === "integer" || type === "number") {
      var step = type === "integer" ? "1" : "0.01";
      return (
        '<div class="field ag-spec-field">' +
        "<label>" + esc(label) + " <code>" + esc(path) + "</code></label>" +
        '<input type="number" step="' + step + '" data-spec-type="' + type + '"' + common + " />" +
        "</div>"
      );
    }
    var price = isPricePath(path);
    return (
      '<div class="field ag-spec-field">' +
      "<label>" + esc(label) + " <code>" + esc(path) + "</code>" +
      (price ? ' <span class="tag muted">字符串金额</span>' : "") +
      "</label>" +
      '<input type="text" data-spec-type="string"' + common +
      (price ? ' placeholder="如 3.50（必须是字符串）"' : "") + " />" +
      (hint ? '<span class="ag-hint">' + esc(hint) + "</span>" : "") +
      "</div>"
    );
  }

  async function renderSpecForm(industryId) {
    var host = $("#ag-spec-form");
    if (!host) return;
    CURRENT = null;
    if (!industryId) {
      host.innerHTML = "";
      return;
    }
    host.innerHTML = '<p class="muted">读取行业必填项…</p>';
    try {
      var body = await api().getOnboardingIndustry(industryId);
      var ind = body.industry || body;
      CURRENT = ind;
      var reqs = ind.required_service_spec || [];
      if (!reqs.length) {
        host.innerHTML = '<p class="muted">该行业没有额外硬指标字段。</p>';
        return;
      }
      var html = '<div class="ag-spec-head"><b>行业硬指标</b><span>' +
        esc(ind.title_zh || industryId) + " · 共 " + reqs.length + " 项（全部必填）</span>" +
        '<button type="button" class="btn" id="ag-spec-example">按示例填充</button></div>' +
        '<div class="ag-spec-grid">' + reqs.map(renderSpecField).join("") + "</div>";
      host.innerHTML = html;
      var btn = $("#ag-spec-example");
      if (btn) btn.addEventListener("click", fillFromExample);
    } catch (e) {
      host.innerHTML = '<p class="err">读取失败：' + esc(e.message || e) + "</p>";
    }
  }

  function setFieldValue(req, value) {
    var path = req.path;
    if (req.type === "object" || path === "business_hours") {
      var box = $('[data-spec-object="' + path + '"]');
      if (!box || !value || typeof value !== "object") return;
      var tz = box.querySelector('[data-spec-part="timezone"]');
      var all = box.querySelector('[data-spec-part="24_7"]');
      var wk = box.querySelector('[data-spec-part="weekly"]');
      if (tz && value.timezone) tz.value = value.timezone;
      if (all && typeof value["24_7"] === "boolean") all.checked = value["24_7"];
      if (wk && value.weekly) wk.value = Array.isArray(value.weekly) ? value.weekly.join("; ") : String(value.weekly);
      return;
    }
    var node = document.getElementById(pathKey(path));
    if (!node) return;
    if (req.type === "array") {
      node.value = Array.isArray(value) ? value.join("\n") : String(value == null ? "" : value);
    } else if (req.type === "boolean") {
      node.value = value === false ? "false" : "true";
    } else {
      node.value = value == null ? "" : String(value);
    }
  }

  function fillFromExample() {
    if (!CURRENT || !CURRENT.example_service_spec) return;
    var example = CURRENT.example_service_spec;
    (CURRENT.required_service_spec || []).forEach(function (req) {
      var v = dig(example, req.path);
      if (v !== null && v !== undefined) setFieldValue(req, v);
    });
  }

  function dig(obj, path) {
    var cur = obj;
    var parts = String(path).split(".");
    for (var i = 0; i < parts.length; i++) {
      if (cur == null || typeof cur !== "object") return null;
      cur = cur[parts[i]];
    }
    return cur === undefined ? null : cur;
  }

  function assign(target, path, value) {
    var parts = String(path).split(".");
    var cur = target;
    for (var i = 0; i < parts.length - 1; i++) {
      if (typeof cur[parts[i]] !== "object" || cur[parts[i]] === null) cur[parts[i]] = {};
      cur = cur[parts[i]];
    }
    cur[parts[parts.length - 1]] = value;
  }

  /** Convert the rendered form into the exact service_specs contract. */
  function collectSpec() {
    var spec = {};
    var problems = [];
    if (!CURRENT) return { spec: spec, problems: ["请先选择行业"] };
    var reqs = CURRENT.required_service_spec || [];
    for (var i = 0; i < reqs.length; i++) {
      var req = reqs[i];
      var path = req.path;
      var type = req.type || "string";
      if (type === "object" || path === "business_hours") {
        var box = $('[data-spec-object="' + path + '"]');
        var hours = {};
        if (box) {
          var tz = box.querySelector('[data-spec-part="timezone"]').value.trim();
          var is247 = box.querySelector('[data-spec-part="24_7"]').checked;
          var weeklyRaw = box.querySelector('[data-spec-part="weekly"]').value.trim();
          if (tz) hours.timezone = tz;
          if (is247) hours["24_7"] = true;
          if (weeklyRaw) hours.weekly = weeklyRaw.split(/[;\n]/).map(function (x) { return x.trim(); }).filter(Boolean);
        }
        if (!hours.timezone) problems.push(path + " 需要 timezone");
        if (!hours["24_7"] && !hours.weekly) problems.push(path + " 需要 7×24 或营业时间");
        if (Object.keys(hours).length) assign(spec, path, hours);
        continue;
      }
      var node = document.getElementById(pathKey(path));
      var raw = node ? String(node.value).trim() : "";
      if (!raw) {
        problems.push((req.description_zh || path) + " 必填");
        continue;
      }
      if (type === "array") {
        var items = raw.split(/[\n,]/).map(function (x) { return x.trim(); }).filter(Boolean);
        if (!items.length) {
          problems.push((req.description_zh || path) + " 至少一项");
          continue;
        }
        assign(spec, path, items);
      } else if (type === "boolean") {
        assign(spec, path, raw === "true");
      } else if (type === "integer") {
        var iv = parseInt(raw, 10);
        if (Number.isNaN(iv)) { problems.push(path + " 必须是整数"); continue; }
        assign(spec, path, iv);
      } else if (type === "number") {
        var nv = Number(raw);
        if (Number.isNaN(nv)) { problems.push(path + " 必须是数字"); continue; }
        assign(spec, path, nv);
      } else {
        // Price-like paths must stay strings; the API rejects numbers outright.
        assign(spec, path, raw);
      }
    }
    return { spec: spec, problems: problems };
  }

  async function loadProfilesIntoSelect() {
    var sel = $("#ag-scope");
    if (!sel) return;
    var id = identity();
    if (!id) {
      sel.innerHTML = '<option value="">（先连接钱包）</option>';
      return;
    }
    sel.innerHTML = '<option value="">读取档案…</option>';
    try {
      var body = await api().listRoleProfiles(id);
      var profiles = body.profiles || [];
      var mine = profiles.filter(function (p) {
        return !p.owner_identity_id || p.owner_identity_id === id;
      });
      var html = '<option value="">（暂不绑定档案）</option>';
      mine.forEach(function (p) {
        html += '<option value="' + esc(p.profile_id) + '">' +
          esc(p.display_name || p.profile_id) + " · " + esc(p["class"] || "") + "</option>";
      });
      sel.innerHTML = html;
    } catch (e) {
      sel.innerHTML = '<option value="">（档案读取失败）</option>';
    }
  }

  async function ensureProfile(className) {
    var id = identity();
    if (!id) throw new Error("请先连接钱包");
    var body = await api().listRoleProfiles(id);
    var existing = (body.profiles || []).find(function (p) {
      return p["class"] === className && (!p.owner_identity_id || p.owner_identity_id === id);
    });
    if (existing) return existing.profile_id;
    var created = await api().createRoleProfile({
      owner_identity_id: id,
      class: className,
      display_name: className === "enterprise" ? "企业档案" : "商家档案",
    });
    return created.profile_id;
  }

  function setWizardStatus(msg, isErr) {
    var node = $("#ag-wizard-status");
    if (!node) return;
    node.textContent = msg || "";
    node.classList.toggle("err", !!isErr);
  }

  async function submitConnect() {
    var out = $("#ag-out");
    var status = $("#ag-wizard-status");
    var side = $("#ag-side").value;
    var vertical = $("#ag-vertical").value;
    var id = identity();
    if (out) out.textContent = "—";
    if (!id) {
      setWizardStatus("请先在顶部「连接钱包」完成认证，拿到身份卡后再接入 agent", true);
      return;
    }
    if (!vertical) {
      setWizardStatus("请选择行业", true);
      return;
    }
    var answers = { industry_ids: [vertical] };
    if (side === "seller") {
      var collected = collectSpec();
      if (collected.problems.length) {
        setWizardStatus("还差 " + collected.problems.length + " 项：" + collected.problems.slice(0, 4).join("；"), true);
        return;
      }
      answers.service_specs = {};
      answers.service_specs[vertical] = collected.spec;
    }
    var scopeProfile = $("#ag-scope") ? $("#ag-scope").value : "";
    if (!scopeProfile && side === "seller") {
      try {
        var want = $("#ag-class") && $("#ag-class").value ? $("#ag-class").value : "merchant";
        scopeProfile = await ensureProfile(want);
        if ($("#ag-scope")) $("#ag-scope").value = scopeProfile;
      } catch (e) {
        setWizardStatus("档案准备失败：" + (e.message || e), true);
        return;
      }
    }
    var payload = {
      side: side,
      vertical: vertical,
      display_name: ($("#ag-name").value || "").trim() || undefined,
      owner_identity_id: id,
      endpoint_url: ($("#ag-endpoint").value || "").trim() || undefined,
      scope_profile_id: scopeProfile || undefined,
      answers: answers,
      mint_api_key: true,
    };
    setWizardStatus("接入中…");
    try {
      var res = await api().ownerConnect(payload);
      setWizardStatus("接入成功 · " + res.agent.agent_id);
      if (out) out.textContent = JSON.stringify(res, null, 2);
      renderConnectResult(res);
      refreshAgents();
      loadProfilesIntoSelect();
    } catch (e) {
      setWizardStatus("接入失败：" + (e.message || e), true);
      if (out) out.textContent = String(e.message || e);
    }
  }

  function renderConnectResult(res) {
    var host = $("#ag-result");
    if (!host) return;
    var creds = res.credentials || {};
    var ready = res.p1_ready === true;
    var env = res.env_snippet || {};
    var envText = Object.keys(env).map(function (k) { return k + "=" + env[k]; }).join("\n");
    host.style.display = "block";
    host.innerHTML =
      '<div class="ag-result-head">' +
      '<b>' + esc(res.agent.name) + "</b>" +
      '<span class="tag ' + (ready ? "ok" : "warn") + '">' + (ready ? "P1 就绪" : "P1 未就绪") + "</span>" +
      '<span class="tag">' + esc(res.profile_id) + "</span>" +
      "</div>" +
      '<p class="ag-hint">身份卡：' + esc(res.agent.owner_identity_id || identity()) + " → agent：" + esc(res.agent.agent_id) + "</p>" +
      (creds.api_key
        ? '<div class="ag-secret"><div class="ag-secret-label">API Key（仅此一次明文显示，请立即保存）</div>' +
          "<code>" + esc(creds.api_key) + "</code>" +
          '<button type="button" class="btn primary" id="ag-copy-key">复制</button></div>'
        : '<p class="err">未签发 API Key</p>') +
      '<div class="ag-snippet"><div class="ag-secret-label">环境变量</div><pre>' + esc(envText) + "</pre>" +
      '<button type="button" class="btn" id="ag-copy-env">复制</button></div>' +
      '<div class="ag-next"><b>下一步</b><ol>' +
      (res.next_steps || []).map(function (s) { return "<li>" + esc(s) + "</li>"; }).join("") +
      "</ol></div>" +
      '<p class="ag-hint">agent 运行密钥由 Karma 服务端托管（0600，可随时吊销），整个流程不涉及你的钱包私钥或助记词。</p>';

    var ck = $("#ag-copy-key");
    if (ck) ck.addEventListener("click", function () { copyText(creds.api_key || ""); });
    var ce = $("#ag-copy-env");
    if (ce) ce.addEventListener("click", function () { copyText(envText); });
  }

  function copyText(text) {
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text);
        return;
      }
    } catch (_) {}
    var ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand("copy"); } catch (_) {}
    ta.remove();
  }

  function init() {
    if (!$("#agents")) return;
    loadIndustries();
    loadProfilesIntoSelect();
    refreshAgents();

    var sideSel = $("#ag-side");
    if (sideSel) {
      sideSel.addEventListener("change", function () {
        var seller = sideSel.value === "seller";
        var wrap = $("#ag-spec-wrap");
        if (wrap) wrap.style.display = seller ? "" : "none";
        if (!seller) {
          var host = $("#ag-spec-form");
          if (host) host.innerHTML = '<p class="muted">买方身份（user profile）不需要行业硬指标，直接接入即可。</p>';
        } else {
          renderSpecForm($("#ag-vertical").value);
        }
      });
    }
    var vertSel = $("#ag-vertical");
    if (vertSel) {
      vertSel.addEventListener("change", function () { renderSpecForm(vertSel.value); });
    }
    var btn = $("#ag-connect");
    if (btn) btn.addEventListener("click", submitConnect);
    var refresh = $("#ag-list-refresh");
    if (refresh) refresh.addEventListener("click", function () { refreshAgents(); loadProfilesIntoSelect(); });

    document.addEventListener("karma-wallet-connected", function () {
      loadProfilesIntoSelect();
      refreshAgents();
    });
    document.addEventListener("karma-session-restored", function () {
      loadProfilesIntoSelect();
      refreshAgents();
    });

    document.addEventListener("click", function (ev) {
      var t = ev.target;
      if (!t || !t.getAttribute) return;
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
})();