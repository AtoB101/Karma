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
      out('#st-out', (e && (e.message || e.detail)) || e, true);
    }
  }

  /* ---------------- 回执 / 账单 / 争议 / 身份 / 设置 ---------------- */
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }

  function listReceipts() {
    var tid = val('#rc-taskid'); var a = api();
    if (!a) return;
    if (!tid) { out('#rc-out', '请填 Task ID', true); return; }
    out('#rc-out', '查询中…', false);
    a.listReceiptsForTask(tid).then(function (r) { out('#rc-out', r, false); })
      .catch(function (e) { out('#rc-out', (e && (e.message || e.detail)) || e, true); });
  }

  function refreshBills() {
    var id = identity(); var a = api();
    if (!a) return;
    if (!id) return;
    a.getCapacity(id).then(function (c) {
      function set(k, v) { var n = document.querySelector('[data-bind=' + k + ']'); if (n) n.textContent = (v == null || isNaN(Number(v))) ? '—' : Number(v).toFixed(2); }
      set('b_total_locked', c.total_locked_usdc);
      set('b_available', c.available_credits);
      set('b_in_progress', (c.in_progress_credits || 0) + (c.reserved_credits || 0));
      set('b_pending', c.pending_settlement_credits);
      set('b_disputed', c.disputed_credits);
      set('b_released', c.released_credits);
    }).catch(function () {});
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

  function buildCreateKeyMsg(f) {
    var perms = (f.permissions || []).slice().sort().join(',');
    return ['Karma Runtime Key Create', 'karma_identity_id:' + f.karma_identity_id, 'wallet_address:' + f.wallet_address,
      'permissions:' + perms, 'single_limit:' + f.single_limit, 'daily_limit:' + f.daily_limit, 'expire_time:' + f.expire_time,
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
    if (!f.id) { out('#ag-out', '请填 Identity ID 或先连接钱包', true); return; }
    a.putAutomationPolicy(f.id, { auto_enabled: true, single_limit: f.single, daily_limit: f.daily, permissions: f.perms, high_risk_mode: 'always', responsibility_acknowledged: true, preauth_enabled: false, allowed_task_types: [], trusted_counterparty_ids: [], payment_code_ttl_seconds: 3600, auto_accept_incoming: false, auto_execute_pipeline: false, human_not_present_allowed: false })
      .then(function (r) { out('#ag-out', r, false); }).catch(function (e) { out('#ag-out', (e && (e.message || e.detail)) || e, true); });
  }
  function getPolicy() {
    var f = agFields(); var a = api();
    if (!a) return;
    if (!f.id) { out('#ag-out', '请填 Identity ID 或先连接钱包', true); return; }
    a.getAutomationPolicy(f.id).then(function (r) { out('#ag-out', r, false); }).catch(function (e) { out('#ag-out', (e && (e.message || e.detail)) || e, true); });
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
    if (!f.id) { out('#ag-out', '请填 Identity ID 或先连接钱包', true); return; }
    if (!global.ethereum || !global.ethereum.request) { out('#ag-out', '需先连接钱包（MetaMask）', true); return; }
    try {
      var accounts = await global.ethereum.request({ method: 'eth_requestAccounts' });
      var wallet = accounts[0];
      var expireIso = new Date(Date.now() + 7 * 86400e3).toISOString();
      var msg = buildCreateKeyMsg({ karma_identity_id: f.id, wallet_address: wallet, permissions: f.perms, single_limit: f.single, daily_limit: f.daily, expire_time: expireIso, agent_name: 'console-agent' });
      var sig = await global.ethereum.request({ method: 'personal_sign', params: [msg, wallet] });
      var rt = global.karmaRuntimeApi;
      var r = await rt.runtimeCreateKey({ wallet_address: wallet, karma_identity_id: f.id, wallet_signature: sig, permissions: f.perms, single_limit: f.single, daily_limit: f.daily, expire_time: expireIso, agent_name: 'console-agent', profile_id: activeProfileId() || undefined });
      out('#ag-out', r, false);
    } catch (e) { out('#ag-out', (e && (e.message || e.detail)) || e, true); }
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
    var ds = $('#btn-dp-status'); if (ds) ds.addEventListener('click', disputeStatus);
    var dt = $('#btn-dp-transitions'); if (dt) dt.addEventListener('click', disputeTransitions);
    var do_ = $('#btn-dp-open'); if (do_) do_.addEventListener('click', openDispute);
    var ic = $('#btn-id-card'); if (ic) ic.addEventListener('click', loadIdCard);
    var as_ = $('#btn-ag-save'); if (as_) as_.addEventListener('click', savePolicy);
    var ag_ = $('#btn-ag-get'); if (ag_) ag_.addEventListener('click', getPolicy);
    var am = $('#btn-ag-mint'); if (am) am.addEventListener('click', function () { mintKey(); });
  });
})(window);
