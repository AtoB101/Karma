/**
 * Karma Console — 单笔订单状态图（动态）
 *
 * 点订单图里的一张单，这里展开这一单的完整状态图：
 * 订单号 / 交易对方 / 对方信息 / 创建时间 / 合同详情（点击查看），
 * 下面是这笔生意专属的阶段线 —— 走到哪一步，哪一步亮蓝灯。
 *
 * 三条规矩：
 *   1. 一条线只属于一种生意。阶段表按「服务类型（scene）」选，不是所有单共用一张图。
 *      服务类型来自后端 progress_rule_spec.scene_id / task_type；认不出就用通用兜底。
 *   2. 每个阶段亮不亮只看真实字段：后端状态机、流转历史（settlement_transition_audits）、
 *      交付验证事件（delivery-verification）。没依据的阶段就是没亮，不猜、不编。
 *   3. 只读。不写库、不碰私钥、不需要额外签名。
 */
(function (global) {
  "use strict";

  var HOST = "order-flow";

  /* ------------------------------------------------------------------ 文案表
   * 交付验证标准里的里程碑事件 -> 中文阶段名。
   * 事件名的出处：packages/evidence-schema/delivery-verification.v1.json 的
   * scenes[*].required_events。新增事件忘了配文案时兜底成「验证凭证」，不会渲染出英文。
   */
  var EVENT_STAGE = {
    execution_receipt_success: { label: "执行回执成功", hint: "卖方提交执行回执且判定成功" },
    proof_fields_covered: { label: "凭证字段齐备", hint: "验收要求的字段全部覆盖" },
    seller_shipped: { label: "卖家已发货", hint: "卖家提交发货凭证" },
    logistics_intake_ok: { label: "物流已揽收", hint: "承运方验收入库" },
    logistics_delivered: { label: "已送达", hint: "承运方送达并提交凭证" },
    "proof:delivery_photo_tagged": { label: "送达拍照", hint: "带时间戳的送达照片" },
    "proof:customs_declaration": { label: "出口报关", hint: "报关单与箱单哈希" },
    "proof:customs_clearance": { label: "进口清关", hint: "清关放行回执" },
    "proof:recipient_ack_or_silent": { label: "签收确认", hint: "买家确认，或静默期到期默认确认" },
    seller_trip_completed: { label: "行程已完成", hint: "司机端行程结束" },
    "proof:route_or_odometer": { label: "轨迹 / 里程", hint: "路线或里程数据哈希" },
    "proof:fare_final": { label: "车费确认", hint: "最终计费确认" },
    seller_issued_confirmation: { label: "已出确认单", hint: "卖方出具确认号 / 票号" },
    "proof:email_receipt_or_confirmation_code": { label: "确认码凭证", hint: "确认单或确认码" },
    "proof:ticket_number_or_pnr": { label: "票号 / PNR", hint: "票号或订座记录" },
    "proof:email_receipt_ref": { label: "邮件回执", hint: "出票邮件回执" },
    "proof:goods_receipt": { label: "收货单", hint: "收货单凭证" },
    "proof:qa_or_quantity": { label: "质检 / 数量", hint: "质检或数量核对凭证" },
    "proof:qa_report_hash": { label: "质检报告", hint: "质检报告哈希" },
    "proof:deliverable_hash": { label: "交付物哈希", hint: "交付物内容哈希" },
    "proof:service_completion_ref": { label: "服务完成凭证", hint: "服务完成凭据" },
    "proof:attendance_or_completion_ref": { label: "出勤 / 结业凭证", hint: "出勤或结业凭据" },
    "proof:campaign_report_hash": { label: "投放报告", hint: "投放报告哈希" },
    buyer_explicit_accept: { label: "买家显式确认", hint: "高风险场景必须买家本人确认" },
    _default: { label: "验证凭证", hint: "交付验证要求的凭证" },
  };

  /* 服务类型（scene）——和后端交付验证标准逐一对应，别自己加。 */
  var SCENES = {
    food_delivery: { label: "餐饮外卖", mode: "physical_triple", events: ["seller_shipped", "logistics_intake_ok", "logistics_delivered", "proof:delivery_photo_tagged"] },
    cross_border_ecommerce: { label: "跨境电商", mode: "physical_triple", events: ["seller_shipped", "proof:customs_declaration", "logistics_intake_ok", "proof:customs_clearance", "logistics_delivered", "proof:delivery_photo_tagged"] },
    logistics_delivery: { label: "物流 / 配送", mode: "physical_triple", events: ["seller_shipped", "logistics_intake_ok", "logistics_delivered", "proof:delivery_photo_tagged", "proof:recipient_ack_or_silent"] },
    b2b_procurement: { label: "B2B 采购", mode: "physical_triple", events: ["seller_shipped", "logistics_intake_ok", "logistics_delivered", "proof:goods_receipt", "proof:qa_or_quantity"] },
    manufacturing: { label: "生产制造", mode: "physical_triple", events: ["seller_shipped", "logistics_intake_ok", "logistics_delivered", "proof:goods_receipt", "proof:qa_report_hash"] },
    ride_hailing: { label: "出行打车", mode: "ride_track", events: ["seller_trip_completed", "proof:route_or_odometer", "proof:fare_final"] },
    hotel_booking: { label: "酒店预订", mode: "ticket_stub", events: ["seller_issued_confirmation", "proof:email_receipt_or_confirmation_code"] },
    flight_booking: { label: "机票预订", mode: "ticket_stub", events: ["seller_issued_confirmation", "proof:ticket_number_or_pnr", "proof:email_receipt_ref"] },
    data_api_billing: { label: "数据 / API 计费", mode: "digital_light", events: ["execution_receipt_success", "proof_fields_covered"] },
    api_tool_call: { label: "接口 / 工具调用", mode: "digital_light", events: ["execution_receipt_success", "proof_fields_covered"] },
    software_development: { label: "软件开发", mode: "digital_light", events: ["execution_receipt_success", "proof:deliverable_hash", "proof_fields_covered"] },
    design_creative: { label: "设计 / 创意", mode: "digital_light", events: ["execution_receipt_success", "proof:deliverable_hash", "proof_fields_covered"] },
    consulting_advisory: { label: "咨询顾问", mode: "digital_light", events: ["execution_receipt_success", "proof:deliverable_hash"] },
    content_creation: { label: "内容创作", mode: "digital_light", events: ["execution_receipt_success", "proof:deliverable_hash"] },
    real_estate_services: { label: "房产服务", mode: "ticket_stub", events: ["seller_issued_confirmation", "proof:service_completion_ref"] },
    financial_services: { label: "金融服务", mode: "digital_light", events: ["execution_receipt_success", "proof_fields_covered", "buyer_explicit_accept"] },
    healthcare_medical: { label: "医疗健康", mode: "digital_light", events: ["execution_receipt_success", "proof_fields_covered", "buyer_explicit_accept"] },
    marketing_advertising: { label: "营销投放", mode: "digital_light", events: ["execution_receipt_success", "proof:campaign_report_hash"] },
    education_training: { label: "教育培训", mode: "ticket_stub", events: ["seller_issued_confirmation", "proof:attendance_or_completion_ref"] },
  };

  var MODE_LABEL = {
    physical_triple: "实物三段（卖家 → 物流 → 买家）",
    ride_track: "行程轨迹",
    ticket_stub: "票务 / 确认单",
    digital_light: "数字交付",
  };

  /* 认不出服务类型时的通用图：只画后端状态机里一定有的那几步。 */
  var GENERIC = { key: "generic", label: "通用服务", mode: "digital_light", events: [] };

  /* 交付验证会话的真实状态 -> 它落在状态图的哪个位置。 */
  var VERIFY_STATUS = {
    CREATED: "已建交付验证",
    AWAITING_SELLER_SHIP: "等卖家发货",
    AWAITING_LOGISTICS_INTAKE: "等承运方揽收",
    IN_TRANSIT: "在途",
    AWAITING_BUYER_RECEIPT: "等买家签收",
    WRONG_ITEM: "错件 · 待定责",
    VERIFIED: "验证通过",
    BUYER_CONFIRMED: "买家已确认",
    BUYER_SILENT_DEFAULT: "静默期到期 · 默认确认",
    REJECTED: "买家拒收",
  };

  var state = { entry: null, open: false };

  function $(sel, root) { return (root || document).querySelector(sel); }
  function api() { return global.cyberKarmaApi; }

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function money(value) {
    var n = Number(value);
    return (Number.isNaN(n) ? 0 : n).toFixed(2);
  }

  function fmtTime(value) {
    var s = String(value || "");
    if (!s) return "—";
    var d = new Date(s);
    if (Number.isNaN(d.getTime())) return s.slice(0, 16).replace("T", " ");
    var p = function (n) { return (n < 10 ? "0" : "") + n; };
    return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate()) +
      " " + p(d.getHours()) + ":" + p(d.getMinutes());
  }

  /** 身份编号：全站统一走 KarmaDisplayId.remote（kid…+ 后 4 位）。 */
  function shortId(id) {
    if (!id) return "—";
    try {
      if (global.KarmaDisplayId && global.KarmaDisplayId.remote) {
        return global.KarmaDisplayId.remote(id) || "—";
      }
    } catch (_) {}
    var s = String(id);
    return s.length > 22 ? s.slice(0, 12) + "…" + s.slice(-6) : s;
  }

  function sceneOf(entry) {
    var d = (entry && entry.detail) || {};
    var raw = String(d.scene_id || d.task_type || "").trim();
    if (raw && SCENES[raw]) return { key: raw, def: SCENES[raw] };
    return { key: raw || "generic", def: GENERIC };
  }

  /* ----------------------------------------------------------- 阶段表构建 */

  /** 后端状态机里「这一步已经走过」的判定依据 = 流转历史里出现过这个状态。 */
  function makeTracker(entry, history) {
    var seen = {};
    (history || []).forEach(function (h) {
      var s = String((h && h.to_status) || "");
      if (!s) return;
      if (!seen[s]) seen[s] = h.at || "";
    });
    var cur = String((entry && entry.status) || "");
    if (cur && !seen[cur]) seen[cur] = (entry && entry.updated_at) || (entry && entry.created_at) || "";
    return {
      seen: seen,
      /* 命中任一状态就返回它第一次发生的时刻，否则 null。 */
      hit: function (list) {
        for (var i = 0; i < list.length; i++) {
          if (seen[list[i]] !== undefined) return seen[list[i]] || "";
        }
        return null;
      },
      status: cur,
    };
  }

  function step(key, label, hint, at, opts) {
    return {
      key: key, label: label, hint: hint || "", at: at || "",
      done: at !== null && at !== undefined,
      spine: !(opts && opts.milestone),
      strict: !!(opts && opts.strict),
      terminal: !!(opts && opts.terminal),
      warn: !!(opts && opts.warn),
      missing: !!(opts && opts.missing),
    };
  }

  var AFTER_PLACED = ["accepted", "in_progress", "progress_submitted", "progress_confirmed", "delivered", "disputed", "arbitrated", "settled", "partially_settled", "refunded", "auto_confirmed"];
  var AFTER_ACCEPTED = ["in_progress", "progress_submitted", "progress_confirmed", "delivered", "disputed", "arbitrated", "settled", "partially_settled", "refunded", "auto_confirmed"];
  var AFTER_RUNNING = ["progress_submitted", "progress_confirmed", "delivered", "disputed", "arbitrated", "settled", "partially_settled", "refunded", "auto_confirmed"];
  var AFTER_DELIVERED = ["disputed", "arbitrated", "settled", "partially_settled", "refunded"];

  function buildStages(entry, history, verification) {
    var t = makeTracker(entry, history);
    var out = [];
    var scene = sceneOf(entry);
    var kind = String(entry.kind || "");
    var ver = verification || {};
    var events = {};
    (ver.events || []).forEach(function (ev) {
      var k = String((ev && ev.kind) || "");
      if (k && events[k] === undefined) events[k] = ev.at || "";
    });

    if (kind === "voucher") {
      out.push(step("placed", "已下单", "付款授权码已创建，等卖方接单", t.hit(["created"]) || (t.status === "created" ? entry.created_at || "" : null)));
      out.push(step("accepted", "卖家已接单", "卖方接单并锁定授权额度", t.hit(["accepted"])));
      out.push(step("used", "已核销", "授权额度已用于这一单", t.hit(["used"])));
    } else {
      var onchain = kind === "binding";
      out.push(step("placed", onchain ? "已建单" : "已下单",
        onchain ? "链上结算单已绑定" : "合同已建，等卖方接单",
        t.hit(onchain ? ["none"] : ["draft", "pending"]) !== null
          ? t.hit(onchain ? ["none"] : ["draft", "pending"])
          : t.hit(AFTER_PLACED)));
      out.push(step("accepted", "卖家已接单", "卖方接单并锁定责任额度",
        t.hit(["accepted"]) !== null ? t.hit(["accepted"]) : t.hit(AFTER_ACCEPTED)));
      out.push(step("running", "执行中", "卖方的 agent 在干活",
        t.hit(["in_progress"]) !== null ? t.hit(["in_progress"]) : t.hit(AFTER_RUNNING)));

      /* 进度回执：只有这一单真的报过进度才占位置，否则线条越画越长没人看。 */
      if (t.seen.progress_submitted !== undefined || t.seen.progress_confirmed !== undefined) {
        out.push(step("progress_submitted", "进度待确认", "卖方上报进度，等买家确认", t.hit(["progress_submitted"])));
        out.push(step("progress_confirmed", "进度已确认", "买家确认了这一阶段", t.hit(["progress_confirmed"])));
      }

      /* 服务类型专属的交付里程碑：只有交付验证真的报了这件事才亮。 */
      (scene.def.events || []).forEach(function (name) {
        var meta = EVENT_STAGE[name] || EVENT_STAGE._default;
        var at = events[name];
        out.push(step("ev:" + name, meta.label, meta.hint, at === undefined ? null : at, {
          milestone: true,
          missing: at === undefined,
        }));
      });

      out.push(step("delivered", "已交付 · 待确认", "等买家验收，或静默期到期默认确认",
        t.hit(["delivered"]) !== null ? t.hit(["delivered"]) : t.hit(AFTER_DELIVERED)));

      if (ver.status && VERIFY_STATUS[ver.status]) {
        var vDone = ver.status === "VERIFIED" || ver.status === "BUYER_CONFIRMED" || ver.status === "BUYER_SILENT_DEFAULT";
        out.push(step("verification", "交付验证 · " + VERIFY_STATUS[ver.status],
          "P7 交付验证标准在跑", ver.updated_at || (vDone ? ver.verified_at || "" : null)));
      }

      if (kind !== "binding") {
        out.push(step("settled", "已结算", "真钱按验证结果划给卖方", t.hit(["settled"]), { strict: true }));
      }
    }

    /* 走到负面终局：把终局那一步接在最后，标成需要人看一眼。 */
    var negative = {
      disputed: ["争议中", "资金冻结，等仲裁裁决", true],
      arbitrated: ["已仲裁", "仲裁已裁决，按裁决划账", true],
      refunded: ["已退款", "钱退回买方", true],
      cancelled: ["已取消", "这一单没成", true],
      rejected: ["已拒绝", "卖方拒绝了这一单", true],
      expired: ["已过期", "授权码过期未使用", true],
      slashed: ["已罚没", "卖方保证金被罚没", true],
      failed: ["已失败", "这一单失败收场", true],
      WRONG_ITEM: ["错件", "中途发现错件，按责任比例分担", true],
      REJECTED: ["买家拒收", "买家拒收，按责任比例分担", true],
    };
    var negKey = t.status;
    if (kind === "binding" && t.status === "slashed") negKey = "slashed";
    if (negative[negKey]) {
      var row = negative[negKey];
      out.push(step("terminal:" + negKey, row[0], row[1], (t.hit([negKey]) !== null ? t.hit([negKey]) : entry.updated_at || entry.created_at || ""), {
        terminal: true, warn: true,
      }));
    }
    return { stages: out, scene: scene };
  }

  /** 主线阶段可以从「后面已经走过」反推成已完成；里程碑不行——没报就是没报。 */
  function markProgress(stages) {
    var lastDone = -1;
    stages.forEach(function (s, i) { if (s.done) lastDone = i; });
    stages.forEach(function (s, i) {
      if (!s.done && s.spine && !s.terminal && !s.strict && i < lastDone) s.done = true;
      s.state = s.done ? (i === lastDone ? "live" : "done") : (i < lastDone ? "skip" : "todo");
      if (s.warn && s.done) s.state = "warn";
    });
    return lastDone;
  }

  function railHtml(stages) {
    return stages.map(function (s) {
      var cls = "of-step is-" + s.state + (s.milestone ? " is-milestone" : "");
      return (
        '<div class="' + cls + '" data-of-step="' + esc(s.key) + '">' +
        '<span class="of-dot"></span>' +
        '<span class="of-label">' + esc(s.label) + "</span>" +
        '<span class="of-at">' + esc(s.at ? fmtTime(s.at) : (s.missing ? "未上报" : "待发生")) + "</span>" +
        '<span class="of-hint">' + esc(s.hint) + "</span>" +
        "</div>"
      );
    }).join("");
  }

  /* --------------------------------------------------------------- 渲染 */

  function headerHtml(entry, scene) {
    var role = entry.direction === "out" ? "卖家" : "买家";
    var d = entry.detail || {};
    return (
      '<div class="of-head">' +
      '<div class="of-head-main">' +
      '<span class="of-no">订单号 <b data-of-no>' + esc(entry.ref_id || "—") + "</b></span>" +
      '<span class="of-tag">' + esc(entry.kind_label || entry.kind) + "</span>" +
      '<span class="of-tag">' + esc(scene.def.label) + " · " + esc(MODE_LABEL[scene.def.mode] || scene.def.mode) + "</span>" +
      '<span class="of-amount">' + money(entry.amount_usdc) + " <em>USDC</em></span>" +
      '<span class="of-side-tag is-' + esc(entry.direction) + '">' + esc(entry.direction === "out" ? "我买的" : "我卖的") + "</span>" +
      "</div>" +
      '<button type="button" class="btn" data-of-close>收起</button>' +
      "</div>" +
      '<div class="of-meta">' +
      '<div class="of-meta-item"><i>' + role + '</i><b data-of-party>' + esc(shortId(entry.counterparty_identity_id)) + "</b><span>交易对方</span></div>" +
      '<div class="of-meta-item"><i>' + role + '信息</i><b data-of-party-info>读取中…</b><span data-of-party-sub>身份卡</span></div>' +
      '<div class="of-meta-item"><i>创建时间</i><b>' + esc(fmtTime(entry.created_at)) + "</b><span>更新 " + esc(fmtTime(entry.updated_at)) + "</span></div>" +
      '<div class="of-meta-item"><i>合同详情</i><button type="button" class="btn" data-of-contract' +
        (entry.task_id ? "" : ' disabled title="这一单没有关联的任务合同"') + ">点击查看</button><span>" +
        esc(d.settlement_mode ? "结算模式 " + d.settlement_mode : "任务合同") + "</span></div>" +
      "</div>" +
      '<div class="of-contract" data-of-contract-box hidden></div>'
    );
  }

  function contractHtml(c) {
    if (!c) return '<p class="of-empty">读不到这一单的合同（可能不是任务结算单，或合同已被清理）。</p>';
    var rows = [
      ["标题", c.title || "—"],
      ["说明", c.description || "—"],
      ["托管金额", money(c.escrow_amount) + " " + (c.currency || "")],
      ["预期步骤数", c.expected_step_count == null ? "—" : String(c.expected_step_count)],
      ["截止时间", fmtTime(c.deadline_at)],
      ["合约哈希", c.contract_hash || "—"],
      ["交付物 schema", JSON.stringify(c.expected_output_schema || {})],
    ];
    return (
      '<div class="of-contract-grid">' +
      rows.map(function (r) {
        return '<div class="of-contract-row"><span>' + esc(r[0]) + "</span><code>" + esc(r[1]) + "</code></div>";
      }).join("") +
      "</div>"
    );
  }

  function render() {
    var host = $("#" + HOST);
    if (!host) return;
    var entry = state.entry;
    if (!entry || !state.open) { host.hidden = true; host.innerHTML = ""; return; }
    var built = state.built || { stages: [], scene: sceneOf(entry) };
    host.hidden = false;
    host.innerHTML =
      headerHtml(entry, built.scene) +
      '<div class="of-rail-wrap"><div class="of-rail">' + railHtml(built.stages) + "</div></div>" +
      '<p class="of-foot" data-of-foot></p>';
    paint();
  }

  function paint() {
    var host = $("#" + HOST);
    if (!host) return;
    var stages = (state.built && state.built.stages) || [];
    var live = null;
    stages.forEach(function (s) { if (s.state === "live" || s.state === "warn") live = s; });
    var missing = stages.filter(function (s) { return s.missing; }).length;
    var foot = $("[data-of-foot]", host);
    if (foot) {
      foot.innerHTML =
        "<span>已走到：<b>" + esc(live ? live.label : "还没开始") + "</b></span>" +
        (live && live.at ? "<span>时间 " + esc(fmtTime(live.at)) + "</span>" : "") +
        "<span>阶段图共 " + stages.length + " 步</span>" +
        (missing
          ? "<span>有 " + missing + " 个里程碑还没上报 —— 图上明确标成「未上报」，不替它点亮</span>"
          : "") +
        "<span>依据：后端状态机 + 流转历史 + 交付验证事件</span>";
    }
  }

  /* ------------------------------------------------------------ 取真实数据 */

  async function open(entry) {
    if (!entry) return;
    if (state.open && state.entry && state.entry.entry_id === entry.entry_id) {
      close();
      return;
    }
    state.entry = entry;
    state.open = true;
    state.built = buildStages(entry, [], null);
    markProgress(state.built.stages);
    render();
    var host = $("#" + HOST);
    if (host && host.scrollIntoView) host.scrollIntoView({ behavior: "smooth", block: "nearest" });

    await loadDetail(entry);
    loadParty(entry);
    loadContractSource(entry);
  }

  function close() {
    state.open = false;
    state.entry = null;
    state.built = null;
    render();
  }

  /** 详情接口给两样图上要用的真东西：流转历史（每步的时刻）+ 交付验证会话。 */
  async function loadDetail(entry) {
    var a = api();
    if (!a || !a.getPaymentEntry) return;
    try {
      var body = await a.getPaymentEntry(entry.kind, entry.ref_id, entry.identity_id);
      if (!state.open || !state.entry || state.entry.entry_id !== entry.entry_id) return;
      var fresh = (body && body.entry) || entry;
      state.entry = fresh;
      state.built = buildStages(fresh, (body && body.history) || [], (body && body.verification) || null);
      markProgress(state.built.stages);
      render();
    } catch (e) {
      var f = $("[data-of-foot]");
      if (f) f.innerHTML += "<span>流转历史读取失败：" + esc((e && (e.message || e.detail)) || e) + "（图上只按当前状态判断）</span>";
    }
  }

  /** 交易对方的信息：身份卡 basic scope，只拿展示名和状态，不拿任何隐私字段。 */
  async function loadParty(entry) {
    var id = entry.counterparty_identity_id;
    var host = $("#" + HOST);
    if (!host || !id) {
      if (host) {
        var b0 = $("[data-of-party-info]");
        if (b0) b0.textContent = "—";
      }
      return;
    }
    var a = api();
    if (!a || !a.karmaFetch) return;
    try {
      var card = await a.karmaFetch("/v1/identity/" + encodeURIComponent(id) + "/card?scope=basic", {
        method: "GET", headers: a.headers(),
      });
      if (!state.open || !state.entry || state.entry.entry_id !== entry.entry_id) return;
      var b = $("[data-of-party-info]");
      var s = $("[data-of-party-sub]");
      var p = $("[data-of-party]");
      if (p) p.textContent = card.display_id || shortId(id);
      if (b) b.textContent = [card.identity_class || "—", card.verification_status || "—"].join(" · ");
      if (s) {
        var rep = card.reputation || card.identity_reputation;
        var score = rep && (rep.score != null ? rep.score : rep.value);
        s.textContent = score != null ? "信誉 " + score : "身份卡";
      }
    } catch (_) {
      var b2 = $("[data-of-party-info]");
      if (b2) b2.textContent = "读不到（" + shortId(id) + "）";
    }
  }

  var contractCache = {};

  async function loadContractSource(entry) {
    if (!entry.task_id) return;
    if (Object.prototype.hasOwnProperty.call(contractCache, entry.task_id)) return;
    var a = api();
    if (!a || !a.getContract) return;
    try {
      contractCache[entry.task_id] = await a.getContract(entry.task_id);
    } catch (_) {
      contractCache[entry.task_id] = null;
    }
  }

  function toggleContract() {
    var host = $("#" + HOST);
    if (!host || !state.entry) return;
    var box = $("[data-of-contract-box]", host);
    if (!box) return;
    if (!box.hidden) { box.hidden = true; return; }
    var tid = state.entry.task_id;
    box.hidden = false;
    box.innerHTML = '<p class="of-empty">读取中…</p>';
    var w = 0;
    (function wait() {
      if (Object.prototype.hasOwnProperty.call(contractCache, tid) || w++ > 40) {
        box.innerHTML = contractHtml(contractCache[tid]);
        return;
      }
      setTimeout(wait, 100);
    })();
  }

  /** 服务类型下拉框的选项只有一个来源：上面那张 SCENES 表。别在下拉里手写第二份。 */
  function fillSceneSelects() {
    document.querySelectorAll("[data-scene-select]").forEach(function (sel) {
      var keep = sel.value;
      Object.keys(SCENES).forEach(function (id) {
        if (sel.querySelector('option[value="' + id + '"]')) return;
        var o = document.createElement("option");
        o.value = id;
        o.textContent = SCENES[id].label + " · " + (MODE_LABEL[SCENES[id].mode] || SCENES[id].mode);
        sel.appendChild(o);
      });
      sel.value = keep;
    });
  }

  function bind() {
    fillSceneSelects();
    var host = $("#" + HOST);
    if (!host) return;
    host.addEventListener("click", function (ev) {
      var t = ev.target;
      if (!t || !t.closest) return;
      if (t.closest("[data-of-close]")) { close(); return; }
      if (t.closest("[data-of-contract]")) { toggleContract(); return; }
    });
    document.addEventListener("karma-page-shown", function (ev) {
      if (!ev || !ev.detail || ev.detail.page !== "overview") close();
    });
    window.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape" && state.open) close();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind);
  } else {
    bind();
  }

  global.KarmaOrderFlow = {
    open: open,
    close: close,
    state: state,
    scenes: SCENES,
    eventStage: EVENT_STAGE,
    buildStages: buildStages,
    sceneOf: sceneOf,
    fillSceneSelects: fillSceneSelects,
  };
})(window);
