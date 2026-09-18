/**
 * 操作台 · 配对码接入 —— 让 agent 自己把凭据领走。
 *
 * 「授权向导 → 交给 Agent」是手动版：生成密钥、复制、粘贴给 agent。这一页换成
 * 正向顺序：agent 先发起，拿到一串配对码；主人只做两个决定（批准接入、划多少
 * 额度），凭据由 Karma 直接交给持配对码的那个进程。
 *
 * 改这个文件时不要破坏这三条：
 *   1. 一次性 —— 批准后的 API Key / Runtime Key 只走 agent 的 claim，从不回到本页；
 *   2. 只签一次 —— 额度那步用钱包 EIP-191 签名，私钥 / 助记词永远不离开钱包；
 *   3. 方向不能反 —— 本页只批准请求，绝不出现「把密钥填进来」的输入框。
 */
(function (global) {
  "use strict";

  var state = {
    code: "",
    view: null,
    agentId: "",
    agentName: "",
    busy: false,
    autoLookup: false,
    industries: null,
    industryLoad: null,
    industry: null,
    specToken: 0,
  };

  function api() { return global.cyberKarmaApi; }
  function byId(id) { return document.getElementById(id); }
  function identity() { return String(global.KARMA_IDENTITY_ID || "").trim(); }

  function esc(v) {
    return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function setStatus(node, msg, isErr) {
    if (!node) return;
    node.textContent = msg || "";
    node.classList.toggle("err", !!isErr);
  }

  function show(node, on) {
    if (node) node.hidden = !on;
  }

  /** 行业标题、行业硬指标表单都在 karma-service-spec.js 里，和「接入一个 Agent」共用一份。 */
  function spec() {
    return global.KarmaServiceSpec;
  }

  function industryTitle(row, fallback) {
    var s = spec();
    if (s) return s.industryTitle(row, fallback);
    return (row && (row.title_zh || row.title_en)) || fallback;
  }

  /* ------------------------------------------------------------ 权限与目录 */

  function permsCatalog() {
    var a = global.KarmaAuthorize;
    return (a && a.PERMS) || [];
  }

  function defaultPerms() {
    var a = global.KarmaAuthorize;
    return (a && a.DEFAULT_PERMS) || [];
  }

  function renderPerms() {
    var host = byId("pair-perms");
    if (!host || host.getAttribute("data-ready") === "1") return;
    var def = defaultPerms();
    host.innerHTML = permsCatalog()
      .map(function (p) {
        var on = def.indexOf(p.key) !== -1;
        return (
          '<label class="pair-perm"><input type="checkbox" data-pair-perm="' +
          esc(p.key) + '"' + (on ? " checked" : "") + " /><b>" + esc(p.label) +
          "</b><span>" + esc(p.hint) + "</span></label>"
        );
      })
      .join("");
    host.setAttribute("data-ready", "1");
  }

  function selectedPerms() {
    var out = [];
    Array.prototype.slice.call(document.querySelectorAll("[data-pair-perm]")).forEach(function (el) {
      if (el.checked) out.push(el.getAttribute("data-pair-perm"));
    });
    return out.sort();
  }

  /**
   * 行业目录只拉一次，并且把那次请求记下来 —— 查询、批准、硬指标表单都要等它，
   * 各拉一遍就是重复打同一个接口。
   */
  function loadIndustries() {
    if (state.industries) return Promise.resolve(state.industries);
    if (state.industryLoad) return state.industryLoad;
    var sel = byId("pair-vertical");
    if (!sel) return Promise.resolve(null);
    state.industryLoad = api()
      .listOnboardingIndustries()
      .then(function (body) {
        state.industries = body.industries || body.items || [];
        var html = '<option value="">请选择行业</option>';
        state.industries.forEach(function (i) {
          html +=
            '<option value="' + esc(i.industry_id) + '">' +
            esc(industryTitle(i, i.industry_id)) + "</option>";
        });
        sel.innerHTML = html;
        sel.disabled = false;
        return state.industries;
      })
      .catch(function () {
        sel.innerHTML = '<option value="">行业目录读取失败</option>';
        return null;
      });
    return state.industryLoad;
  }

  function findIndustry(industryId) {
    var want = String(industryId || "").trim();
    if (!want || !state.industries) return null;
    for (var i = 0; i < state.industries.length; i++) {
      if (state.industries[i].industry_id === want) return state.industries[i];
    }
    return null;
  }

  /**
   * agent 申报的行业 -> 目录里的 industry_id。服务端在 request 时已经用
   * VERTICAL_ALIASES 归一过（food -> food_delivery），所以这里先认
   * requested_industry_id，认不出来再退回 requested_vertical。
   */
  function resolveIndustryId(view) {
    var v = view || {};
    var want = String(v.requested_industry_id || v.requested_vertical || "").trim();
    return findIndustry(want) ? want : "";
  }

  async function loadProfiles() {
    var sel = byId("pair-scope");
    if (!sel) return;
    var id = identity();
    if (!id) {
      sel.innerHTML = '<option value="">（先连接钱包）</option>';
      return;
    }
    try {
      var body = await api().listRoleProfiles(id);
      var mine = (body.profiles || []).filter(function (p) {
        return !p.owner_identity_id || p.owner_identity_id === id;
      });
      var html = '<option value="">（暂不绑定档案）</option>';
      mine.forEach(function (p) {
        html +=
          '<option value="' + esc(p.profile_id) + '">' +
          esc(p.display_name || p.profile_id) + " · " + esc(p["class"] || "") + "</option>";
      });
      sel.innerHTML = html;
    } catch (_) {
      sel.innerHTML = '<option value="">（档案读取失败）</option>';
    }
  }

  /* ---------------------------------------------------------------- 渲染 */

  var STATUS_TEXT = {
    pending: "等待你批准",
    approved: "已批准，等 agent 领取",
    claimed: "agent 已领走凭据",
    denied: "已拒绝",
    expired: "已过期",
  };

  function renderRequest() {
    var host = byId("pair-request");
    var v = state.view;
    if (!host) return;
    if (!v) { host.hidden = true; host.innerHTML = ""; return; }
    var rows = [
      ["Agent 名称", v.agent_name || "—"],
      ["来源平台", v.platform || "—"],
      ["公钥指纹", v.public_key_fingerprint || "（未提供公钥）"],
      ["回调地址", v.endpoint_url || "—"],
      ["申请方向", v.requested_side === "seller" ? "收款（卖家 agent）" : v.requested_side === "buyer" ? "付款（买家 agent）" : "—"],
      ["申请行业", v.requested_vertical || "—"],
      ["自述", v.self_description || "—"],
      ["状态", STATUS_TEXT[v.status] || v.status],
      ["有效期至", v.expires_at || "—"],
    ];
    host.innerHTML =
      '<div class="pair-request-head"><b>' + esc(v.agent_name || "未知 agent") +
      '</b><span>' + esc(v.user_code || "") + "</span></div>" +
      '<table class="pair-table">' +
      rows.map(function (r) {
        return "<tr><th>" + esc(r[0]) + "</th><td>" + esc(r[1]) + "</td></tr>";
      }).join("") +
      "</table>" +
      '<p class="pair-hint">只批准你认得的 agent。批准等于用你的身份为它背书，' +
      "额度用你在下面填的数为准，随时可以在「我的 Agent」里吊销。</p>";
    host.hidden = false;
  }

  function renderResult(html, isErr) {
    var host = byId("pair-result");
    if (!host) return;
    host.innerHTML = html || "";
    host.classList.toggle("err", !!isErr);
  }

  function renderApproved() {
    var box = byId("pair-grant");
    var name = byId("pair-grant-name");
    if (name) name.textContent = state.agentName || state.agentId || "";
    show(box, true);
    var v = state.view || {};
    var vn = byId("pair-name");
    if (vn && !vn.value) vn.value = v.agent_name || "";
    renderPerms();
  }

  /* ------------------------------------------ 行业硬指标（与「接入一个 Agent」共用表单） */

  function specHost() {
    return byId("pair-spec-form");
  }

  function note(msg, isErr) {
    var node = byId("pair-spec-note");
    if (!node) return;
    node.textContent = msg || "";
    node.classList.toggle("err", !!isErr);
    node.hidden = !msg;
  }

  /** agent 在 request 里自报的 service_specs[行业]。只用来预填，提交以表单为准。 */
  function declaredSpecs(industryId) {
    var v = state.view || {};
    var specs = (v.requested_answers || {}).service_specs || {};
    return specs[industryId] || specs[v.requested_vertical] || null;
  }

  /**
   * 行业硬指标：买方没有，卖方必须有 —— 服务端拿它当接入边界校验，不合规 P1 门禁会拒。
   *
   * agent 自报的那份只填进表单给主人核对。以前这一页把 requested_answers 原样透传，
   * 主人看到的是「HTTP 400」，既不知道错在哪一项也改不了；现在表单在页面上，
   * 提交时以主人看到的这份为准。
   */
  async function renderPairSpec() {
    var host = specHost();
    if (!host) return;
    var token = ++state.specToken;
    var side = (byId("pair-side") || {}).value || (state.view || {}).requested_side || "buyer";
    var industryId = (byId("pair-vertical") || {}).value || "";
    state.industry = null;
    note("");
    if (side !== "seller") {
      host.innerHTML =
        '<p class="muted">买方身份（user profile）不需要行业硬指标，直接接入即可。</p>';
      return;
    }
    if (!industryId) {
      host.innerHTML = "";
      return;
    }
    host.innerHTML = '<p class="muted">读取行业必填项…</p>';
    try {
      var body = await api().getOnboardingIndustry(industryId);
      if (token !== state.specToken) return; // 主人已经换了行业，这次结果作废
      var ind = body.industry || body;
      state.industry = ind;
      var s = spec();
      if (!s) {
        host.innerHTML = '<p class="err">硬指标表单未加载，请刷新页面</p>';
        return;
      }
      s.renderForm(host, ind);
      var declared = declaredSpecs(industryId);
      if (declared) {
        var filled = s.applyValues(host, declared);
        if (filled) {
          note("agent 已申报 " + filled + " 项，请核对；不对就直接改，提交以本表单为准。");
        }
      }
    } catch (e) {
      if (token !== state.specToken) return;
      host.innerHTML = '<p class="err">读取失败：' + esc(e.message || e) + "</p>";
    }
  }

  /* ---------------------------------------------------------------- 动作 */

  /** 把 agent 申报的方向 / 行业落进表单，再据此渲染硬指标。 */
  async function prefillDecision() {
    var v = state.view || {};
    await loadIndustries();
    var vs = byId("pair-side");
    if (vs && v.requested_side) vs.value = v.requested_side;
    var vy = byId("pair-vertical");
    var wanted = String(v.requested_industry_id || v.requested_vertical || "").trim();
    var got = resolveIndustryId(v);
    if (vy) vy.value = got;
    // 先渲染表单（它自己会清提示），再补「目录里没这个行业」那句。
    await renderPairSpec();
    if (!got && wanted) {
      note("agent 申报的行业「" + wanted + "」不在目录里，请手动选一个。");
    }
  }

  async function query() {
    var status = byId("pair-status");
    var code = ((byId("pair-code") || {}).value || "").trim();
    if (!code) {
      setStatus(status, "先把 agent 给你的配对码填进来", true);
      return;
    }
    state.code = code;
    setStatus(status, "查询中…");
    try {
      state.view = await api().lookupPairing(code);
      renderRequest();
      var pending = state.view.status === "pending";
      show(byId("pair-decide"), pending);
      show(byId("pair-grant"), false);
      renderResult("");
      if (pending) await prefillDecision();
      setStatus(status, pending ? "等待你批准" : "这条请求已处理");
    } catch (e) {
      state.view = null;
      renderRequest();
      show(byId("pair-decide"), false);
      show(byId("pair-grant"), false);
      setStatus(status, e && e.message ? e.message : String(e), true);
    }
  }

  async function approve() {
    var status = byId("pair-status");
    if (!state.view) return;
    if (!identity()) {
      setStatus(status, "请先在顶部「连接钱包」完成认证", true);
      return;
    }
    var side = (byId("pair-side") || {}).value || state.view.requested_side || "buyer";
    var vertical = (byId("pair-vertical") || {}).value || "";
    // 主人屏幕上这份表单说了算：行业、以及这个行业的硬指标，一起覆盖 agent 自报的。
    var answers = Object.assign({}, state.view.requested_answers || {});
    if (side === "seller") {
      if (!vertical) {
        setStatus(status, "请先选择行业 —— 硬指标是按行业定的", true);
        return;
      }
      var host = specHost();
      var s = spec();
      if (!s || !state.industry || !host) {
        setStatus(status, "行业硬指标还没读出来，稍等一下再点批准", true);
        return;
      }
      var collected = s.collect(host);
      if (collected.problems.length) {
        renderResult(
          "<b>行业硬指标还差 " + collected.problems.length + " 项</b><p>" +
            esc(collected.problems.join("；")) + "</p>",
          true
        );
        setStatus(status, "行业硬指标不合格，先补齐再批准", true);
        return;
      }
      answers.industry_ids = [vertical];
      answers.service_specs = Object.assign({}, answers.service_specs || {});
      answers.service_specs[vertical] = collected.spec;
    }
    if (state.busy) return;
    state.busy = true;
    setStatus(status, "批准中…");
    try {
      var payload = {
        user_code: state.code,
        side: side,
        vertical: vertical || undefined,
        display_name: (byId("pair-name") || {}).value || undefined,
        scope_profile_id: (byId("pair-scope") || {}).value || undefined,
        answers: answers,
      };
      var body = await api().approvePairing(payload);
      var agent = body.agent || {};
      state.agentId = agent.agent_id || "";
      state.agentName = agent.name || payload.display_name || "";
      show(byId("pair-decide"), false);
      renderApproved();
      renderResult(
        "<b>已批准接入</b><p>" + esc(state.agentId) + "</p>" +
          "<p>API Key 已经放进这次配对，等它自己来领（只发一次，本页不会显示这串密钥）。</p>"
      );
      setStatus(status, "已批准，等 agent 领取");
      document.dispatchEvent(new CustomEvent("karma-agent-connected", { detail: { agent_id: state.agentId } }));
    } catch (e) {
      // 服务端的 400 要原样摆在页面上（比如硬指标哪一项不合规），别只塞进状态栏。
      var msg = e && e.message ? e.message : String(e);
      renderResult("<b>批准失败</b><p>" + esc(msg) + "</p>", true);
      setStatus(status, msg, true);
    } finally {
      state.busy = false;
    }
  }

  async function reject() {
    var status = byId("pair-status");
    if (!state.view) return;
    state.busy = true;
    try {
      await api().denyPairing({ user_code: state.code, reason: "owner declined" });
      state.view = Object.assign({}, state.view, { status: "denied" });
      renderRequest();
      show(byId("pair-decide"), false);
      setStatus(status, "已拒绝，agent 那边拿不到任何凭据");
    } catch (e) {
      setStatus(status, e && e.message ? e.message : String(e), true);
    } finally {
      state.busy = false;
    }
  }

  /** 额度那一步：先落策略，再签名铸造 runtime key，最后挂到这次配对交付里。 */
  async function grant() {
    var status = byId("pair-grant-status");
    var id = identity();
    if (!id) {
      setStatus(status, "请先在顶部「连接钱包」完成认证", true);
      return;
    }
    if (!state.agentId) {
      setStatus(status, "先批准接入，再划额度", true);
      return;
    }
    var perms = selectedPerms();
    if (!perms.length) {
      setStatus(status, "至少勾一项权限", true);
      return;
    }
    var single = Number((byId("pair-single") || {}).value || 0);
    var daily = Number((byId("pair-daily") || {}).value || 0);
    // 服务端 90 天封顶（MAX_KEY_LIFETIME_DAYS）：铸不出「十年有效的钥匙」。
    // 这里先夹住，别让用户填完、签完名才吃一个 400。
    var days = Math.min(90, Math.max(1, Number((byId("pair-expire-days") || {}).value || 7)));
    if (!(single > 0) || !(daily > 0)) {
      setStatus(status, "单笔和每日上限都要大于 0", true);
      return;
    }
    if (daily + 1e-9 < single) {
      setStatus(status, "每日上限不能小于单笔上限", true);
      return;
    }
    var provider =
      global.KarmaWalletAuth && global.KarmaWalletAuth.activeProvider && global.KarmaWalletAuth.activeProvider();
    if (!provider || typeof provider.request !== "function") {
      setStatus(status, "没检测到钱包插件，请用顶部「连接钱包」重新连一次", true);
      return;
    }
    if (state.busy) return;
    state.busy = true;
    try {
      setStatus(status, "① 保存权限与边界…");
      await api().putAutomationPolicy(id, {
        auto_enabled: true,
        responsibility_acknowledged: true,
        single_limit: single,
        daily_limit: daily,
        permissions: perms,
        high_risk_mode: "above_single",
      });

      setStatus(status, "② 请在钱包里签名（签一次，生成钱钥匙）…");
      var accounts = await provider.request({ method: "eth_requestAccounts" });
      var wallet = accounts && accounts[0];
      if (!wallet) throw new Error("钱包没有返回地址");
      var build = global.KarmaAuthorize && global.KarmaAuthorize.buildCreateKeyMsg;
      var pyIso = global.KarmaAuthorize && global.KarmaAuthorize.pyUtcIso;
      if (!build || !pyIso) throw new Error("签名工具未加载，请刷新页面");
      var fields = {
        karma_identity_id: id,
        wallet_address: wallet,
        permissions: perms.slice(),
        single_limit: single,
        daily_limit: daily,
        expire_time: pyIso(Date.now() + Math.max(1, days) * 86400e3),
        agent_name: state.agentName || state.agentId,
        // 记下这把钥匙是给哪个 agent 铸的。agent_binding 是写进钱包签名消息的字段，
        // 所以服务端能确认「用户本人授权了这个 agent」；下面还会单独传 agent_id 做交叉校验。
        agent_binding: state.agentId,
        agent_id: state.agentId,
      };
      var sig = await provider.request({
        method: "personal_sign",
        params: [build(fields), wallet],
      });
      var res = await global.karmaRuntimeApi.runtimeCreateKey({
        wallet_address: wallet,
        karma_identity_id: id,
        wallet_signature: sig,
        permissions: perms,
        single_limit: single,
        daily_limit: daily,
        expire_time: fields.expire_time,
        agent_name: fields.agent_name,
        agent_binding: fields.agent_binding,
        agent_id: fields.agent_id,
        profile_id: (byId("pair-scope") || {}).value || undefined,
      });

      setStatus(status, "③ 放进交付，等 agent 来领…");
      await api().attachPairingRuntimeKey({
        user_code: state.code,
        runtime_key: res.runtime_key,
      });
      renderResult(
        "<b>额度已授权并交付</b>" +
          '<table class="pair-table">' +
          "<tr><th>单笔上限（USDC）</th><td>" + esc(single) + "</td></tr>" +
          "<tr><th>每日上限（USDC）</th><td>" + esc(daily) + "</td></tr>" +
          "<tr><th>有效期（天）</th><td>" + esc(days) + "</td></tr>" +
          "<tr><th>公钥绑定</th><td>" +
          "等 agent 领取时绑定 · 绑定后每个请求都要 agent 私钥签名，光有钥匙不能用</td></tr>" +
          "</table>" +
          "<p>agent 用配对码领取时会一次拿到身份钥匙和钱钥匙，本页不显示密钥。</p>"
      );
      setStatus(status, "已交付，等 agent 领取");
    } catch (e) {
      setStatus(status, e && e.message ? e.message : String(e), true);
    } finally {
      state.busy = false;
    }
  }

  /* ---------------------------------------------------------------- 初始化 */

  function prefillFromUrl() {
    var code = "";
    try {
      var q = new URLSearchParams(global.location.search || "");
      code = q.get("pair") || "";
      if (!code && (global.location.hash || "").indexOf("pair=") !== -1) {
        code = new URLSearchParams(global.location.hash.slice(1)).get("pair") || "";
      }
    } catch (_) {}
    if (code && byId("pair-code")) {
      byId("pair-code").value = code;
      state.autoLookup = true;
      query();
    }
  }

  function init() {
    if (!byId("ag-pair")) return;
    var q = byId("pair-query");
    if (q) q.addEventListener("click", query);
    var a = byId("pair-approve");
    if (a) a.addEventListener("click", approve);
    var r = byId("pair-reject");
    if (r) r.addEventListener("click", reject);
    var g = byId("pair-grant-go");
    if (g) g.addEventListener("click", grant);
    var codeInput = byId("pair-code");
    if (codeInput) {
      codeInput.addEventListener("keydown", function (ev) {
        if (ev.key === "Enter") query();
      });
    }
    // 方向决定要不要填硬指标，行业决定填哪一份 —— 两个变了都得重渲染。
    ["pair-side", "pair-vertical"].forEach(function (id) {
      var el = byId(id);
      if (el) el.addEventListener("change", renderPairSpec);
    });
    ["karma-wallet-connected", "karma-session-restored"].forEach(function (name) {
      document.addEventListener(name, function () {
        loadProfiles();
        // 从 ?pair= 链接进来的：钱包会话通常比首次查询晚一步，补一次。
        if (state.autoLookup && !state.view) {
          state.autoLookup = false;
          query();
        }
      });
    });
    loadIndustries();
    loadProfiles();
    prefillFromUrl();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  global.KarmaPairing = { reload: query, state: state };
})(window);
