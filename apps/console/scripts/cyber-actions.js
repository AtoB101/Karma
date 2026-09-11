/**
 * Cyber console — 真实业务动作（付款码 + 结算流转）。
 * 依赖 karma-public-api.js 暴露的 window.cyberKarmaApi。
 */
(function (global) {
  function api() {
    return global.cyberKarmaApi;
  }
  function $(sel) {
    return document.querySelector(sel);
  }
  function val(sel) {
    return ($(sel) && $(sel).value || '').trim();
  }
  function out(sel, text, isErr) {
    var n = $(sel);
    if (!n) return;
    n.textContent = text == null ? '' : (typeof text === 'string' ? text : JSON.stringify(text, null, 2));
    n.style.color = isErr ? '#f87171' : '#e6ecf5';
  }
  function identity() {
    return val('[data-cfg=identity_id]') || (global.KARMA_IDENTITY_ID || '');
  }
  function sha256hex(s) {
    return crypto.subtle.digest('SHA-256', new TextEncoder().encode(s)).then(function (h) {
      return Array.from(new Uint8Array(h)).map(function (b) { return b.toString(16).padStart(2, '0'); }).join('');
    });
  }

  /* ---------------- 付款码（收付中心） ---------------- */
  async function createPayCode() {
    var buyer = identity();
    var seller = val('#pc-seller');
    var amount = parseFloat(val('#pc-amount'));
    var taskType = val('#pc-tasktype') || 'api.caption';
    var a = api();
    if (!a) { out('#pc-out', 'API 客户端未加载', true); return; }
    if (!buyer) { out('#pc-out', '请先填顶部 Identity 或连接钱包', true); return; }
    if (!seller) { out('#pc-out', '请填卖方 Identity', true); return; }
    if (!amount || amount <= 0) { out('#pc-out', '金额无效', true); return; }

    // 签名：钱包 personal_sign（dev legacy 模式不强制 EIP-712；生产走 EIP-712）
    var sig = '0xconsole_legacy';
    try {
      if (global.ethereum && global.ethereum.request) {
        var accounts = await global.ethereum.request({ method: 'eth_requestAccounts' });
        var msg = 'Karma Payment Code\nbuyer:' + buyer + '\nseller:' + seller + '\namount:' + amount;
        sig = await global.ethereum.request({ method: 'personal_sign', params: [msg, accounts[0]] });
      }
    } catch (_) {}

    out('#pc-out', '创建中…', false);
    try {
      var body = {
        buyer_identity_id: buyer,
        seller_identity_id: seller,
        amount: amount,
        currency: 'USDC',
        bill_credit_amount: amount,
        task_type: taskType,
        task_description_hash: await sha256hex(taskType + ':' + amount),
        progress_rule_hash: await sha256hex('progress'),
        evidence_requirement_hash: await sha256hex('evidence'),
        buyer_signature: sig,
        payment_mode: 'manual'
      };
      var r = await a.createPaymentCode(body);
      out('#pc-out', r, false);
      if (r && r.voucher && r.voucher.voucher_id) {
        var v = $('#pc-voucher'); if (v) v.value = r.voucher.voucher_id;
      }
    } catch (e) {
      out('#pc-out', (e && (e.message || e.detail)) || e, true);
    }
  }

  function readPayCode() {
    var vid = val('#pc-voucher'); var a = api();
    if (!a) return;
    if (!vid) { out('#pc-recv-out', '请填 Voucher ID', true); return; }
    a.getPaymentCode(vid).then(function (r) { out('#pc-recv-out', r, false); })
      .catch(function (e) { out('#pc-recv-out', (e && (e.message || e.detail)) || e, true); });
  }
  function acceptPayCode() {
    var vid = val('#pc-voucher'); var seller = val('#pc-seller-id'); var a = api();
    if (!a) return;
    if (!vid || !seller) { out('#pc-recv-out', '请填 Voucher ID 和卖方 Identity', true); return; }
    a.acceptPaymentCode(vid, seller).then(function (r) { out('#pc-recv-out', r, false); })
      .catch(function (e) { out('#pc-recv-out', (e && (e.message || e.detail)) || e, true); });
  }
  function rejectPayCode() {
    var vid = val('#pc-voucher'); var seller = val('#pc-seller-id'); var a = api();
    if (!a) return;
    if (!vid || !seller) { out('#pc-recv-out', '请填 Voucher ID 和卖方 Identity', true); return; }
    a.rejectPaymentCode(vid, seller, 'console reject').then(function (r) { out('#pc-recv-out', r, false); })
      .catch(function (e) { out('#pc-recv-out', (e && (e.message || e.detail)) || e, true); });
  }

  /* ---------------- 结算流转（任务执行） ---------------- */
  async function settleStep(step) {
    var tid = val('#st-taskid');
    var buyer = val('#st-buyer');
    var worker = val('#st-worker');
    var amount = parseFloat(val('#st-amount')) || 0;
    var a = api();
    if (!a) { out('#st-out', 'API 客户端未加载', true); return; }
    if (!tid) { out('#st-out', '请填 Task ID', true); return; }
    var me = identity();
    /* Each transition is bound to one economic party; the API answers a bare 403
     * when the signed-in identity is not it, so say which identity is required. */
    var party = {
      contract: [buyer, '买方（client_agent_id）'],
      create: [buyer, '买方（client_agent_id）'],
      pending: [buyer, '买方（client_agent_id）'],
      lock: [buyer, '买方（client_agent_id）'],
      start: [worker, '被指派的卖方（worker_agent_id）'],
      submit: [worker, '被指派的卖方（worker_agent_id）'],
      'buyer-accept': [buyer, '买方（client_agent_id）'],
    }[step];
    if (party && party[0] && me && party[0] !== me) {
      out('#st-out', '该步骤只能由' + party[1] + '执行：' + party[0] +
        '\n当前登录身份：' + me + '\n请用对应身份登录后再操作。', true);
      return;
    }
    try {
      var r;
      if (step === 'contract') {
        if (!buyer) { out('#st-out', '请填买方', true); return; }
        var deadline = new Date(Date.now() + 3 * 86400e3).toISOString();
        r = await a.jsonPost('/v1/contracts', {
          task_id: tid, client_agent_id: buyer, title: 'console task', description: '',
          expected_output_schema: { type: 'object' }, expected_step_count: 1,
          escrow_amount: amount, currency: 'USDC', deadline_at: deadline
        });
      } else if (step === 'create') {
        if (!buyer) { out('#st-out', '请填买方', true); return; }
        r = await a.createSettlement({ task_id: tid, client_agent_id: buyer, escrow_amount: amount, currency: 'USDC' });
      } else if (step === 'lock') {
        if (!worker) { out('#st-out', '请填卖方 worker', true); return; }
        r = await a.settlementLock(tid, worker);
      } else if (step === 'pending') {
        r = await a.settlementPending(tid);
      } else if (step === 'start') {
        r = await a.settlementStart(tid);
      } else if (step === 'submit') {
        r = await a.settlementSubmit(tid);
      } else if (step === 'buyer-accept') {
        r = await a.settlementBuyerAccept(tid);
      } else if (step === 'dispute') {
        r = await a.settlementDispute(tid, 'console dispute');
      } else {
        out('#st-out', '未知步骤', true); return;
      }
      out('#st-out', r, false);
    } catch (e) {
      var msg = (e && (e.message || e.detail)) || e;
      if (typeof msg === 'string') {
        if (msg.indexOf('only the assigned worker') >= 0) msg = '该步骤只能由被指派的卖方执行（403）';
        else if (msg.indexOf('only the settlement buyer') >= 0) msg = '该步骤只能由买方执行（403）';
        else if (msg.indexOf('buyer or assigned worker') >= 0) msg = '该步骤只能由买方或被指派的卖方执行（403）';
        else if (msg.indexOf('successful execution receipt is required') >= 0) {
          msg = '结算被拦住：这条任务还没有「成功的执行回执」。\n' +
            '执行回执必须由卖方 agent 用它自己的运行密钥（Ed25519）签名后提交到 /v1/receipts，' +
            'Karma 会校验签名与哈希，操作台只能查询、不能代签。\n' +
            '先让卖方 agent 提交回执（本页「回执证明」可查到），再回到这里批准结算。';
        }
      }
      out('#st-out', msg, true);
    }
  }

  /* ---------------- 回执 / 账单 / 争议 / 身份 / 设置 ---------------- */
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }

  function listReceipts() {
    var tid = val('#rc-taskid'); var a = api();
    if (!a) return;
    if (!tid) { out('#rc-out', '请填 Task ID', true); return; }
    out('#rc-out', '查询中…', false);
    // 回执按子身份隔离：任务归属其它子身份时不出数据，只说明原因，避免串账。
    var pid = activeProfileId();
    var guard = pid && a.getSettlement
      ? a.getSettlement(tid).then(function (s) {
          if (s && s.profile_id && s.profile_id !== pid) {
            return '当前视角是子身份 ' + String(pid).slice(0, 12) + '…，该任务属于 ' + String(s.profile_id).slice(0, 12) + '…。切回「主体（全部）」可查看全部回执。';
          }
          return null;
        }).catch(function () { return null; })
      : Promise.resolve(null);
    return guard.then(function (blocked) {
      if (blocked) { out('#rc-out', blocked, true); return; }
      a.listReceiptsForTask(tid).then(function (r) { out('#rc-out', r, false); })
        .catch(function (e) { out('#rc-out', (e && (e.message || e.detail)) || e, true); });
    });
  }

  /* ---- 账单：主身份总账 ↔ 子身份明细 ----
   *
   * The capacity row is the master anchor; profile_capacity splits it per role
   * profile and settlements carry profile_id, so an owner can see one sub-identity's
   * money without losing the fact that everything rolls up to one identity card.
   */

  var BILL_PROFILES = [];

  function billSet(k, v) {
    var n = document.querySelector('[data-bind=' + k + ']');
    if (n) n.textContent = (v == null || isNaN(Number(v))) ? '—' : Number(v).toFixed(2);
  }

  function billNum(v) {
    var n = Number(v);
    return isNaN(n) ? 0 : n;
  }

  function billEsc(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function billProfileLabel(p) {
    return (p.display_name || p.profile_id) + ' · ' + (p['class'] || '') + (p.visibility === 'private' ? ' 🔒' : '');
  }

  function billScope() {
    var sel = $('#bill-scope');
    return sel ? sel.value : '';
  }

  async function loadBillProfiles() {
    var sel = $('#bill-scope');
    var id = identity();
    if (!sel || !id) return [];
    try {
      var body = await api().listRoleProfiles(id);
      BILL_PROFILES = (body && body.profiles) || [];
    } catch (_) {
      BILL_PROFILES = [];
    }
    var keep = sel.value || activeProfileId();
    sel.innerHTML = '<option value="">全部（主身份总账）</option>';
    BILL_PROFILES.forEach(function (p) {
      var o = document.createElement('option');
      o.value = p.profile_id;
      o.textContent = billProfileLabel(p);
      sel.appendChild(o);
    });
    if (keep) sel.value = keep;
    if (keep && sel.value !== keep) {
      // The stored scope no longer exists (profile deleted / another account):
      // fall back to the master view instead of showing a phantom filter.
      if (window.KarmaIdentitySwitcher && window.KarmaIdentitySwitcher.setActiveProfileId) {
        window.KarmaIdentitySwitcher.setActiveProfileId('');
      }
      sel.value = '';
    }
    return BILL_PROFILES;
  }

  function allocationFor(allocations, profileId) {
    for (var i = 0; i < allocations.length; i++) {
      if (allocations[i] && allocations[i].profile_id === profileId) return allocations[i];
    }
    return null;
  }

  function ledgerTable(rows) {
    if (!rows.length) return '<p class="ag-hint">该子身份还没有收付记录。</p>';
    var head = '<tr><th>Task</th><th>金额</th><th>状态</th><th>付款方 agent</th><th>收款方 agent</th><th>已放款</th><th>已退款</th><th>时间</th></tr>';
    var body = rows
      .map(function (t) {
        return (
          '<tr><td><code>' + billEsc(t.task_id) + '</code></td>' +
          '<td>' + billEsc(t.currency || '') + ' ' + billEsc(billNum(t.escrow_amount).toFixed(2)) + '</td>' +
          '<td>' + billEsc(t.status) + '</td>' +
          '<td>' + billEsc(t.client_agent_id || '—') + '</td>' +
          '<td>' + billEsc(t.worker_agent_id || '—') + '</td>' +
          '<td>' + (t.released_amount == null ? '—' : billEsc(billNum(t.released_amount).toFixed(2))) + '</td>' +
          '<td>' + (t.refunded_amount == null ? '—' : billEsc(billNum(t.refunded_amount).toFixed(2))) + '</td>' +
          '<td>' + billEsc(String(t.created_at || '').slice(0, 19).replace('T', ' ')) + '</td></tr>'
        );
      })
      .join('');
    return '<table><thead>' + head + '</thead><tbody>' + body + '</tbody></table>';
  }

  async function refreshBills() {
    var id = identity(); var a = api();
    var host = $('#bill-ledger');
    if (!a || !id) {
      if (host) host.innerHTML = '<p class="ag-hint">请先连接钱包完成认证。</p>';
      return;
    }
    var scope = billScope();
    if (host) host.innerHTML = '<p class="ag-hint">读取中…</p>';

    var profiles = BILL_PROFILES.length ? BILL_PROFILES : await loadBillProfiles();
    var allocations = [];
    try {
      var allocBody = await a.getAllocations(id);
      allocations = (allocBody && allocBody.allocations) || [];
    } catch (_) {}
    var cap = null;
    try { cap = await a.getCapacity(id); } catch (_) {}

    var hint = $('#bill-scope-hint');
    if (hint) {
      hint.textContent = scope
        ? '子身份明细 · 主体身份卡 ' + id + '（本视角只统计该子身份的收付）'
        : '主体身份卡 ' + id + ' —— 所有子身份的记录都汇总到这张卡，各子身份明细互不混淆。';
    }

    // 释放额度是主体身份卡的操作（服务端只动 master 台账，不碰子身份额度分配），
    // 所以在子身份视角下关掉按钮，并指向真正能下调子身份额度的入口。
    var relBtn = $('#btn-release-capacity');
    var relInput = $('#release-amount');
    var relHint = $('#release-status');
    if (relBtn && relInput) {
      relBtn.disabled = !!scope;
      relInput.disabled = !!scope;
      if (relHint) {
        relHint.textContent = scope
          ? '当前视角是子身份 ' + String(scope).slice(0, 12) + '…：释放额度属于主体身份卡，请先在顶部切回「主体（全部）」；子身份的额度请到「身份」页 →「额度分配」下调。'
          : '只能释放未被任务占用的可用额度（台账 1:1 锚定，不涉及链上转账）。';
        relHint.classList.toggle('err', !!scope);
      }
    }

    if (!scope) {
      if (cap) {
        billSet('b_total_locked', cap.total_locked_usdc);
        billSet('b_available', cap.available_credits);
        billSet('b_in_progress', billNum(cap.in_progress_credits) + billNum(cap.reserved_credits));
        billSet('b_pending', cap.pending_settlement_credits);
        billSet('b_disputed', cap.disputed_credits);
        billSet('b_released', cap.released_credits);
      }
      if (!host) return;
      if (!profiles.length) {
        host.innerHTML = '<p class="ag-hint">还没有子身份档案。到「身份」页创建档案后，这里会按子身份拆开显示。</p>';
        return;
      }
      var rows = [];
      for (var i = 0; i < profiles.length; i++) {
        var p = profiles[i];
        var alloc = allocationFor(allocations, p.profile_id);
        var txCount = 0;
        try {
          var led = await a.getProfileLedger(p.profile_id);
          txCount = ((led && led.transactions) || []).length;
        } catch (_) {}
        rows.push(
          '<tr><td>' + billEsc(p.display_name || p.profile_id) + '<br><code style="font-size:11px">' + billEsc(p.profile_id) + '</code></td>' +
          '<td>' + billEsc(p['class'] || '—') + '</td>' +
          '<td>' + (alloc ? billNum(alloc.allocated_credits).toFixed(2) : '未分配') + '</td>' +
          '<td>' + (alloc ? billNum(alloc.available_credits).toFixed(2) : '—') + '</td>' +
          '<td>' + (alloc ? billNum(alloc.in_progress_credits).toFixed(2) : '—') + '</td>' +
          '<td>' + (alloc ? billNum(alloc.pending_settlement_credits).toFixed(2) : '—') + '</td>' +
          '<td>' + (alloc ? billNum(alloc.disputed_credits).toFixed(2) : '—') + '</td>' +
          '<td>' + txCount + '</td></tr>'
        );
      }
      host.innerHTML =
        '<table><thead><tr><th>子身份</th><th>类别</th><th>已分配</th><th>可用</th><th>执行占用</th><th>待结算</th><th>争议冻结</th><th>收付笔数</th></tr></thead><tbody>' +
        rows.join('') + '</tbody></table>';
      return;
    }

    var alloc = allocationFor(allocations, scope);
    if (alloc) {
      billSet('b_total_locked', alloc.allocated_credits);
      billSet('b_available', alloc.available_credits);
      billSet('b_in_progress', alloc.in_progress_credits);
      billSet('b_pending', alloc.pending_settlement_credits);
      billSet('b_disputed', alloc.disputed_credits);
      billSet('b_released', alloc.released_credits);
    } else if (cap) {
      billSet('b_total_locked', 0);
      billSet('b_available', 0);
      billSet('b_in_progress', 0);
      billSet('b_pending', 0);
      billSet('b_disputed', 0);
      billSet('b_released', 0);
    }
    if (!host) return;
    try {
      var led = await a.getProfileLedger(scope);
      var note = alloc ? '' : '<p class="ag-hint">该子身份还没有分配额度（到「身份」页 → 额度分配）。</p>';
      host.innerHTML = note + ledgerTable((led && led.transactions) || []);
    } catch (e) {
      host.innerHTML = '<p class="err">读取失败：' + billEsc(e.message || e) + '</p>';
    }
  }

  function disputeStatus() {
    var tid = val('#dp-taskid'); var a = api();
    if (!a) return;
    if (!tid) { out('#dp-out', '请填 Task ID', true); return; }
    a.getSettlement(tid).then(function (r) { out('#dp-out', r, false); }).catch(function (e) { out('#dp-out', (e && (e.message || e.detail)) || e, true); });
  }
  function disputeTransitions() {
    var tid = val('#dp-taskid'); var a = api();
    if (!a) return;
    if (!tid) { out('#dp-out', '请填 Task ID', true); return; }
    a.listSettlementTransitions(tid).then(function (r) { out('#dp-out', r, false); }).catch(function (e) { out('#dp-out', (e && (e.message || e.detail)) || e, true); });
  }
  function openDispute() {
    var tid = val('#dp-taskid'); var reason = val('#dp-reason') || 'console dispute'; var a = api();
    if (!a) return;
    if (!tid) { out('#dp-out', '请填 Task ID', true); return; }
    a.settlementDispute(tid, reason).then(function (r) { out('#dp-out', r, false); }).catch(function (e) { out('#dp-out', (e && (e.message || e.detail)) || e, true); });
  }

  function loadIdCard() {
    var id = val('#id-card-id') || identity(); var a = api();
    if (!a) return;
    if (!id) { out('#id-out', '请填 Identity ID 或先连接钱包', true); return; }
    a.karmaFetch('/v1/identity/' + encodeURIComponent(id) + '/card?scope=basic', { method: 'GET', headers: a.headers() }).then(function (card) {
      out('#id-out', card, false);
      var v = $('#id-card-view');
      if (v) {
        v.style.display = 'block';
        v.innerHTML = '<div style="font-size:1.2rem;font-weight:700">' + esc(card.display_id || card.identity_id || '—') + '</div>' +
          '<div style="font-family:monospace;font-size:0.8rem;color:var(--text-dim);margin-top:6px;word-break:break-all">' + esc(card.identity_id || '') + '</div>' +
          '<div style="display:flex;gap:18px;flex-wrap:wrap;margin-top:14px">' +
          '<div><b style="color:var(--text-dim);font-size:0.7rem;text-transform:uppercase">Identity Class</b><div style="font-family:monospace">' + esc(card.identity_class || '—') + '</div></div>' +
          '<div><b style="color:var(--text-dim);font-size:0.7rem;text-transform:uppercase">Verification</b><div style="font-family:monospace">' + esc(card.verification_status || '—') + '</div></div>' +
          '<div><b style="color:var(--text-dim);font-size:0.7rem;text-transform:uppercase">Status</b><div style="font-family:monospace">' + esc(card.status || '—') + '</div></div>' +
          '</div>';
      }
    }).catch(function (e) { out('#id-out', (e && (e.message || e.detail)) || e, true); });
  }

  /* The server rebuilds the signed string from the parsed request, so the client
   * must reproduce Python's formatting exactly: str(float) for the limits and
   * datetime.isoformat() for an aware UTC timestamp. Signing a JS Date.toISOString()
   * ('…123Z') or a bare '100' recovered a different signer and always 403'd. */
  function pyFloatStr(n) {
    var v = Number(n);
    if (!isFinite(v)) return String(n);
    return Number.isInteger(v) ? v.toFixed(1) : String(v);
  }

  function pyUtcIso(ms) {
    var iso = new Date(ms).toISOString(); // 2026-09-18T10:35:00.123Z
    var m = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,3}))?Z$/.exec(iso);
    if (!m) return iso;
    var frac = (m[2] || '').padEnd(6, '0');
    // Python omits the fraction entirely when it is zero.
    return frac === '000000' ? m[1] + '+00:00' : m[1] + '.' + frac + '+00:00';
  }

  function buildCreateKeyMsg(f) {
    var perms = (f.permissions || []).slice().sort().join(',');
    return ['Karma Runtime Key Create', 'karma_identity_id:' + f.karma_identity_id, 'wallet_address:' + f.wallet_address,
      'permissions:' + perms, 'single_limit:' + pyFloatStr(f.single_limit), 'daily_limit:' + pyFloatStr(f.daily_limit),
      'expire_time:' + f.expire_time,
      'agent_name:' + (f.agent_name || 'console-agent'), 'agent_binding:' + (f.agent_binding || '')].join('\n');
  }
  function agFields() {
    var id = val('#ag-identity') || identity();
    var perms = (val('#ag-perms') || '').split(',').map(function (s) { return s.trim(); }).filter(Boolean);
    return { id: id, perms: perms, single: parseFloat(val('#ag-single')) || 0, daily: parseFloat(val('#ag-daily')) || 0 };
  }
  function savePolicy() {
    var f = agFields(); var a = api();
    if (!a) return;
    if (!f.id) { out('#set-out', '请填 Identity ID 或先连接钱包', true); return; }
    a.putAutomationPolicy(f.id, { auto_enabled: true, single_limit: f.single, daily_limit: f.daily, permissions: f.perms, high_risk_mode: 'always', responsibility_acknowledged: true, preauth_enabled: false, allowed_task_types: [], trusted_counterparty_ids: [], payment_code_ttl_seconds: 3600, auto_accept_incoming: false, auto_execute_pipeline: false, human_not_present_allowed: false })
      .then(function (r) { out('#set-out', r, false); }).catch(function (e) { out('#set-out', (e && (e.message || e.detail)) || e, true); });
  }
  function getPolicy() {
    var f = agFields(); var a = api();
    if (!a) return;
    if (!f.id) { out('#set-out', '请填 Identity ID 或先连接钱包', true); return; }
    a.getAutomationPolicy(f.id).then(function (r) { out('#set-out', r, false); }).catch(function (e) { out('#set-out', (e && (e.message || e.detail)) || e, true); });
  }
  function activeProfileId() {
    try {
      if (window.KarmaIdentitySwitcher && window.KarmaIdentitySwitcher.getActiveProfileId) {
        var p = window.KarmaIdentitySwitcher.getActiveProfileId();
        if (p) return p;
      }
      return sessionStorage.getItem('karma_console_active_profile') || '';
    } catch (_) { return ''; }
  }
  async function mintKey() {
    var f = agFields(); var a = api();
    if (!a) return;
    if (!f.id) { out('#set-out', '请填 Identity ID 或先连接钱包', true); return; }
    var provider =
      (global.KarmaWalletAuth && global.KarmaWalletAuth.activeProvider && global.KarmaWalletAuth.activeProvider()) ||
      global.ethereum;
    if (!provider || !provider.request) {
      out('#set-out', '未检测到可用钱包，请先用页面右上角「连接钱包」完成认证', true);
      return;
    }
    try {
      var accounts = await provider.request({ method: 'eth_requestAccounts' });
      var wallet = accounts[0];
      var expireIso = pyUtcIso(Date.now() + 7 * 86400e3);
      var msg = buildCreateKeyMsg({ karma_identity_id: f.id, wallet_address: wallet, permissions: f.perms, single_limit: f.single, daily_limit: f.daily, expire_time: expireIso, agent_name: 'console-agent' });
      var sig = await provider.request({ method: 'personal_sign', params: [msg, wallet] });
      var rt = global.karmaRuntimeApi;
      var r = await rt.runtimeCreateKey({ wallet_address: wallet, karma_identity_id: f.id, wallet_signature: sig, permissions: f.perms, single_limit: f.single, daily_limit: f.daily, expire_time: expireIso, agent_name: 'console-agent', profile_id: activeProfileId() || undefined });
      out('#set-out', r, false);
    } catch (e) { out('#set-out', (e && (e.message || e.detail)) || e, true); }
  }

  document.addEventListener('DOMContentLoaded', function () {
    var c = $('#btn-create-paycode');
    if (c) c.addEventListener('click', function () { createPayCode(); });
    var rd = $('#btn-read-paycode');
    if (rd) rd.addEventListener('click', readPayCode);
    var ac = $('#btn-accept-paycode');
    if (ac) ac.addEventListener('click', acceptPayCode);
    var rj = $('#btn-reject-paycode');
    if (rj) rj.addEventListener('click', rejectPayCode);

    document.querySelectorAll('[data-st-step]').forEach(function (btn) {
      btn.addEventListener('click', function () { settleStep(btn.getAttribute('data-st-step')); });
    });

    var lr = $('#btn-list-receipts'); if (lr) lr.addEventListener('click', listReceipts);
    var rb = $('#btn-refresh-bills'); if (rb) rb.addEventListener('click', refreshBills);
    var bs = $('#bill-scope');
    if (bs) bs.addEventListener('change', function () {
      // 统一入口：账单视角就是全站子身份视角，切一次两边都跟着动。
      var sw = window.KarmaIdentitySwitcher;
      if (sw && sw.setActiveProfileId) { sw.setActiveProfileId(bs.value); return; }
      refreshBills();
    });
    document.addEventListener('karma-page-shown', function (ev) {
      var page = ev && ev.detail && ev.detail.page;
      if (page !== 'bills') return;
      loadBillProfiles().then(refreshBills).catch(function () {});
    });
    document.addEventListener('karma-wallet-connected', function () {
      loadBillProfiles().then(refreshBills).catch(function () {});
    });
    document.addEventListener('karma-profile-switched', function () {
      loadBillProfiles().then(refreshBills).catch(function () {});
    });
    var ds = $('#btn-dp-status'); if (ds) ds.addEventListener('click', disputeStatus);
    var dt = $('#btn-dp-transitions'); if (dt) dt.addEventListener('click', disputeTransitions);
    var do_ = $('#btn-dp-open'); if (do_) do_.addEventListener('click', openDispute);
    var ic = $('#btn-id-card'); if (ic) ic.addEventListener('click', loadIdCard);
    var as_ = $('#btn-ag-save'); if (as_) as_.addEventListener('click', savePolicy);
    var ag_ = $('#btn-ag-get'); if (ag_) ag_.addEventListener('click', getPolicy);
    var am = $('#btn-ag-mint'); if (am) am.addEventListener('click', function () { mintKey(); });
  });
})(window);
