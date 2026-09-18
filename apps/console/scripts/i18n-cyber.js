/**
 * Cyber console i18n — zh-CN, en, ja, ko, es-AR, es-SV.
 * Every shipped pack covers all 256 keys; fallback is locale -> en -> zh-CN -> key.
 */
(function (global) {
  const STORAGE_KEY = "karma_cyber_lang";

  const en = {
    "api.lang": "Language",
    "api.base": "API base URL",
    "api.key": "API key (X-Karma-Api-Key)",
    "api.identity": "Identity ID",
    "api.save": "Save connection",
    "api.refresh": "Refresh from API",
    "api.lookup": "Settlement lookup",
    "api.task_id": "Task ID",
    "api.task_batch": "Task IDs (comma-separated)",
    "api.fetch_settlement": "Fetch Settlement",
    "api.status_ok": "Connected",
    "api.status_refreshed": "Credits refreshed",
    "api.status_idle": "Idle",
    "api.status_err": "Error",
    "api.sync_now": "Sync",
    "brand.title": "Karma Console",
    "nav.overview": "Orders",
    "nav.center": "Payments Hub",
    "nav.tasks": "Tasks",
    "nav.receipts": "Receipts",
    "nav.bills": "Bills",
    "nav.disputes": "Disputes",
    "nav.identity": "Identity & KYC",
    "nav.auth": "Authentication",
    "nav.settings": "Settings",
    "nav.agents": "Agents",
    "sub.orders.buy": "Orders I buy",
    "sub.orders.sell": "Orders I sell",
    "ord.title": "Order board",
    "ord.note": "Each lane is a stage: waiting → running → to confirm → in dispute. Finished orders leave this board once the dispute window closes — history lives in Payments and Bills.",
    "ord.all": "All",
    "ord.buy": "I buy",
    "ord.sell": "I sell",
    "ord.refresh": "Refresh",
    "sub.center.out": "Outgoing",
    "sub.center.in": "Incoming",
    "sub.center.confirm": "To confirm",
    "sub.center.dispute": "In dispute",
    "sub.center.new": "New payment",
    "sub.tasks.flow": "Settlement flow",
    "sub.identity.master": "Master identity",
    "sub.identity.verify": "Verification",
    "sub.identity.subs": "Sub-identities",
    "sub.identity.money": "Where funds live",
    "sub.agents.wizard": "Grant wizard",
    "sub.agents.mine": "My agents",
    "sub.agents.handoff": "Hand off",
    "sub.agents.connect": "Connect an agent",
    "sub.agents.pair": "Pairing",
    "side.rule_title": "Fund Safety Rules",
    "side.rule_body": "Admins can only pause — no ledger tampering or withdrawals. All credits stay 1:1 anchored to USDC.",
    "id.current": "Current Identity",
    "id.status": "OK",
    "id.buyer_sub": "Buyer sub-identity",
    "id.seller_sub": "Seller sub-identity",
    "top.sub": "Switch identity",
    "top.export": "Export Records",
    "top.lock": "Increase Lock",
    "scope.master": "Master ID",
    "scope.active": "Viewing as",
    "scope.master_all": "Master (all)",
    "scope.none": "not connected",
    "scope.empty": "No sub-identity yet - create one on the Identity page.",
    "page.overview.title": "Orders",
    "page.overview.sub": "Where every order stands right now. Finished orders step aside once the dispute window closes.",
    "page.center.title": "Payments Hub",
    "page.center.sub": "One identity can pay and receive depending on the task.",
    "page.tasks.title": "Tasks",
    "page.tasks.sub": "Progress, receipts, regret liability, and settlement.",
    "page.receipts.title": "Receipts",
    "page.receipts.sub": "Execution receipts, evidence hashes, runtime logs.",
    "page.bills.title": "Bills",
    "page.bills.sub": "Internal bill-credit state visible only to the identity owner.",
    "page.disputes.title": "Disputes",
    "page.disputes.sub": "Evidence, frozen funds, arbitration.",
    "page.market.title": "Skill Market",
    "page.market.sub": "List and call billable APIs",
    "page.reviews.title": "Review Desk",
    "page.reviews.sub": "Entity, developer and role-profile KYC queues in one place \u2014 with the machine verdict shown.",
    "nav.reviews": "Review Desk",
    "page.identity.title": "Identity & KYC",
    "page.identity.sub": "Verify once (ID + selfie), then spin up one card per agent.",
    "page.auth.title": "Authentication",
    "page.auth.sub": "Connect wallet and claim your identity card.",
    "page.agents.title": "Agent Onboarding",
    "page.agents.sub": "One identity card, any agent infrastructure.",
    "page.settings.title": "Settings",
    "page.settings.sub": "Safety, receipt rules, settlement, privacy, webhooks.",
    "m.locked": "Locked USDC",
    "m.locked_hint": "On-chain anchor",
    "m.available": "Available Credits",
    "m.available_hint": "Can create vouchers",
    "m.exec": "In Execution",
    "m.exec_hint": "Frozen for active tasks",
    "m.pending": "Pending Receipt",
    "m.pending_hint": "Accepted / pending settlement",
    "m.dispute": "Dispute Hold",
    "m.dispute_hint": "Awaiting arbitration",
    "quick.title": "Quick Actions",
    "quick.desc": "One identity can pay or receive across different tasks.",
    "quick.pay": "Create Payment Auth",
    "quick.pay_desc": "Issue a one-time Voucher; seller verifies to start.",
    "quick.receive": "Verify Payment Auth",
    "quick.receive_desc": "Enter buyer Voucher to confirm locked credits.",
    "quick.receipt": "Submit Receipt",
    "quick.receipt_desc": "Upload evidence hash, runtime log hash, and progress.",
    "quick.dispute": "Handle Dispute",
    "quick.dispute_desc": "Submit evidence, accept resolution, or request arbitration.",
    "flow.title": "Responsibility Flow",
    "flow.desc": "Flexible before responsibility; immutable after.",
    "flow.locked": "USDC Locked",
    "flow.locked_desc": "USDC locked into Vault; internal credits generated.",
    "flow.frozen": "Task Credits Frozen",
    "flow.frozen_desc": "In-progress credits cannot be re-authorized.",
    "flow.receipt": "Receipt Awaiting Confirmation",
    "flow.receipt_desc": "Execution Receipt submitted; pending verification or buyer confirmation.",
    "flow.settle": "Destroyed on Settlement",
    "flow.settle_desc": "On settlement, matching internal credits are burned.",
    "preview.title": "API Data Preview",
    "preview.desc": "GET /v1/settlement/{task_id} returns JSON (requires API Key).",
    "tasks.title": "Pending Actions",
    "tasks.desc": "Auto-populated from task ID list via API.",
    "tasks.view_all": "View All",
    "th.task": "Task",
    "th.role": "Role",
    "th.counterparty": "Counterparty",
    "th.amount": "Amount",
    "th.progress": "Progress",
    "th.status": "Status",
    "th.next": "Next Step",
    "th.receipts": "Receipts",
    "center.payable": "Payable Credits",
    "center.payable_hint": "Can create Vouchers",
    "center.issued": "Issued Auth",
    "center.issued_hint": "Pending / in progress",
    "center.receivable": "Receivable",
    "center.receivable_hint": "Can submit receipts",
    "center.settleable": "Settleable",
    "center.settleable_hint": "Can request payout",
    "center.fee": "Protocol Fee Est.",
    "center.fee_hint": "Deducted at settlement",
    "pay.title": "I Want to Pay",
    "pay.desc": "Create a one-time auth; seller verifies to lock credits.",
    "pay.seller_id": "Seller Karma ID",
    "pay.amount": "Amount (USDC)",
    "pay.validity": "Validity",
    "pay.24h": "24 hours",
    "pay.48h": "48 hours",
    "pay.7d": "7 days",
    "pay.task_desc": "Task Description",
    "pay.task_desc_ph": "Describe the task...",
    "pay.notice": "After seller accepts, the corresponding credits will be locked.",
    "pay.btn": "Generate Payment Voucher",
    "recv.title": "I Want to Receive",
    "recv.desc": "Enter buyer's Voucher; confirm credits are locked before starting.",
    "recv.voucher": "Buyer Voucher",
    "recv.btn": "Verify Auth",
    "recv.mode": "Acceptance Mode",
    "recv.mode1": "Start immediately after accepting",
    "recv.mode2": "Wait for manual start",
    "recv.mode3": "Auto-start via Agent Runtime",
    "recv.accept": "Accept & Start Task",
    "task.page_title": "Task Execution",
    "task.page_desc": "Use Settlement lookup above to fetch real SettlementState.",
    "task.new_auth": "New Payment Auth",
    "task.settle_ops": "Settlement Operations",
    "task.history": "State Transition History",
    "task.history_desc": "Last 50 settlement state changes.",
    "receipt.submit_title": "Submit Execution Receipt",
    "receipt.submit_desc": "Receipts must bind task, identity, evidence hash, log hash, and signature.",
    "receipt.task_id": "Task ID",
    "receipt.evidence": "Evidence Hash",
    "receipt.log": "Runtime Log Hash",
    "receipt.output": "Output Digest",
    "receipt.btn": "Submit Receipt",
    "receipt.list_title": "Receipt List",
    "receipt.list_desc": "Enter Task ID to load all receipts for that task.",
    "receipt.load": "Load",
    "bills.export": "Export CSV",
    "bills.th.time": "Time",
    "bills.th.dir": "Direction",
    "bills.th.task": "Task",
    "bills.th.counter": "Counterparty",
    "bills.th.amount": "Amount",
    "bills.th.result": "Settlement Result",
    "bills.th.status": "Status",
    "bills.empty": "Configure task IDs to auto-populate bill data.",
    "disp.frozen": "Dispute Hold",
    "disp.frozen_hint": "Funds locked",
    "disp.mine": "My Action Needed",
    "disp.mine_hint": "Need to submit evidence",
    "disp.arb": "In Arbitration",
    "disp.arb_hint": "Awaiting ruling",
    "disp.handle_title": "Dispute Handling",
    "disp.handle_desc": "Funds are frozen during disputes; auto-executed after ruling.",
    "disp.th.task": "Task",
    "disp.th.counter": "Counterparty",
    "disp.th.amount": "Amount",
    "disp.th.reason": "Reason",
    "disp.th.status": "Status",
    "disp.th.action": "Action",
    "id.main_title": "Main Identity",
    "id.main_desc": "Karma Identity SBT is non-transferable and non-tradable.",
    "id.api_status": "API Status",
    "id.api_version": "API Version",
    "id.change_num": "Change Display Number",
    "id.bind_legal": "Bind Legal Identity",
    "id.safety_title": "Safety Mode",
    "id.safety_desc": "Runtime Safety Mode controls global fund operation permissions.",
    "id.buyer_sub": "Buyer Sub-ID",
    "id.buyer_sub_desc": "For payment tasks",
    "id.seller_sub": "Seller Sub-ID",
    "id.seller_sub_desc": "For receiving tasks",
    "id.enabled": "Enabled",
    "set.safety": "Fund Safety",
    "set.safety_desc": "Set per-task and daily limits, release confirmation method.",
    "set.receipt_rules": "Receipt Rules",
    "set.receipt_rules_desc": "Decide how API / MCP / Agent tasks are auto-verified.",
    "set.settle_pref": "Settlement Preference",
    "set.settle_pref_desc": "Auto-settle on completion or manual confirmation.",
    "set.privacy": "Privacy Settings",
    "set.privacy_desc": "Display ID rotation, sub-ID usage, evidence disclosure.",
    "set.notify": "Notifications",
    "set.notify_desc": "Alerts on task acceptance, receipt submission, disputes, settlement.",
    "set.webhook": "Developer Webhook",
    "set.webhook_desc": "Agent platform auto-receives task status, receipt verification, settlement results.",
    "set.ai_title": "AI Agent Auto-Authorization Center",
    "set.ai_desc": "Control whether AI agents can auto-request auth, submit receipts, and sync task status.",
    "set.ai_toggle": "Enable AI Agent Authorization",
    "set.ai_toggle_desc": "AI can only operate within your configured limits, task types, and risk rules.",
    "set.ai_status": "Current Status",
    "set.ai_off": "OFF",
    "set.ai_on": "ON",
    "set.ai_rules": "AI Safety Boundaries",
    "set.ai_max_single": "Max single AI auto-auth amount",
    "set.ai_max_daily": "Max daily AI auto-auth total",
    "set.ai_scope": "AI auto-operation scope",
    "set.ai_scope1": "Auto auth + auto receipts + real-time sync",
    "set.ai_scope2": "Only auto-submit receipts",
    "set.ai_scope3": "Only real-time sync",
    "set.ai_scope4": "All disabled",
    "set.ai_receipt_mode": "Execution Receipt mode",
    "set.ai_receipt1": "Agent Runtime auto-submit",
    "set.ai_receipt2": "MCP Trace auto-submit",
    "set.ai_receipt3": "API receipt auto-submit",
    "set.ai_receipt4": "Manual submit",
    "set.ai_risk": "High-risk task confirmation",
    "set.ai_risk1": "Manual confirm for over-limit / unknown Agent / external contract",
    "set.ai_risk2": "All AI auth requires manual confirm",
    "set.ai_risk3": "Fully auto, within limits",
    "set.ai_sync": "Real-time status sync",
    "set.ai_sync1": "On: sync tasks, receipts, progress, settlement, disputes",
    "set.ai_sync2": "Off",
    "set.ai_warn": "Safety boundary: AI agents can only request auth and submit receipts; anything exceeding rules requires manual confirmation.",
    "set.ai_save": "Save AI Agent Rules",
    "sync.title": "Task Sync",
    "sync.desc": "Enter task IDs (comma-separated) to auto-fetch Settlement data from API.",
    "auto_sync": "Auto sync",
    "last_sync": "Last",
  };

  const zhCN = {
    "api.lang": "语言",
    "api.base": "API 根地址",
    "api.key": "API Key (X-Karma-Api-Key)",
    "api.identity": "身份 ID",
    "api.save": "保存连接",
    "api.refresh": "从 API 刷新额度",
    "api.lookup": "查询结算任务",
    "api.task_id": "任务 ID",
    "api.task_batch": "任务列表（逗号分隔）",
    "api.fetch_settlement": "拉取 Settlement",
    "api.status_ok": "已连接",
    "api.status_refreshed": "额度已刷新",
    "api.status_idle": "未请求",
    "api.status_err": "错误",
    "api.sync_now": "同步",
    "brand.title": "Karma Console",
    "nav.overview": "订单",
    "nav.center": "收付中心",
    "nav.tasks": "任务执行",
    "nav.receipts": "回执证明",
    "nav.bills": "账单",
    "nav.disputes": "争议",
    "nav.identity": "身份 · 认证",
    "nav.auth": "认证",
    "nav.settings": "设置",
    "nav.agents": "Agent 接入",
    "sub.orders.buy": "买方订单",
    "sub.orders.sell": "卖方订单",
    "ord.title": "订单状态图",
    "ord.note": "每条泳道就是一个阶段：待接单 → 执行中 → 待确认 → 争议中。已完成且过了可争议期的单会从这里退场，历史去「收付中心」和「账单」看。",
    "ord.all": "全部",
    "ord.buy": "我买的",
    "ord.sell": "我卖的",
    "ord.refresh": "刷新",
    "sub.center.out": "支出明细",
    "sub.center.in": "收入明细",
    "sub.center.confirm": "确认区",
    "sub.center.dispute": "争议区",
    "sub.center.new": "发起收付",
    "sub.tasks.flow": "结算流转",
    "sub.identity.master": "我的主身份",
    "sub.identity.verify": "主身份认证",
    "sub.identity.subs": "子身份",
    "sub.identity.money": "资金归属",
    "sub.agents.wizard": "授权向导",
    "sub.agents.mine": "我的 Agent",
    "sub.agents.handoff": "交给 Agent",
    "sub.agents.connect": "接入一个 Agent",
    "sub.agents.pair": "配对接入",
    "side.rule_title": "资金安全规则",
    "side.rule_body": "管理员只能暂停，不能改账、不能提现。所有责任额度永远 1:1 锚定 USDC。",
    "id.current": "当前身份",
    "id.status": "正常",
    "id.buyer_sub": "付款子身份",
    "id.seller_sub": "收款子身份",
    "top.sub": "切换身份",
    "top.export": "导出记录",
    "top.lock": "增加锁仓额度",
    "scope.master": "主体身份卡",
    "scope.active": "当前视角",
    "scope.master_all": "主体（全部）",
    "scope.none": "未连接",
    "scope.empty": "还没有子身份档案，可在「身份」页创建。",
    "page.overview.title": "订单",
    "page.overview.sub": "订单走到哪一步一眼看见；过了可争议期的单自动退场。",
    "page.center.title": "收付中心",
    "page.center.sub": "同一个身份既可以付款，也可以收款。",
    "page.tasks.title": "任务执行",
    "page.tasks.sub": "查看任务进度、执行回执、反悔责任和结算状态。",
    "page.receipts.title": "回执证明",
    "page.receipts.sub": "提交和验证 Execution Receipt、Evidence Hash 与 Runtime Log。",
    "page.bills.title": "账单",
    "page.bills.sub": "账单额度是内部责任状态，只对身份主人展示。",
    "page.disputes.title": "争议",
    "page.disputes.sub": "提交证据、查看冻结资金、请求仲裁或接受方案。",
    "page.market.title": "技能市场",
    "page.market.sub": "上架与调用可计费的接口",
    "page.reviews.title": "复核台",
    "page.reviews.sub": "主身份认证、主体认证、开发者实名、子身份 KYC 四条待办汇到一处，机器结论摊开给你看。",
    "nav.reviews": "复核台",
    "page.identity.title": "身份 · 认证",
    "page.identity.sub": "一次认证（证件 + 刷脸）拿到身份卡；每个 agent 一张子身份卡。",
    "page.auth.title": "认证",
    "page.auth.sub": "连接钱包完成 SIWE 认证，领取你的 master 身份卡。",
    "page.agents.title": "Agent 接入",
    "page.agents.sub": "一张身份卡，接入任意 agent 基础设施。",
    "page.settings.title": "设置",
    "page.settings.sub": "配置资金安全、回执规则、结算偏好、隐私和 Webhook。",
    "m.locked": "锁仓 USDC",
    "m.locked_hint": "真实资金锚定",
    "m.available": "可用额度",
    "m.available_hint": "可创建付款授权",
    "m.exec": "执行占用",
    "m.exec_hint": "已接单任务冻结",
    "m.pending": "待收款",
    "m.pending_hint": "已接单 / 待结算",
    "m.dispute": "争议冻结",
    "m.dispute_hint": "等待仲裁推进",
    "quick.title": "快捷操作",
    "quick.desc": "不区分固定买家/卖家，同一个身份在不同任务里可以付款，也可以收款。",
    "quick.pay": "创建付款授权",
    "quick.pay_desc": "给卖家一个一次性 Voucher，卖家验证后开工。",
    "quick.receive": "验证收款授权",
    "quick.receive_desc": "输入买家 Voucher，确认额度已锁定。",
    "quick.receipt": "提交执行回执",
    "quick.receipt_desc": "上传 evidence hash、runtime log hash 和进度。",
    "quick.dispute": "处理争议",
    "quick.dispute_desc": "提交证据、接受方案或请求仲裁。",
    "flow.title": "责任状态流",
    "flow.desc": "责任成立前灵活，责任成立后不可后台篡改。",
    "flow.locked": "USDC 已锁仓",
    "flow.locked_desc": "USDC 已锁入 Vault，生成内部责任额度。",
    "flow.frozen": "任务额度已冻结",
    "flow.frozen_desc": "执行中额度不能重复授权给其他任务。",
    "flow.receipt": "回执等待确认",
    "flow.receipt_desc": "Execution Receipt 已提交，等待验证或买家确认。",
    "flow.settle": "结算后销毁",
    "flow.settle_desc": "USDC 结算时，同额内部责任额度同步销毁。",
    "preview.title": "API 数据预览",
    "preview.desc": "GET /v1/settlement/{task_id} 返回 JSON（需 API Key 与权限）。",
    "tasks.title": "最近需要处理",
    "tasks.desc": "下方表格由 GET /v1/settlement 等接口按「任务 ID 列表」自动填充。",
    "tasks.view_all": "查看全部",
    "th.task": "任务",
    "th.role": "角色",
    "th.counterparty": "对方",
    "th.amount": "金额",
    "th.progress": "进度",
    "th.status": "状态",
    "th.next": "下一步",
    "th.receipts": "回执数",
    "center.payable": "可付款额度",
    "center.payable_hint": "可创建 Voucher",
    "center.issued": "已发出授权",
    "center.issued_hint": "等待/执行中",
    "center.receivable": "待收款",
    "center.receivable_hint": "可提交回执",
    "center.settleable": "可结算",
    "center.settleable_hint": "可申请到账",
    "center.fee": "协议费预估",
    "center.fee_hint": "结算时扣除",
    "pay.title": "我要付款",
    "pay.desc": "创建一次性授权，卖家验证后会锁定对应额度。（完整 Voucher 需服务端签名 / EIP-712）",
    "pay.seller_id": "收款方 Karma ID",
    "pay.amount": "金额 (USDC)",
    "pay.validity": "有效期",
    "pay.24h": "24 小时",
    "pay.48h": "48 小时",
    "pay.7d": "7 天",
    "pay.task_desc": "任务说明",
    "pay.task_desc_ph": "描述任务内容...",
    "pay.notice": "卖家接单后，对应额度会被锁定，不能再用于其他任务。",
    "pay.btn": "生成付款授权 Voucher",
    "recv.title": "我要收款",
    "recv.desc": "输入买家提供的 Voucher，确认额度已锁定后再开工。",
    "recv.voucher": "买家 Voucher",
    "recv.btn": "验证授权",
    "recv.mode": "接单方式",
    "recv.mode1": "接单后立即执行",
    "recv.mode2": "接单后等待手动开始",
    "recv.mode3": "由 Agent Runtime 自动开始",
    "recv.accept": "接单并开始任务",
    "task.page_title": "任务执行",
    "task.page_desc": "使用上方「查询结算任务」从 API 拉取真实 SettlementState。",
    "task.new_auth": "新建付款授权",
    "task.settle_ops": "结算操作",
    "task.history": "状态转换历史",
    "task.history_desc": "最近 50 条 Settlement 状态变更记录。",
    "receipt.submit_title": "提交 Execution Receipt",
    "receipt.submit_desc": "回执必须绑定任务、身份、证据哈希、日志哈希和签名。",
    "receipt.task_id": "Task ID",
    "receipt.evidence": "Evidence Hash",
    "receipt.log": "Runtime Log Hash",
    "receipt.output": "Output Digest",
    "receipt.btn": "提交回执",
    "receipt.list_title": "回执列表",
    "receipt.list_desc": "输入 Task ID 后加载该任务的所有回执。",
    "receipt.load": "加载",
    "bills.export": "导出 CSV",
    "bills.th.time": "时间",
    "bills.th.dir": "方向",
    "bills.th.task": "任务",
    "bills.th.counter": "对方",
    "bills.th.amount": "金额",
    "bills.th.result": "结算结果",
    "bills.th.status": "状态",
    "bills.empty": "配置任务 ID 后自动填充账单数据。",
    "disp.frozen": "争议冻结",
    "disp.frozen_hint": "资金已锁定",
    "disp.mine": "待我处理",
    "disp.mine_hint": "需要提交证据",
    "disp.arb": "仲裁中",
    "disp.arb_hint": "等待裁决",
    "disp.handle_title": "争议处理",
    "disp.handle_desc": "争议期间资金不会被任何一方拿走，裁决后自动执行。",
    "disp.th.task": "任务",
    "disp.th.counter": "对方",
    "disp.th.amount": "金额",
    "disp.th.reason": "原因",
    "disp.th.status": "状态",
    "disp.th.action": "操作",
    "id.main_title": "主身份",
    "id.main_desc": "Karma Identity SBT 是责任身份，不可交易、不可转让。",
    "id.api_status": "API 状态",
    "id.api_version": "API 版本",
    "id.change_num": "更换展示编号",
    "id.bind_legal": "绑定法律身份",
    "id.safety_title": "安全模式",
    "id.safety_desc": "Runtime Safety Mode 控制全局资金操作权限。",
    "id.buyer_sub": "Buyer Sub-ID",
    "id.buyer_sub_desc": "用于付款任务",
    "id.seller_sub": "Seller Sub-ID",
    "id.seller_sub_desc": "用于收款任务",
    "id.enabled": "启用",
    "set.safety": "资金安全",
    "set.safety_desc": "设置单笔任务上限、每日授权上限、释放额度确认方式。",
    "set.receipt_rules": "回执规则",
    "set.receipt_rules_desc": "决定 API / MCP / Agent 任务如何自动验证。",
    "set.settle_pref": "结算偏好",
    "set.settle_pref_desc": "任务完成后自动结算或手动确认结算。",
    "set.privacy": "隐私设置",
    "set.privacy_desc": "展示编号轮换、子身份使用和证据披露权限。",
    "set.notify": "通知",
    "set.notify_desc": "任务接单、回执提交、争议、结算到账时提醒。",
    "set.webhook": "开发者 Webhook",
    "set.webhook_desc": "Agent 平台自动接收任务状态、回执验证和结算结果。",
    "set.ai_title": "AI Agent 自动授权中心",
    "set.ai_desc": "用户设置好规则后，可用一个开关控制是否允许 AI 代理自动请求授权、提交回执并实时同步任务状态。",
    "set.ai_toggle": "开启授权 AI 代理",
    "set.ai_toggle_desc": "开启后，AI 只能在你设置的额度、任务类型和风控规则内自动操作。",
    "set.ai_status": "当前状态",
    "set.ai_off": "关闭",
    "set.ai_on": "开启",
    "set.ai_rules": "AI 安全边界",
    "set.ai_max_single": "单次 AI 最大自动授权额度",
    "set.ai_max_daily": "每日 AI 自动授权总额度",
    "set.ai_scope": "AI 自动操作范围",
    "set.ai_scope1": "自动请求授权 + 自动提交回执 + 实时同步状态",
    "set.ai_scope2": "只允许自动提交回执",
    "set.ai_scope3": "只允许实时同步状态",
    "set.ai_scope4": "全部关闭",
    "set.ai_receipt_mode": "Execution Receipt 模式",
    "set.ai_receipt1": "Agent Runtime 自动提交",
    "set.ai_receipt2": "MCP Trace 自动提交",
    "set.ai_receipt3": "API 回执自动提交",
    "set.ai_receipt4": "手动提交",
    "set.ai_risk": "高风险任务确认模式",
    "set.ai_risk1": "超过额度 / 未知 Agent / 外部合约请求时必须人工确认",
    "set.ai_risk2": "所有 AI 授权都必须人工确认",
    "set.ai_risk3": "完全自动，但受额度限制",
    "set.ai_sync": "实时状态同步",
    "set.ai_sync1": "开启：同步任务、回执、进度、结算和争议状态",
    "set.ai_sync2": "关闭",
    "set.ai_warn": "安全边界：AI 代理只能请求授权和提交回执；任何超出规则的金额、未知 Agent、未知合约、跨链请求，都必须人工二次确认。",
    "set.ai_save": "保存 AI Agent 授权规则",
    "sync.title": "任务同步",
    "sync.desc": "输入任务 ID（逗号分隔），自动从 API 拉取 Settlement 数据。",
    "auto_sync": "自动同步",
    "last_sync": "上次",
  };

  /* ------------------------------------------------------------------
   * 完整语言包：ja / ko / es-Latam
   * 每个包都覆盖 en 的全部 256 个键，所以切换后不会出现半英半本地语。
   * ------------------------------------------------------------------ */
  const ja = {
    "api.lang": "言語",
    "api.base": "API ベース URL",
    "api.key": "API キー（X-Karma-Api-Key）",
    "api.identity": "アイデンティティ ID",
    "api.save": "接続を保存",
    "api.refresh": "API から更新",
    "api.lookup": "決済照会",
    "api.task_id": "タスク ID",
    "api.task_batch": "タスク ID（カンマ区切り）",
    "api.fetch_settlement": "決済を取得",
    "api.status_ok": "接続済み",
    "api.status_refreshed": "クレジットを更新しました",
    "api.status_idle": "待機中",
    "api.status_err": "エラー",
    "api.sync_now": "同期",
    "brand.title": "Karma Console",
    "nav.overview": "注文",
    "nav.center": "決済ハブ",
    "nav.tasks": "タスク",
    "nav.receipts": "レシート",
    "nav.bills": "請求",
    "nav.disputes": "紛争",
    "nav.identity": "身元・認証",
    "nav.auth": "認証",
    "nav.settings": "設定",
    "nav.agents": "エージェント",
    "sub.orders.buy": "自分が買う注文",
    "sub.orders.sell": "自分が売る注文",
    "ord.title": "注文ボード",
    "ord.note": "各レーンは段階です：待機 → 実行中 → 確認待ち → 紛争中。確定した注文は紛争期間の終了後にこのボードから外れ、履歴は決済と請求に残ります。",
    "ord.all": "すべて",
    "ord.buy": "買う",
    "ord.sell": "売る",
    "ord.refresh": "更新",
    "sub.center.out": "支払い",
    "sub.center.in": "受け取り",
    "sub.center.confirm": "確認待ち",
    "sub.center.dispute": "紛争中",
    "sub.center.new": "新規支払い",
    "sub.tasks.flow": "決済フロー",
    "sub.identity.master": "メインアイデンティティ",
    "sub.identity.verify": "本人確認",
    "sub.identity.subs": "サブアイデンティティ",
    "sub.identity.money": "資金の保管場所",
    "sub.agents.wizard": "付与ウィザード",
    "sub.agents.mine": "マイエージェント",
    "sub.agents.handoff": "引き継ぎ",
    "sub.agents.connect": "エージェントを接続",
    "sub.agents.pair": "ペアリング",
    "side.rule_title": "資金安全ルール",
    "side.rule_body": "管理者は一時停止のみ可能で、台帳の改ざんや出金はできません。すべてのクレジットは USDC と 1:1 で裏付けられます。",
    "id.current": "現在のアイデンティティ",
    "id.status": "正常",
    "id.buyer_sub": "買い手サブ ID",
    "id.seller_sub": "売り手サブ ID",
    "top.sub": "アイデンティティを切り替え",
    "top.export": "記録をエクスポート",
    "top.lock": "ロックを増やす",
    "scope.master": "メイン ID",
    "scope.active": "表示中",
    "scope.master_all": "メイン（すべて）",
    "scope.none": "未接続",
    "scope.empty": "サブアイデンティティがありません。身元ページで作成してください。",
    "page.overview.title": "注文",
    "page.overview.sub": "すべての注文の現在地。確定した注文は紛争期間の終了後に外れます。",
    "page.center.title": "決済ハブ",
    "page.center.sub": "同じアイデンティティが、タスクに応じて支払いも受け取りも行えます。",
    "page.tasks.title": "タスク",
    "page.tasks.sub": "進捗、レシート、責任、決済。",
    "page.receipts.title": "レシート",
    "page.receipts.sub": "実行レシート、証拠ハッシュ、ランタイムログ。",
    "page.bills.title": "請求",
    "page.bills.sub": "アイデンティティの所有者だけが見られる内部ビルクレジットの状態。",
    "page.disputes.title": "紛争",
    "page.disputes.sub": "証拠、凍結資金、仲裁。",
    "page.market.title": "スキルマーケット",
    "page.market.sub": "課金 API の出品と呼び出し",
    "page.reviews.title": "審査デスク",
    "page.reviews.sub": "法人・開発者・ロールプロフィールの KYC を一か所に。機械判定の結果も表示します。",
    "nav.reviews": "審査デスク",
    "page.identity.title": "身元・認証",
    "page.identity.sub": "一度だけ本人確認（ID + 自撮り）を行い、エージェントごとにカードを発行します。",
    "page.auth.title": "認証",
    "page.auth.sub": "ウォレットを接続してアイデンティティカードを受け取ります。",
    "page.agents.title": "エージェント接続",
    "page.agents.sub": "1 枚のアイデンティティカードで、あらゆるエージェント基盤に接続できます。",
    "page.settings.title": "設定",
    "page.settings.sub": "安全、レシート規則、決済、プライバシー、Webhook。",
    "m.locked": "ロック済み USDC",
    "m.locked_hint": "オンチェーン担保",
    "m.available": "利用可能クレジット",
    "m.available_hint": "バウチャーを発行できます",
    "m.exec": "実行中",
    "m.exec_hint": "進行中タスクのため凍結",
    "m.pending": "レシート待ち",
    "m.pending_hint": "受理済み／決済待ち",
    "m.dispute": "紛争による保留",
    "m.dispute_hint": "仲裁待ち",
    "quick.title": "クイックアクション",
    "quick.desc": "同じアイデンティティが、タスクに応じて支払いも受け取りもできます。",
    "quick.pay": "支払い認証を作成",
    "quick.pay_desc": "一度限りのバウチャーを発行し、売り手が検証して開始します。",
    "quick.receive": "支払い認証を検証",
    "quick.receive_desc": "買い手のバウチャーを入力し、ロック済みクレジットを確認します。",
    "quick.receipt": "レシートを提出",
    "quick.receipt_desc": "証拠ハッシュ、ランタイムログハッシュ、進捗をアップロードします。",
    "quick.dispute": "紛争を処理",
    "quick.dispute_desc": "証拠を提出し、和解を受け入れるか、仲裁を申請します。",
    "flow.title": "責任フロー",
    "flow.desc": "責任が生じる前は柔軟に、生じた後は不可逆に。",
    "flow.locked": "USDC をロック",
    "flow.locked_desc": "USDC を Vault にロックし、内部クレジットを発行します。",
    "flow.frozen": "タスククレジットを凍結",
    "flow.frozen_desc": "進行中のクレジットは再付与できません。",
    "flow.receipt": "レシートの確認待ち",
    "flow.receipt_desc": "実行レシートを提出済み。検証または買い手の確認待ちです。",
    "flow.settle": "決済時に消滅",
    "flow.settle_desc": "決済時、対応する内部クレジットは焼却されます。",
    "preview.title": "API データプレビュー",
    "preview.desc": "GET /v1/settlement/{task_id} が JSON を返します（API キーが必要）。",
    "tasks.title": "未処理アクション",
    "tasks.desc": "API 経由でタスク ID リストから自動取得します。",
    "tasks.view_all": "すべて表示",
    "th.task": "タスク",
    "th.role": "役割",
    "th.counterparty": "相手方",
    "th.amount": "金額",
    "th.progress": "進捗",
    "th.status": "ステータス",
    "th.next": "次のステップ",
    "th.receipts": "レシート",
    "center.payable": "支払可能クレジット",
    "center.payable_hint": "バウチャーを発行できます",
    "center.issued": "発行済み認証",
    "center.issued_hint": "保留／進行中",
    "center.receivable": "受け取り可能",
    "center.receivable_hint": "レシートを提出できます",
    "center.settleable": "決済可能",
    "center.settleable_hint": "支払いを請求できます",
    "center.fee": "プロトコル手数料（概算）",
    "center.fee_hint": "決済時に差し引かれます",
    "pay.title": "支払いたい",
    "pay.desc": "一度限りの認証を作成し、売り手が検証してクレジットをロックします。",
    "pay.seller_id": "売り手の Karma ID",
    "pay.amount": "金額（USDC）",
    "pay.validity": "有効期限",
    "pay.24h": "24 時間",
    "pay.48h": "48 時間",
    "pay.7d": "7 日",
    "pay.task_desc": "タスクの説明",
    "pay.task_desc_ph": "タスクを説明してください…",
    "pay.notice": "売り手が受諾すると、対応するクレジットがロックされます。",
    "pay.btn": "支払いバウチャーを生成",
    "recv.title": "受け取りたい",
    "recv.desc": "買い手のバウチャーを入力し、開始前にクレジットのロックを確認します。",
    "recv.voucher": "買い手のバウチャー",
    "recv.btn": "認証を検証",
    "recv.mode": "受諾モード",
    "recv.mode1": "受諾後すぐに開始",
    "recv.mode2": "手動開始を待つ",
    "recv.mode3": "Agent Runtime で自動開始",
    "recv.accept": "受諾してタスクを開始",
    "task.page_title": "タスク実行",
    "task.page_desc": "上部の決済照会で実際の SettlementState を取得できます。",
    "task.new_auth": "新しい支払い認証",
    "task.settle_ops": "決済オペレーション",
    "task.history": "状態遷移履歴",
    "task.history_desc": "直近 50 件の決済状態変更。",
    "receipt.submit_title": "実行レシートを提出",
    "receipt.submit_desc": "レシートはタスク、アイデンティティ、証拠ハッシュ、ログハッシュ、署名を紐付けます。",
    "receipt.task_id": "タスク ID",
    "receipt.evidence": "証拠ハッシュ",
    "receipt.log": "ランタイムログハッシュ",
    "receipt.output": "出力ダイジェスト",
    "receipt.btn": "レシートを提出",
    "receipt.list_title": "レシート一覧",
    "receipt.list_desc": "タスク ID を入力すると、そのタスクの全レシートを読み込みます。",
    "receipt.load": "読み込む",
    "bills.export": "CSV をエクスポート",
    "bills.th.time": "時刻",
    "bills.th.dir": "方向",
    "bills.th.task": "タスク",
    "bills.th.counter": "相手方",
    "bills.th.amount": "金額",
    "bills.th.result": "決済結果",
    "bills.th.status": "ステータス",
    "bills.empty": "タスク ID を設定すると請求データが自動で入ります。",
    "disp.frozen": "紛争による保留",
    "disp.frozen_hint": "資金は凍結中",
    "disp.mine": "自分の対応が必要",
    "disp.mine_hint": "証拠の提出が必要です",
    "disp.arb": "仲裁中",
    "disp.arb_hint": "判断を待っています",
    "disp.handle_title": "紛争処理",
    "disp.handle_desc": "紛争中は資金を凍結し、判断後に自動実行します。",
    "disp.th.task": "タスク",
    "disp.th.counter": "相手方",
    "disp.th.amount": "金額",
    "disp.th.reason": "理由",
    "disp.th.status": "ステータス",
    "disp.th.action": "操作",
    "id.main_title": "メインアイデンティティ",
    "id.main_desc": "Karma アイデンティティ SBT は譲渡も取引もできません。",
    "id.api_status": "API ステータス",
    "id.api_version": "API バージョン",
    "id.change_num": "表示番号を変更",
    "id.bind_legal": "法的身元を紐付け",
    "id.safety_title": "セーフティモード",
    "id.safety_desc": "Runtime セーフティモードは資金操作の全体権限を制御します。",
    "id.buyer_sub_desc": "支払いタスク用",
    "id.seller_sub_desc": "受け取りタスク用",
    "id.enabled": "有効",
    "set.safety": "資金安全",
    "set.safety_desc": "タスクごと・1 日あたりの上限、解放の確認方法を設定します。",
    "set.receipt_rules": "レシート規則",
    "set.receipt_rules_desc": "API / MCP / Agent タスクをどう自動検証するかを決めます。",
    "set.settle_pref": "決済の設定",
    "set.settle_pref_desc": "完了時に自動決済するか、手動確認にするか。",
    "set.privacy": "プライバシー設定",
    "set.privacy_desc": "表示 ID のローテーション、サブ ID の使用、証拠の開示。",
    "set.notify": "通知",
    "set.notify_desc": "タスク受諾、レシート提出、紛争、決済を通知します。",
    "set.webhook": "開発者向け Webhook",
    "set.webhook_desc": "エージェント基盤がタスク状態、レシート検証、決済結果を自動受信します。",
    "set.ai_title": "AI エージェント自動認証センター",
    "set.ai_desc": "AI エージェントが自動で認証を要求し、レシートを提出し、タスク状態を同期できるかを制御します。",
    "set.ai_toggle": "AI エージェント認証を有効化",
    "set.ai_toggle_desc": "AI は設定した上限、タスク種別、リスク規則の範囲内でのみ動作できます。",
    "set.ai_status": "現在の状態",
    "set.ai_off": "オフ",
    "set.ai_on": "オン",
    "set.ai_rules": "AI 安全境界",
    "set.ai_max_single": "AI が自動認証できる 1 件あたりの上限",
    "set.ai_max_daily": "AI が自動認証できる 1 日あたりの合計上限",
    "set.ai_scope": "AI 自動処理の範囲",
    "set.ai_scope1": "自動認証 + 自動レシート + リアルタイム同期",
    "set.ai_scope2": "レシートの自動提出のみ",
    "set.ai_scope3": "リアルタイム同期のみ",
    "set.ai_scope4": "すべて無効",
    "set.ai_receipt_mode": "実行レシートのモード",
    "set.ai_receipt1": "Agent Runtime が自動提出",
    "set.ai_receipt2": "MCP Trace が自動提出",
    "set.ai_receipt3": "API レシートを自動提出",
    "set.ai_receipt4": "手動提出",
    "set.ai_risk": "高リスクタスクの確認",
    "set.ai_risk1": "上限超過 / 未知の Agent / 外部コントラクトは手動確認",
    "set.ai_risk2": "すべての AI 認証に手動確認を要求",
    "set.ai_risk3": "上限内は完全自動",
    "set.ai_sync": "リアルタイム状態同期",
    "set.ai_sync1": "オン：タスク、レシート、進捗、決済、紛争を同期",
    "set.ai_sync2": "オフ",
    "set.ai_warn": "安全境界：AI エージェントは認証の要求とレシートの提出のみ可能です。規則を超える操作は手動確認が必要です。",
    "set.ai_save": "AI エージェント規則を保存",
    "sync.title": "タスク同期",
    "sync.desc": "タスク ID（カンマ区切り）を入力すると、API から決済データを自動取得します。",
    "auto_sync": "自動同期",
    "last_sync": "前回",
  };

  const ko = {
    "api.lang": "언어",
    "api.base": "API 기본 URL",
    "api.key": "API 키 (X-Karma-Api-Key)",
    "api.identity": "아이덴티티 ID",
    "api.save": "연결 저장",
    "api.refresh": "API에서 새로고침",
    "api.lookup": "정산 조회",
    "api.task_id": "작업 ID",
    "api.task_batch": "작업 ID (쉼표로 구분)",
    "api.fetch_settlement": "정산 가져오기",
    "api.status_ok": "연결됨",
    "api.status_refreshed": "크레딧을 새로고침했습니다",
    "api.status_idle": "대기 중",
    "api.status_err": "오류",
    "api.sync_now": "동기화",
    "brand.title": "Karma Console",
    "nav.overview": "주문",
    "nav.center": "결제 허브",
    "nav.tasks": "작업",
    "nav.receipts": "영수증",
    "nav.bills": "청구",
    "nav.disputes": "분쟁",
    "nav.identity": "신원 · 인증",
    "nav.auth": "인증",
    "nav.settings": "설정",
    "nav.agents": "에이전트",
    "sub.orders.buy": "내가 사는 주문",
    "sub.orders.sell": "내가 파는 주문",
    "ord.title": "주문 보드",
    "ord.note": "각 레인은 하나의 단계입니다: 대기 → 실행 중 → 확인 대기 → 분쟁 중. 확정된 주문은 분쟁 기간이 끝나면 이 보드에서 사라지고, 이력은 결제와 청구에 남습니다.",
    "ord.all": "전체",
    "ord.buy": "구매",
    "ord.sell": "판매",
    "ord.refresh": "새로고침",
    "sub.center.out": "지출",
    "sub.center.in": "수입",
    "sub.center.confirm": "확인 대기",
    "sub.center.dispute": "분쟁 중",
    "sub.center.new": "새 결제",
    "sub.tasks.flow": "정산 흐름",
    "sub.identity.master": "메인 아이덴티티",
    "sub.identity.verify": "본인 확인",
    "sub.identity.subs": "하위 아이덴티티",
    "sub.identity.money": "자금이 있는 곳",
    "sub.agents.wizard": "권한 부여 마법사",
    "sub.agents.mine": "내 에이전트",
    "sub.agents.handoff": "인계",
    "sub.agents.connect": "에이전트 연결",
    "sub.agents.pair": "페어링",
    "side.rule_title": "자금 안전 규칙",
    "side.rule_body": "관리자는 일시 중지만 할 수 있으며 원장 조작이나 출금은 불가능합니다. 모든 크레딧은 USDC와 1:1로 고정됩니다.",
    "id.current": "현재 아이덴티티",
    "id.status": "정상",
    "id.buyer_sub": "구매자 하위 ID",
    "id.seller_sub": "판매자 하위 ID",
    "top.sub": "아이덴티티 전환",
    "top.export": "기록 내보내기",
    "top.lock": "잠금 늘리기",
    "scope.master": "메인 ID",
    "scope.active": "보는 중",
    "scope.master_all": "메인 (전체)",
    "scope.none": "연결되지 않음",
    "scope.empty": "하위 아이덴티티가 없습니다. 신원 페이지에서 만드세요.",
    "page.overview.title": "주문",
    "page.overview.sub": "모든 주문의 현재 위치. 확정된 주문은 분쟁 기간이 끝나면 물러납니다.",
    "page.center.title": "결제 허브",
    "page.center.sub": "하나의 아이덴티티가 작업에 따라 결제도 수취도 할 수 있습니다.",
    "page.tasks.title": "작업",
    "page.tasks.sub": "진행 상황, 영수증, 책임, 정산.",
    "page.receipts.title": "영수증",
    "page.receipts.sub": "실행 영수증, 증거 해시, 런타임 로그.",
    "page.bills.title": "청구",
    "page.bills.sub": "아이덴티티 소유자만 볼 수 있는 내부 청구 크레딧 상태.",
    "page.disputes.title": "분쟁",
    "page.disputes.sub": "증거, 동결 자금, 중재.",
    "page.market.title": "스킬 마켓",
    "page.market.sub": "유료 API 등록 및 호출",
    "page.reviews.title": "심사 데스크",
    "page.reviews.sub": "법인 · 개발자 · 역할 프로필 KYC를 한곳에서. 기계 판정 결과도 함께 표시합니다.",
    "nav.reviews": "심사 데스크",
    "page.identity.title": "신원 · 인증",
    "page.identity.sub": "한 번만 본인 확인(ID + 셀피)을 하고, 에이전트마다 카드를 발급하세요.",
    "page.auth.title": "인증",
    "page.auth.sub": "지갑을 연결하고 아이덴티티 카드를 받으세요.",
    "page.agents.title": "에이전트 온보딩",
    "page.agents.sub": "아이덴티티 카드 하나로 어떤 에이전트 인프라에도 연결됩니다.",
    "page.settings.title": "설정",
    "page.settings.sub": "안전, 영수증 규칙, 정산, 개인정보, 웹훅.",
    "m.locked": "잠긴 USDC",
    "m.locked_hint": "온체인 담보",
    "m.available": "사용 가능 크레딧",
    "m.available_hint": "바우처를 만들 수 있습니다",
    "m.exec": "실행 중",
    "m.exec_hint": "진행 중인 작업으로 동결",
    "m.pending": "영수증 대기",
    "m.pending_hint": "접수됨 / 정산 대기",
    "m.dispute": "분쟁 보류",
    "m.dispute_hint": "중재 대기 중",
    "quick.title": "빠른 작업",
    "quick.desc": "하나의 아이덴티티가 작업에 따라 결제도 수취도 할 수 있습니다.",
    "quick.pay": "결제 인증 만들기",
    "quick.pay_desc": "일회용 바우처를 발급하면 판매자가 확인하고 시작합니다.",
    "quick.receive": "결제 인증 확인",
    "quick.receive_desc": "구매자 바우처를 입력해 잠긴 크레딧을 확인합니다.",
    "quick.receipt": "영수증 제출",
    "quick.receipt_desc": "증거 해시, 런타임 로그 해시, 진행 상황을 업로드합니다.",
    "quick.dispute": "분쟁 처리",
    "quick.dispute_desc": "증거를 제출하고, 합의를 수락하거나 중재를 요청합니다.",
    "flow.title": "책임 흐름",
    "flow.desc": "책임이 생기기 전에는 유연하게, 생긴 뒤에는 변경 불가.",
    "flow.locked": "USDC 잠금",
    "flow.locked_desc": "USDC를 Vault에 잠그면 내부 크레딧이 발행됩니다.",
    "flow.frozen": "작업 크레딧 동결",
    "flow.frozen_desc": "진행 중인 크레딧은 다시 부여할 수 없습니다.",
    "flow.receipt": "영수증 확인 대기",
    "flow.receipt_desc": "실행 영수증을 제출했습니다. 검증 또는 구매자 확인을 기다립니다.",
    "flow.settle": "정산 시 소멸",
    "flow.settle_desc": "정산 시 해당 내부 크레딧은 소각됩니다.",
    "preview.title": "API 데이터 미리보기",
    "preview.desc": "GET /v1/settlement/{task_id} 가 JSON을 반환합니다 (API 키 필요).",
    "tasks.title": "대기 중 작업",
    "tasks.desc": "API를 통해 작업 ID 목록에서 자동으로 채워집니다.",
    "tasks.view_all": "전체 보기",
    "th.task": "작업",
    "th.role": "역할",
    "th.counterparty": "상대방",
    "th.amount": "금액",
    "th.progress": "진행 상황",
    "th.status": "상태",
    "th.next": "다음 단계",
    "th.receipts": "영수증",
    "center.payable": "결제 가능 크레딧",
    "center.payable_hint": "바우처를 만들 수 있습니다",
    "center.issued": "발급된 인증",
    "center.issued_hint": "보류 / 진행 중",
    "center.receivable": "수취 가능",
    "center.receivable_hint": "영수증을 제출할 수 있습니다",
    "center.settleable": "정산 가능",
    "center.settleable_hint": "지급을 요청할 수 있습니다",
    "center.fee": "프로토콜 수수료 예상",
    "center.fee_hint": "정산 시 차감됩니다",
    "pay.title": "결제하고 싶습니다",
    "pay.desc": "일회용 인증을 만들면 판매자가 확인해 크레딧을 잠급니다.",
    "pay.seller_id": "판매자 Karma ID",
    "pay.amount": "금액 (USDC)",
    "pay.validity": "유효 기간",
    "pay.24h": "24시간",
    "pay.48h": "48시간",
    "pay.7d": "7일",
    "pay.task_desc": "작업 설명",
    "pay.task_desc_ph": "작업을 설명하세요…",
    "pay.notice": "판매자가 수락하면 해당 크레딧이 잠깁니다.",
    "pay.btn": "결제 바우처 생성",
    "recv.title": "수취하고 싶습니다",
    "recv.desc": "구매자 바우처를 입력하고 시작 전에 크레딧이 잠겼는지 확인하세요.",
    "recv.voucher": "구매자 바우처",
    "recv.btn": "인증 확인",
    "recv.mode": "수락 모드",
    "recv.mode1": "수락 후 즉시 시작",
    "recv.mode2": "수동 시작 대기",
    "recv.mode3": "Agent Runtime으로 자동 시작",
    "recv.accept": "수락하고 작업 시작",
    "task.page_title": "작업 실행",
    "task.page_desc": "위의 정산 조회로 실제 SettlementState를 가져올 수 있습니다.",
    "task.new_auth": "새 결제 인증",
    "task.settle_ops": "정산 운영",
    "task.history": "상태 전이 이력",
    "task.history_desc": "최근 50건의 정산 상태 변경.",
    "receipt.submit_title": "실행 영수증 제출",
    "receipt.submit_desc": "영수증은 작업, 아이덴티티, 증거 해시, 로그 해시, 서명을 묶습니다.",
    "receipt.task_id": "작업 ID",
    "receipt.evidence": "증거 해시",
    "receipt.log": "런타임 로그 해시",
    "receipt.output": "출력 다이제스트",
    "receipt.btn": "영수증 제출",
    "receipt.list_title": "영수증 목록",
    "receipt.list_desc": "작업 ID를 입력하면 해당 작업의 모든 영수증을 불러옵니다.",
    "receipt.load": "불러오기",
    "bills.export": "CSV 내보내기",
    "bills.th.time": "시간",
    "bills.th.dir": "방향",
    "bills.th.task": "작업",
    "bills.th.counter": "상대방",
    "bills.th.amount": "금액",
    "bills.th.result": "정산 결과",
    "bills.th.status": "상태",
    "bills.empty": "작업 ID를 설정하면 청구 데이터가 자동으로 채워집니다.",
    "disp.frozen": "분쟁 보류",
    "disp.frozen_hint": "자금 동결됨",
    "disp.mine": "내 조치 필요",
    "disp.mine_hint": "증거를 제출해야 합니다",
    "disp.arb": "중재 중",
    "disp.arb_hint": "판정 대기 중",
    "disp.handle_title": "분쟁 처리",
    "disp.handle_desc": "분쟁 중에는 자금이 동결되고, 판정 후 자동 실행됩니다.",
    "disp.th.task": "작업",
    "disp.th.counter": "상대방",
    "disp.th.amount": "금액",
    "disp.th.reason": "사유",
    "disp.th.status": "상태",
    "disp.th.action": "조치",
    "id.main_title": "메인 아이덴티티",
    "id.main_desc": "Karma 아이덴티티 SBT는 양도와 거래가 불가능합니다.",
    "id.api_status": "API 상태",
    "id.api_version": "API 버전",
    "id.change_num": "표시 번호 변경",
    "id.bind_legal": "법적 신원 연결",
    "id.safety_title": "안전 모드",
    "id.safety_desc": "Runtime 안전 모드는 전역 자금 작업 권한을 제어합니다.",
    "id.buyer_sub_desc": "결제 작업용",
    "id.seller_sub_desc": "수취 작업용",
    "id.enabled": "사용",
    "set.safety": "자금 안전",
    "set.safety_desc": "작업별 · 일일 한도와 해제 확인 방식을 설정합니다.",
    "set.receipt_rules": "영수증 규칙",
    "set.receipt_rules_desc": "API / MCP / Agent 작업을 어떻게 자동 검증할지 정합니다.",
    "set.settle_pref": "정산 설정",
    "set.settle_pref_desc": "완료 시 자동 정산 또는 수동 확인.",
    "set.privacy": "개인정보 설정",
    "set.privacy_desc": "표시 ID 순환, 하위 ID 사용, 증거 공개 범위.",
    "set.notify": "알림",
    "set.notify_desc": "작업 수락, 영수증 제출, 분쟁, 정산을 알립니다.",
    "set.webhook": "개발자 웹훅",
    "set.webhook_desc": "에이전트 플랫폼이 작업 상태, 영수증 검증, 정산 결과를 자동으로 받습니다.",
    "set.ai_title": "AI 에이전트 자동 인증 센터",
    "set.ai_desc": "AI 에이전트가 자동으로 인증을 요청하고, 영수증을 제출하고, 작업 상태를 동기화할 수 있는지 제어합니다.",
    "set.ai_toggle": "AI 에이전트 인증 사용",
    "set.ai_toggle_desc": "AI는 설정한 한도, 작업 유형, 위험 규칙 범위 안에서만 동작합니다.",
    "set.ai_status": "현재 상태",
    "set.ai_off": "꺼짐",
    "set.ai_on": "켜짐",
    "set.ai_rules": "AI 안전 경계",
    "set.ai_max_single": "AI 자동 인증 1건 최대 금액",
    "set.ai_max_daily": "AI 자동 인증 일일 최대 합계",
    "set.ai_scope": "AI 자동 운영 범위",
    "set.ai_scope1": "자동 인증 + 자동 영수증 + 실시간 동기화",
    "set.ai_scope2": "영수증 자동 제출만",
    "set.ai_scope3": "실시간 동기화만",
    "set.ai_scope4": "모두 사용 안 함",
    "set.ai_receipt_mode": "실행 영수증 모드",
    "set.ai_receipt1": "Agent Runtime 자동 제출",
    "set.ai_receipt2": "MCP Trace 자동 제출",
    "set.ai_receipt3": "API 영수증 자동 제출",
    "set.ai_receipt4": "수동 제출",
    "set.ai_risk": "고위험 작업 확인",
    "set.ai_risk1": "한도 초과 / 미확인 Agent / 외부 컨트랙트는 수동 확인",
    "set.ai_risk2": "모든 AI 인증에 수동 확인 필요",
    "set.ai_risk3": "한도 내에서는 완전 자동",
    "set.ai_sync": "실시간 상태 동기화",
    "set.ai_sync1": "켜짐: 작업, 영수증, 진행 상황, 정산, 분쟁 동기화",
    "set.ai_sync2": "꺼짐",
    "set.ai_warn": "안전 경계: AI 에이전트는 인증 요청과 영수증 제출만 할 수 있습니다. 규칙을 넘는 작업은 수동 확인이 필요합니다.",
    "set.ai_save": "AI 에이전트 규칙 저장",
    "sync.title": "작업 동기화",
    "sync.desc": "작업 ID(쉼표로 구분)를 입력하면 API에서 정산 데이터를 자동으로 가져옵니다.",
    "auto_sync": "자동 동기화",
    "last_sync": "마지막",
  };

  const esLatam = {
    "api.lang": "Idioma",
    "api.base": "URL base de la API",
    "api.key": "Clave de API (X-Karma-Api-Key)",
    "api.identity": "ID de identidad",
    "api.save": "Guardar conexión",
    "api.refresh": "Actualizar desde la API",
    "api.lookup": "Consulta de liquidación",
    "api.task_id": "ID de tarea",
    "api.task_batch": "IDs de tarea (separados por coma)",
    "api.fetch_settlement": "Obtener liquidación",
    "api.status_ok": "Conectado",
    "api.status_refreshed": "Créditos actualizados",
    "api.status_idle": "Inactivo",
    "api.status_err": "Error",
    "api.sync_now": "Sincronizar",
    "brand.title": "Karma Console",
    "nav.overview": "Órdenes",
    "nav.center": "Centro de pagos",
    "nav.tasks": "Tareas",
    "nav.receipts": "Recibos",
    "nav.bills": "Facturas",
    "nav.disputes": "Disputas",
    "nav.identity": "Identidad y KYC",
    "nav.auth": "Autenticación",
    "nav.settings": "Ajustes",
    "nav.agents": "Agentes",
    "sub.orders.buy": "Órdenes que compro",
    "sub.orders.sell": "Órdenes que vendo",
    "ord.title": "Tablero de órdenes",
    "ord.note": "Cada carril es una etapa: en espera → en ejecución → por confirmar → en disputa. Las órdenes cerradas salen de este tablero cuando termina la ventana de disputa; el historial queda en Pagos y Facturas.",
    "ord.all": "Todas",
    "ord.buy": "Compro",
    "ord.sell": "Vendo",
    "ord.refresh": "Actualizar",
    "sub.center.out": "Salidas",
    "sub.center.in": "Entradas",
    "sub.center.confirm": "Por confirmar",
    "sub.center.dispute": "En disputa",
    "sub.center.new": "Nuevo pago",
    "sub.tasks.flow": "Flujo de liquidación",
    "sub.identity.master": "Identidad principal",
    "sub.identity.verify": "Verificación",
    "sub.identity.subs": "Subidentidades",
    "sub.identity.money": "Dónde vive el dinero",
    "sub.agents.wizard": "Asistente de autorización",
    "sub.agents.mine": "Mis agentes",
    "sub.agents.handoff": "Traspaso",
    "sub.agents.connect": "Conectar un agente",
    "sub.agents.pair": "Emparejamiento",
    "side.rule_title": "Reglas de seguridad de fondos",
    "side.rule_body": "Los administradores solo pueden pausar: no pueden alterar el libro ni retirar fondos. Todos los créditos se mantienen 1:1 con USDC.",
    "id.current": "Identidad actual",
    "id.status": "Correcto",
    "id.buyer_sub": "Sub-ID de comprador",
    "id.seller_sub": "Sub-ID de vendedor",
    "top.sub": "Cambiar identidad",
    "top.export": "Exportar registros",
    "top.lock": "Aumentar bloqueo",
    "scope.master": "ID principal",
    "scope.active": "Viendo como",
    "scope.master_all": "Principal (todo)",
    "scope.none": "sin conexión",
    "scope.empty": "Aún no hay subidentidades: crea una en la página de Identidad.",
    "page.overview.title": "Órdenes",
    "page.overview.sub": "Dónde está cada orden ahora mismo. Las órdenes cerradas se apartan al terminar la ventana de disputa.",
    "page.center.title": "Centro de pagos",
    "page.center.sub": "Una misma identidad puede pagar y cobrar según la tarea.",
    "page.tasks.title": "Tareas",
    "page.tasks.sub": "Progreso, recibos, responsabilidad y liquidación.",
    "page.receipts.title": "Recibos",
    "page.receipts.sub": "Recibos de ejecución, hashes de evidencia, logs de runtime.",
    "page.bills.title": "Facturas",
    "page.bills.sub": "Estado interno del crédito de facturación, visible solo para el titular de la identidad.",
    "page.disputes.title": "Disputas",
    "page.disputes.sub": "Evidencia, fondos congelados, arbitraje.",
    "page.market.title": "Mercado de habilidades",
    "page.market.sub": "Publica y consume APIs facturables",
    "page.reviews.title": "Mesa de revisión",
    "page.reviews.sub": "Colas de KYC de empresas, desarrolladores y perfiles de rol en un solo lugar, con el veredicto automático a la vista.",
    "nav.reviews": "Mesa de revisión",
    "page.identity.title": "Identidad y KYC",
    "page.identity.sub": "Verifica una sola vez (documento + selfi) y luego emite una tarjeta por agente.",
    "page.auth.title": "Autenticación",
    "page.auth.sub": "Conecta tu billetera y reclama tu tarjeta de identidad.",
    "page.agents.title": "Alta de agentes",
    "page.agents.sub": "Una tarjeta de identidad, cualquier infraestructura de agentes.",
    "page.settings.title": "Ajustes",
    "page.settings.sub": "Seguridad, reglas de recibos, liquidación, privacidad, webhooks.",
    "m.locked": "USDC bloqueado",
    "m.locked_hint": "Anclaje on-chain",
    "m.available": "Créditos disponibles",
    "m.available_hint": "Puede crear vales",
    "m.exec": "En ejecución",
    "m.exec_hint": "Congelado por tareas activas",
    "m.pending": "Recibo pendiente",
    "m.pending_hint": "Aceptado / pendiente de liquidación",
    "m.dispute": "Retención por disputa",
    "m.dispute_hint": "Esperando arbitraje",
    "quick.title": "Acciones rápidas",
    "quick.desc": "Una misma identidad puede pagar o cobrar según la tarea.",
    "quick.pay": "Crear autorización de pago",
    "quick.pay_desc": "Emite un vale de un solo uso; el vendedor lo verifica para empezar.",
    "quick.receive": "Verificar autorización de pago",
    "quick.receive_desc": "Ingresa el vale del comprador para confirmar los créditos bloqueados.",
    "quick.receipt": "Enviar recibo",
    "quick.receipt_desc": "Sube el hash de evidencia, el hash del log de runtime y el progreso.",
    "quick.dispute": "Gestionar disputa",
    "quick.dispute_desc": "Presenta evidencia, acepta una resolución o pide arbitraje.",
    "flow.title": "Flujo de responsabilidad",
    "flow.desc": "Flexible antes de la responsabilidad; inmutable después.",
    "flow.locked": "USDC bloqueado",
    "flow.locked_desc": "El USDC se bloquea en la bóveda y se generan créditos internos.",
    "flow.frozen": "Créditos de tarea congelados",
    "flow.frozen_desc": "Los créditos en curso no pueden reautorizarse.",
    "flow.receipt": "Recibo pendiente de confirmación",
    "flow.receipt_desc": "Recibo de ejecución enviado; pendiente de verificación o confirmación del comprador.",
    "flow.settle": "Se destruyen al liquidar",
    "flow.settle_desc": "Al liquidar, los créditos internos correspondientes se queman.",
    "preview.title": "Vista previa de datos de la API",
    "preview.desc": "GET /v1/settlement/{task_id} devuelve JSON (requiere clave de API).",
    "tasks.title": "Acciones pendientes",
    "tasks.desc": "Se completa automáticamente desde la lista de IDs de tarea vía API.",
    "tasks.view_all": "Ver todo",
    "th.task": "Tarea",
    "th.role": "Rol",
    "th.counterparty": "Contraparte",
    "th.amount": "Importe",
    "th.progress": "Progreso",
    "th.status": "Estado",
    "th.next": "Siguiente paso",
    "th.receipts": "Recibos",
    "center.payable": "Créditos pagables",
    "center.payable_hint": "Puede crear vales",
    "center.issued": "Autorizaciones emitidas",
    "center.issued_hint": "Pendientes / en curso",
    "center.receivable": "Por cobrar",
    "center.receivable_hint": "Puede enviar recibos",
    "center.settleable": "Liquidable",
    "center.settleable_hint": "Puede solicitar el pago",
    "center.fee": "Comisión estimada del protocolo",
    "center.fee_hint": "Se descuenta al liquidar",
    "pay.title": "Quiero pagar",
    "pay.desc": "Crea una autorización de un solo uso; el vendedor la verifica para bloquear los créditos.",
    "pay.seller_id": "Karma ID del vendedor",
    "pay.amount": "Importe (USDC)",
    "pay.validity": "Validez",
    "pay.24h": "24 horas",
    "pay.48h": "48 horas",
    "pay.7d": "7 días",
    "pay.task_desc": "Descripción de la tarea",
    "pay.task_desc_ph": "Describe la tarea...",
    "pay.notice": "Cuando el vendedor acepte, se bloquearán los créditos correspondientes.",
    "pay.btn": "Generar vale de pago",
    "recv.title": "Quiero cobrar",
    "recv.desc": "Ingresa el vale del comprador y confirma que los créditos están bloqueados antes de empezar.",
    "recv.voucher": "Vale del comprador",
    "recv.btn": "Verificar autorización",
    "recv.mode": "Modo de aceptación",
    "recv.mode1": "Empezar al aceptar",
    "recv.mode2": "Esperar inicio manual",
    "recv.mode3": "Inicio automático vía Agent Runtime",
    "recv.accept": "Aceptar e iniciar la tarea",
    "task.page_title": "Ejecución de tarea",
    "task.page_desc": "Usa la consulta de liquidación de arriba para obtener el SettlementState real.",
    "task.new_auth": "Nueva autorización de pago",
    "task.settle_ops": "Operaciones de liquidación",
    "task.history": "Historial de transiciones de estado",
    "task.history_desc": "Los últimos 50 cambios de estado de liquidación.",
    "receipt.submit_title": "Enviar recibo de ejecución",
    "receipt.submit_desc": "Los recibos deben vincular tarea, identidad, hash de evidencia, hash de log y firma.",
    "receipt.task_id": "ID de tarea",
    "receipt.evidence": "Hash de evidencia",
    "receipt.log": "Hash del log de runtime",
    "receipt.output": "Digest de salida",
    "receipt.btn": "Enviar recibo",
    "receipt.list_title": "Lista de recibos",
    "receipt.list_desc": "Ingresa un ID de tarea para cargar todos sus recibos.",
    "receipt.load": "Cargar",
    "bills.export": "Exportar CSV",
    "bills.th.time": "Hora",
    "bills.th.dir": "Dirección",
    "bills.th.task": "Tarea",
    "bills.th.counter": "Contraparte",
    "bills.th.amount": "Importe",
    "bills.th.result": "Resultado de liquidación",
    "bills.th.status": "Estado",
    "bills.empty": "Configura IDs de tarea para completar los datos de facturación.",
    "disp.frozen": "Retención por disputa",
    "disp.frozen_hint": "Fondos bloqueados",
    "disp.mine": "Requiere mi acción",
    "disp.mine_hint": "Hay que presentar evidencia",
    "disp.arb": "En arbitraje",
    "disp.arb_hint": "Esperando el laudo",
    "disp.handle_title": "Gestión de disputas",
    "disp.handle_desc": "Los fondos se congelan durante la disputa y se ejecutan automáticamente tras el laudo.",
    "disp.th.task": "Tarea",
    "disp.th.counter": "Contraparte",
    "disp.th.amount": "Importe",
    "disp.th.reason": "Motivo",
    "disp.th.status": "Estado",
    "disp.th.action": "Acción",
    "id.main_title": "Identidad principal",
    "id.main_desc": "El SBT de identidad de Karma no es transferible ni negociable.",
    "id.api_status": "Estado de la API",
    "id.api_version": "Versión de la API",
    "id.change_num": "Cambiar número visible",
    "id.bind_legal": "Vincular identidad legal",
    "id.safety_title": "Modo de seguridad",
    "id.safety_desc": "El modo de seguridad del Runtime controla los permisos globales de operación de fondos.",
    "id.buyer_sub_desc": "Para tareas de pago",
    "id.seller_sub_desc": "Para tareas de cobro",
    "id.enabled": "Activo",
    "set.safety": "Seguridad de fondos",
    "set.safety_desc": "Define límites por tarea y diarios, y el método de confirmación de liberación.",
    "set.receipt_rules": "Reglas de recibos",
    "set.receipt_rules_desc": "Define cómo se verifican automáticamente las tareas de API / MCP / Agente.",
    "set.settle_pref": "Preferencia de liquidación",
    "set.settle_pref_desc": "Liquidación automática al completar o confirmación manual.",
    "set.privacy": "Privacidad",
    "set.privacy_desc": "Rotación del ID visible, uso de sub-IDs y divulgación de evidencia.",
    "set.notify": "Notificaciones",
    "set.notify_desc": "Avisos de aceptación de tareas, envío de recibos, disputas y liquidación.",
    "set.webhook": "Webhook para desarrolladores",
    "set.webhook_desc": "La plataforma de agentes recibe automáticamente el estado de la tarea, la verificación del recibo y el resultado de la liquidación.",
    "set.ai_title": "Centro de autorización automática de agentes de IA",
    "set.ai_desc": "Controla si los agentes de IA pueden solicitar autorizaciones, enviar recibos y sincronizar el estado de las tareas por sí solos.",
    "set.ai_toggle": "Habilitar autorización de agentes de IA",
    "set.ai_toggle_desc": "La IA solo puede operar dentro de tus límites, tipos de tarea y reglas de riesgo.",
    "set.ai_status": "Estado actual",
    "set.ai_off": "APAGADO",
    "set.ai_on": "ENCENDIDO",
    "set.ai_rules": "Límites de seguridad de la IA",
    "set.ai_max_single": "Importe máximo por autorización automática de la IA",
    "set.ai_max_daily": "Total diario máximo de autorizaciones automáticas de la IA",
    "set.ai_scope": "Alcance de operación automática de la IA",
    "set.ai_scope1": "Autorización automática + recibos automáticos + sincronización en tiempo real",
    "set.ai_scope2": "Solo envío automático de recibos",
    "set.ai_scope3": "Solo sincronización en tiempo real",
    "set.ai_scope4": "Todo deshabilitado",
    "set.ai_receipt_mode": "Modo de recibo de ejecución",
    "set.ai_receipt1": "Envío automático por Agent Runtime",
    "set.ai_receipt2": "Envío automático por MCP Trace",
    "set.ai_receipt3": "Envío automático de recibo por API",
    "set.ai_receipt4": "Envío manual",
    "set.ai_risk": "Confirmación de tareas de alto riesgo",
    "set.ai_risk1": "Confirmación manual si supera el límite / agente desconocido / contrato externo",
    "set.ai_risk2": "Toda autorización de la IA requiere confirmación manual",
    "set.ai_risk3": "Totalmente automático dentro de los límites",
    "set.ai_sync": "Sincronización de estado en tiempo real",
    "set.ai_sync1": "Activada: tareas, recibos, progreso, liquidación y disputas",
    "set.ai_sync2": "Desactivada",
    "set.ai_warn": "Límite de seguridad: los agentes de IA solo pueden solicitar autorizaciones y enviar recibos; cualquier cosa que supere las reglas requiere confirmación manual.",
    "set.ai_save": "Guardar reglas de agentes de IA",
    "sync.title": "Sincronización de tareas",
    "sync.desc": "Ingresa IDs de tarea (separados por coma) para obtener los datos de liquidación desde la API.",
    "auto_sync": "Sincronización automática",
    "last_sync": "Última",
  };

  /* 阿根廷 / 萨尔瓦多同属拉美西班牙语，目前两份内容一致；
     地区差异（货币、支付通道、KYC 措辞）直接写进对应对象即可。 */
  const esAR = Object.assign({}, esLatam, {
  });

  const esSV = Object.assign({}, esLatam, {
  });

  const PACKS = {
    en: en,
    "zh-CN": zhCN,
    ja: ja,
    ko: ko,
    "es-AR": esAR,
    "es-SV": esSV,
  };

  /**
   * Languages the picker offers. Every code here has a pack that covers all
   * 256 keys, so none of them can leave the page half-translated.
   */
  const SHIPPED_LANGS = ["zh-CN", "en", "ja", "ko", "es-AR", "es-SV"];

  /** Endonyms for every pack, so the control never shows a bare locale code.
   *  Keep them short: the picker keeps the width it always had, so a long
   *  label would widen the box and push it into the connect-wallet button. */
  /** 语言自称，选择器里永远不显示裸的语言代码；宁可短一点，
   *  也不能把语言选择框撑宽。 */
  const LANG_LABELS = {
    "zh-CN": "\u4e2d\u6587",
    en: "English",
    ja: "\u65e5\u672c\u8a9e",
    ko: "\ud55c\uad6d\uc5b4",
    "es-AR": "Espa\u00f1ol (AR)",
    "es-SV": "Espa\u00f1ol (SV)",
  };

  /**
   * 浏览器语言标签 → 我们的语言包；没有对应包时返回 null。
   *
   * 西班牙语按地区分两套：
   *   es-AR / es-UY / es-PY → es-AR（voseo 区，说「Conectá」）
   *   其余 es-* 与裸 es      → es-SV（tuteo 区：拉美多数国家 + 西班牙）
   * 以前把所有 es-* 都给了 es-AR，墨西哥用户会看到阿根廷语，很出戏。
   */
  function mapBrowserTag(tag) {
    const t = String(tag == null ? "" : tag).toLowerCase().replace(/_/g, "-").trim();
    if (!t) return null;
    if (t === "zh" || t.indexOf("zh-") === 0) return "zh-CN";
    if (t === "ja" || t.indexOf("ja-") === 0) return "ja";
    if (t === "ko" || t.indexOf("ko-") === 0) return "ko";
    if (t === "en" || t.indexOf("en-") === 0) return "en";
    if (t === "es" || t.indexOf("es-") === 0) {
      const region = t.split("-")[1] || "";
      if (region === "ar" || region === "uy" || region === "py") return "es-AR";
      return "es-SV";
    }
    return null;
  }

  /**
   * 从浏览器语言偏好里挑一门我们有的；都没有就回落英文。
   *
   * 看的是整串 navigator.languages（按优先级排），不是只看 navigator.language：
   * 「首选法语、次选日语」的用户，只看第一位会被错判成英文。
   * 结果缓存一次 —— 一次会话里浏览器语言不会变。
   */
  let detectedLang = null;
  function detectFromBrowser() {
    if (detectedLang) return detectedLang;
    let list = [];
    try {
      if (navigator.languages && navigator.languages.length) {
        list = Array.prototype.slice.call(navigator.languages);
      }
    } catch (_) {}
    try {
      if (navigator.language) list.push(navigator.language);
    } catch (_) {}
    for (let i = 0; i < list.length; i += 1) {
      const hit = mapBrowserTag(list[i]);
      if (hit && PACKS[hit]) { detectedLang = hit; return hit; }
    }
    detectedLang = "en";
    return detectedLang;
  }

  /** 显式选择优先（存过就永远听用户的）；没存过才跟随浏览器语言。 */
  function getLang() {
    try {
      const s = localStorage.getItem(STORAGE_KEY);
      if (s && PACKS[s]) return s;
    } catch (_) {}
    return detectFromBrowser();
  }

  /**
   * 把当前语言写到 <html lang>。
   *
   * 探测来的语言以前不会写进去 —— 界面已经是日文了，标记还停在 zh-CN，
   * 读屏软件、翻译插件、字体回退全按中文处理。每次应用文案时都同步一次。
   */
  function syncHtmlLang() {
    try {
      const want = getLang();
      if (document.documentElement.lang !== want) document.documentElement.lang = want;
    } catch (_) {}
  }

  function setLang(code) {
    if (!PACKS[code]) return;
    try {
      localStorage.setItem(STORAGE_KEY, code);
    } catch (_) {}
    document.documentElement.lang = code;
  }

  /**
   * 取译文。
   *
   * zh 是调用点自带的中文原文（可选）：扩展包里没有这条键时会回落到它，
   * 所以「还没翻译」永远不会变成把键名打到屏幕上。
   * 查找顺序：扩展包(当前语言) → 核心包(当前语言) → 核心包(en) → 原文 → 键名。
   */
  function t(key, zh) {
    const L = getLang();
    const ext = EXT[L];
    if (ext && ext[key] != null) return ext[key];
    if (PACKS[L] && PACKS[L][key] != null) return PACKS[L][key];
    if (L !== "en" && PACKS.en[key] != null) return PACKS.en[key];
    if (zh != null) {
      const fromPhrase = lookup(zh);
      return fromPhrase == null ? zh : fromPhrase;
    }
    const bySource = lookup(key);
    return bySource == null ? key : bySource;
  }

  function applyCyberI18n() {
    syncHtmlLang();
    document.querySelectorAll("[data-i18n]").forEach(function (el) {
      const key = el.getAttribute("data-i18n");
      if (!key) return;
      if (el.tagName === "INPUT" || el.tagName === "TEXTAREA") {
        if (el.hasAttribute("data-i18n-placeholder")) {
          const pk0 = el.getAttribute("data-i18n-placeholder");
          if (!el.hasAttribute("data-i18n-ph-src")) {
            el.setAttribute("data-i18n-ph-src", el.getAttribute("placeholder") || "");
          }
          el.setAttribute("placeholder", t(pk0, el.getAttribute("data-i18n-ph-src")));
        } else {
          if (!el.hasAttribute("data-i18n-src")) {
            el.setAttribute("data-i18n-src", el.value);
          }
          el.value = t(key, el.getAttribute("data-i18n-src"));
        }
        return;
      }
      // 页面里的中文原文就是 zh 兜底；只在首次应用时抓一次，避免切来切去丢原文。
      if (!el.hasAttribute("data-i18n-src")) {
        el.setAttribute("data-i18n-src", el.textContent);
      }
      el.textContent = t(key, el.getAttribute("data-i18n-src"));
    });
    document.querySelectorAll("[data-i18n-placeholder]").forEach(function (el) {
      const pk = el.getAttribute("data-i18n-placeholder");
      if (pk && (el.tagName === "INPUT" || el.tagName === "TEXTAREA")) {
        if (!el.hasAttribute("data-i18n-ph-src")) {
          el.setAttribute("data-i18n-ph-src", el.getAttribute("placeholder") || "");
        }
        el.setAttribute("placeholder", t(pk, el.getAttribute("data-i18n-ph-src")));
      }
    });
    // 核心包管不到的地方（页面里写死的中文、脚本拼出来的 HTML）交给源文案表。
    applyPhrase();
  }

  /* ------------------------------------------------------------------
   * 源文案表（phrase pack）
   *
   * 页面和脚本里写的是中文原文，这里按「中文原文 -> 译文」查表，查不到就原样留着。
   * 布局：<i18n 脚本所在目录>/i18n-phrase/<locale>.js
   *   window.CYBER_I18N_PHRASE = window.CYBER_I18N_PHRASE || {};
   *   window.CYBER_I18N_PHRASE["ja"] = { "订单": "注文", "共 {0} 笔订单": "{0} 件の注文" };
   *
   * 带 {0} {1} 的条目按整段正则匹配，用来覆盖模板拼出来的句子（「共 3 笔订单」）。
   * 只有当前语言那一份会被加载；zh-CN 不需要 —— 中文就是页面里的原文。
   * ------------------------------------------------------------------ */
  const PHRASE = {};
  const PHRASE_NORM = {};
  const PATTERN = {};
  const EXT = {};

  /** 空白归一化：模板字符串拼出来的句子常常带换行和缩进。 */
  function normSpace(s) {
    return String(s).replace(/\s+/g, " ").trim();
  }

  let PHRASE_BASE = "scripts/i18n-phrase/";
  try {
    const cs = document.currentScript;
    if (cs && cs.src) PHRASE_BASE = cs.src.replace(/i18n-cyber\.js(\?.*)?$/, "") + "i18n-phrase/";
  } catch (_) {}

  /** 把带 {n} 的条目编译成正则；长的排前面，免得短条目先吃掉长句子。 */
  function compilePatterns(lang) {
    if (PATTERN[lang]) return;
    const pack = PHRASE[lang];
    if (!pack) return;
    const norm = {};
    Object.keys(pack).forEach(function (src) {
      const n = normSpace(src);
      if (norm[n] === undefined) norm[n] = pack[src];
    });
    PHRASE_NORM[lang] = norm;
    const list = [];
    Object.keys(pack).forEach(function (src) {
      if (src.indexOf("{") < 0) return;
      src = normSpace(src);
      let re = "";
      let i = 0;
      while (i < src.length) {
        const m = /^\{(\d+)\}/.exec(src.slice(i));
        if (m) {
          re += "([\\s\\S]+?)";
          i += m[0].length;
          continue;
        }
        re += src.charAt(i).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        i += 1;
      }
      list.push([new RegExp("^" + re + "$"), pack[src]]);
    });
    list.sort(function (a, b) { return b[0].source.length - a[0].source.length; });
    PATTERN[lang] = list;
  }

  /** 查一条中文原文在当前语言下的译文；没有就返回 null。 */
  function lookup(text) {
    return lookupDepth(text, 0);
  }

  /**
   * 模板参数里拆出来的分隔符：「A / B」「A、B」「A；B」都算。
   * 斜杠必须两边有空格 —— 否则「刷脸（正/左/右/抬/低 五个角度）」这种本身就带斜杠的术语
   * 会被切成碎片，反而更糟。
   */
  const ARG_SEP = /(\s+\/\s+|\s*[、；;]\s*)/;

  /**
   * 模板里抓到的参数也要翻一遍。
   *
   * 症状：「还差：连接钱包 / 证件正面 / …」
   * 外层模板已经翻成了「Still missing: {0}」，
   * 但 {0} 里的中文原样带了过去 —— 半英半中。
   *
   * 参数本身常常是拼出来的（一串项用分隔符连起来），
   * 所以先整段查，整段查不到再按分隔符拆开逐项查。
   * 不含中文的（订单号、钱包地址、数字）直接原样返回，绝不误伤。
   * depth 是防止模板套模板无限往下钻的剂量。
   */
  function substArg(text, depth) {
    const s0 = String(text == null ? "" : text);
    if (!s0 || !CJK_ONE.test(s0)) return s0;
    if (depth >= 2) return s0;
    const whole = lookupDepth(s0, depth + 1);
    if (whole != null) return whole;
    if (!ARG_SEP.test(s0)) return s0;
    const parts = s0.split(ARG_SEP);
    if (parts.length < 3) return s0;
    let changed = false;
    const out = parts.map(function (p) {
      if (!p || !CJK_ONE.test(p)) return p;
      const hit = lookupDepth(p, depth + 1);
      if (hit != null) { changed = true; return hit; }
      return p;
    });
    return changed ? out.join("") : s0;
  }

  function lookupDepth(text, depth) {
    if (text == null || text === "") return null;
    const L = getLang();
    if (L === "zh-CN") return null;
    const pack = PHRASE[L];
    if (pack && pack[text] != null) return pack[text];
    const key = normSpace(text);
    const norm = PHRASE_NORM[L];
    if (norm && norm[key] != null) return norm[key];
    const pats = PATTERN[L];
    if (pats) {
      for (let i = 0; i < pats.length; i += 1) {
        const m = pats[i][0].exec(key);
        if (m) {
          return pats[i][1].replace(/\{(\d+)\}/g, function (_, d) {
            return substArg(m[Number(d) + 1], depth);
          });
        }
      }
    }
    return null;
  }

  /**
   * 宽松版：按钮/标题常写成「🔗 连接钱包」「⚙ 连接设置」——
   * 两端的 emoji / ▤ / ⚙ / · 这类装饰符号不属于文案，去掉后再查一次。
   * 找不到就返回 null，由调用方决定怎么办。
   */
  function lookupLoose(text) {
    const t = String(text == null ? "" : text);
    let a = 0;
    let b = t.length;
    while (a < b && !CJK_ONE.test(t.charAt(a))) a += 1;
    while (b > a && !CJK_ONE.test(t.charAt(b - 1))) b -= 1;
    if (a >= b) return null;
    const core = t.slice(a, b);
    const hit = lookup(core);
    if (hit == null) return null;
    return t.slice(0, a) + hit + t.slice(b);
  }

  /** 供 JS 调用点使用：T("订单") -> 当前语言的译文（没有就返回中文原文）。 */
  function T(zh) {
    const src = zh == null ? "" : String(zh);
    const out = lookup(src);
    return out == null ? src : out;
  }

  /**
   * 模板版：Tf("共 {0} 单", 3) -> "3 orders"。
   * 句子是拼出来的（带数字/变量）时用它，整句才不会被拆成半中半英。
   */
  function Tf(zh) {
    let out = T(zh);
    for (let i = 1; i < arguments.length; i += 1) {
      const v = arguments[i];
      out = out.split("{" + (i - 1) + "}").join(v == null ? "" : String(v));
    }
    return out;
  }

  const SKIP_TAGS = { SCRIPT: 1, STYLE: 1, NOSCRIPT: 1, TEXTAREA: 1, CODE: 1, PRE: 1 };
  const CJK_ONE = /[\u4e00-\u9fff]/;
  const ATTRS = ["placeholder", "title", "aria-label", "alt"];
  const T_SRC = new WeakMap();
  const T_LAST = new WeakMap();
  const A_SRC = new WeakMap();
  const A_LAST = new WeakMap();
  let TITLE_SRC = null;

  /** data-i18n 覆盖过的元素交给核心包处理，别在这里被翻第二遍。 */
  function skipped(el) {
    let n = el;
    while (n && n.nodeType === 1) {
      // PRE/CODE 平时不翻（里面常是 JSON、签名原文这类数据）；
      // 明确标了 data-i18n-phrase 的除外 —— 那是给人看的一句提示文案。
      if (SKIP_TAGS[n.tagName] && !n.hasAttribute("data-i18n-phrase")) return true;
      if (n.hasAttribute("data-i18n-skip")) return true;
      if (n.hasAttribute("data-i18n") || n.hasAttribute("data-i18n-placeholder")) return true;
      n = n.parentElement;
    }
    return false;
  }

  /** 保留原文两端空白，只换中间那句。 */
  function replaceTrimmed(src, out) {
    const trimmed = src.trim();
    const at = src.indexOf(trimmed);
    if (at < 0) return out;
    return src.slice(0, at) + out + src.slice(at + trimmed.length);
  }

  function translateTextNode(node) {
    const el = node.parentElement;
    if (!el || skipped(el)) return;
    const raw = node.data;
    let src = T_SRC.get(node);
    if (src === undefined || T_LAST.get(node) !== raw) src = raw;
    T_SRC.set(node, src);
    const trimmed = src.trim();
    if (!trimmed) return;
    const out = lookup(trimmed);
    let want;
    if (out != null) want = replaceTrimmed(src, out);
    else {
      const loose = lookupLoose(src);
      want = loose == null ? src : loose;
    }
    if (node.data !== want) {
      T_LAST.set(node, want);
      node.data = want;
    }
  }

  /**
   * TEXTAREA 的正文不翻（里面是用户输入），但它的 placeholder 是界面文案，得翻。
   * 别的 SKIP_TAGS 连 placeholder 一起跳过。
   */
  function skippedAttrs(el) {
    let n = el;
    while (n && n.nodeType === 1) {
      if (SKIP_TAGS[n.tagName] && n.tagName !== "TEXTAREA" && !n.hasAttribute("data-i18n-phrase")) return true;
      if (n.hasAttribute("data-i18n-skip")) return true;
      if (n.hasAttribute("data-i18n") || n.hasAttribute("data-i18n-placeholder")) return true;
      n = n.parentElement;
    }
    return false;
  }

  function translateAttrs(el) {
    if (!el || el.nodeType !== 1 || skippedAttrs(el)) return;
    let list = ATTRS;
    if (el.tagName === "INPUT") {
      const type = (el.getAttribute("type") || "").toLowerCase();
      if (type === "button" || type === "submit" || type === "reset") list = ATTRS.concat(["value"]);
    }
    let srcs = A_SRC.get(el);
    if (!srcs) { srcs = {}; A_SRC.set(el, srcs); }
    let lasts = A_LAST.get(el);
    if (!lasts) { lasts = {}; A_LAST.set(el, lasts); }
    for (let i = 0; i < list.length; i += 1) {
      const a = list[i];
      if (!el.hasAttribute(a)) continue;
      const raw = el.getAttribute(a) || "";
      let src = srcs[a];
      if (src === undefined || lasts[a] !== raw) src = raw;
      srcs[a] = src;
      const trimmed = src.trim();
      if (!trimmed) continue;
      const out = lookup(trimmed);
      if (out == null) {
        const loose = lookupLoose(src);
        if (loose != null && raw !== loose) { lasts[a] = loose; el.setAttribute(a, loose); }
        continue;
      }
      const want = replaceTrimmed(src, out);
      if (raw !== want) {
        lasts[a] = want;
        el.setAttribute(a, want);
      }
    }
  }

  let observer = null;
  let queued = null;

  function flush() {
    const set = queued;
    queued = null;
    if (!set) return;
    set.forEach(function (node) {
      if (node && node.isConnected) applyPhrase(node);
    });
  }

  function schedule(node) {
    if (!node) return;
    if (!queued) {
      queued = new Set();
      if (typeof requestAnimationFrame === "function") requestAnimationFrame(flush);
      else setTimeout(flush, 16);
    }
    queued.add(node);
  }

  /** 新渲染出来的 DOM 也要跟着换语言，所以整棵子树挂观察器。 */
  function startObserver() {
    if (observer || typeof MutationObserver !== "function" || !document.body) return;
    observer = new MutationObserver(function (records) {
      for (let i = 0; i < records.length; i += 1) {
        const r = records[i];
        if (r.type === "childList") {
          r.addedNodes.forEach(function (n) {
            if (n.nodeType === 1) schedule(n);
            else if (n.nodeType === 3 && n.parentElement) schedule(n.parentElement);
          });
        } else if (r.type === "characterData") {
          if (r.target.parentElement) schedule(r.target.parentElement);
        } else if (r.type === "attributes") {
          schedule(r.target);
        }
      }
    });
    observer.observe(document.documentElement, {
      subtree: true,
      childList: true,
      characterData: true,
      attributes: true,
      attributeFilter: ATTRS,
    });
  }

  /** 把一棵子树（默认整个 body）翻成当前语言。幂等：已经是对的就不动。 */
  function applyPhrase(root) {
    const base = root && root.nodeType === 1 ? root : document.body;
    if (!base) return;
    startObserver();
    try {
      translateAttrs(base);
      const withAttrs = base.querySelectorAll("[placeholder],[title],[aria-label],[alt]");
      for (let i = 0; i < withAttrs.length; i += 1) translateAttrs(withAttrs[i]);
      const walker = document.createTreeWalker(base, NodeFilter.SHOW_TEXT, null, false);
      let n = walker.nextNode();
      while (n) {
        translateTextNode(n);
        n = walker.nextNode();
      }
      const t0 = document.title;
      if (t0) {
        if (TITLE_SRC === null) TITLE_SRC = t0;
        const src = TITLE_SRC;
        const out = lookup(src.trim());
        const want = out == null ? src : out;
        if (document.title !== want) document.title = want;
      }
    } catch (_) {}
  }

  const loading = {};
  const waiting = {};

  function adopt(lang) {
    const extGlobal = global.CYBER_I18N_EXT;
    if (extGlobal && extGlobal[lang] && !EXT[lang]) EXT[lang] = extGlobal[lang];
    const phGlobal = global.CYBER_I18N_PHRASE;
    if (phGlobal && phGlobal[lang] && !PHRASE[lang]) {
      PHRASE[lang] = phGlobal[lang];
      compilePatterns(lang);
    }
  }

  function loadFile(url, done) {
    if (loading[url] === "ok" || loading[url] === "missing") { done(); return; }
    let tag;
    try {
      tag = document.createElement("script");
    } catch (_) {
      loading[url] = "missing";
      done();
      return;
    }
    tag.src = url;
    tag.async = true;
    tag.onload = function () { loading[url] = "ok"; done(); };
    tag.onerror = function () { loading[url] = "missing"; done(); };
    document.head.appendChild(tag);
  }

  /**
   * 确保 lang 的源文案表已就绪，然后回调（拉不到也会回调，页面照旧显示中文原文）。
   * zh-CN 直接同步回调。
   */
  function ensureExt(lang, cb) {
    if (!PACKS[lang] || lang === "zh-CN") { if (cb) cb(); return; }
    if (PHRASE[lang]) { adopt(lang); if (cb) cb(); return; }
    const q = waiting[lang];
    if (q) { if (cb) q.push(cb); return; }
    const cbs = waiting[lang] = cb ? [cb] : [];
    loadFile(PHRASE_BASE + lang + ".js", function () {
      adopt(lang);
      delete waiting[lang];
      cbs.forEach(function (f) { try { f(); } catch (_) {} });
    });
  }

  global.CYBER_I18N = {
    PACKS,
    EXT,
    PHRASE,
    ensureExt,
    getExtBase: function () { return PHRASE_BASE; },
    getPhraseBase: function () { return PHRASE_BASE; },
    lookup,
    lookupLoose,
    T,
    Tf,
    applyPhrase,
    SHIPPED_LANGS,
    LANG_LABELS,
    getLang,
    setLang,
    t,
    applyCyberI18n,
    STORAGE_KEY,
  };
})(window);
