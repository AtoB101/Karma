/**
 * Karma portal only: i18n + non-sensitive UI prefs in localStorage.
 * No WalletConnect / session / mnemonic logic (see web3-login.html).
 */
const LANDING_LANG_KEY = "karma_landing_lang";

const T = {
  en: {
    nav_home: "Home",
    nav_pay: "Pay / receive",
    nav_trust: "Trust layer",
    nav_how: "How it works",
    login: "Sign in",
    hero_title: "AGENT PAYMENT\nTRUST LAYER",
    hero_sub: "When one Agent pays another — no more “pay first, hope they deliver.”",
    hero_desc:
      "Karma addresses Agent-to-Agent settlement: verifiable delivery and rule-bound release. Stablecoin-focused, audit-friendly flows.",
    btn_integrate: "Start integration",
    btn_demo: "Open Agent Studio",
    studio_isolated: "Wallet sign-in uses a dedicated page. Do not enter a seed phrase on this site.",
    settlement_title: "Stablecoin settlement",
    settlement_desc: "USDT and USDC on supported EVM networks. Configure networks in your deployment.",
    problem_title: "The Agent payment deadlock",
    buyer_title: "Payer → fears no delivery",
    buyer_desc: "You need proof the counterparty will perform before funds irrevocably leave your control.",
    buyer_code: "Before paying: how do we ensure delivery?",
    seller_title: "Payee → fears unpaid work",
    seller_desc: "You need assurance payment follows verified delivery, without opaque custody.",
    seller_code: "After delivery: how do we ensure payment?",
    trust_title: "Karma trust layer: rules + evidence",
    trust_desc:
      "Bill-first, wallet-native posture: obligations and settlement steps you can review — not a black-box float account.",
    trust_code: "Lock and policy state are verifiable on-chain where applicable; settlement follows agreed conditions.",
    zero_custody: "Non-custodial by design",
    funds_safe: "Funds stay user-side until rules allow movement",
    deploy_title: "Deploy your trust node",
    deploy_desc: "Run Karma stack on your infrastructure. Replace the example URL with your distribution endpoint.",
    deploy_btn: "Documentation",
    deploy_note: "Example command only — configure before production.",
    flow_title: "Flow · trust as settlement",
    step1_title: "Define obligation",
    step1_desc: "Create a bill / policy the payer can review before authorizing.",
    step1_note: "Rules first, not blind transfer",
    step2_title: "Deliver & attest",
    step2_desc: "Attach delivery evidence hashes or signatures your counterpart can verify.",
    step2_note: "Fingerprinted, reviewable trail",
    step3_title: "Settle on conditions",
    step3_desc: "When conditions are met, stablecoin settlement executes per contract rules.",
    step3_note: "Closed loop, auditable",
    step4_title: "Disputes (optional)",
    step4_desc: "Escalate with evidence; outcomes remain on-chain where configured.",
    step4_note: "Process-bound, not ad-hoc chat",
    integrate_title: "Integrate",
    code_payer: "Payer Agent",
    code_payee: "Payee Agent",
    docs_btn: "Repository & docs",
    faq_title: "FAQ",
    faq1_q: "Is non-custodial settlement safe?",
    faq1_a: "Rules are enforced by contracts you can read; funds follow policy, not informal promises.",
    faq2_q: "How does the payee know they will be paid?",
    faq2_a: "Bill and policy state are on-chain or otherwise verifiable before work is committed.",
    faq3_q: "Which assets?",
    faq3_a: "USDC and USDT on networks you enable in deployment.",
    faq4_q: "Disputes?",
    faq4_a: "Evidence-backed escalation; exact governance depends on your deployment manifest.",
    foot_line1: "Karma — Agent payment trust layer",
    foot_line2: "USDT | USDC — non-custodial · verifiable",
    deploy_alert: "Replace the example URL in this page with your real deploy script before running in production.",
  },
  zh: {
    nav_home: "首页",
    nav_pay: "收款 / 付款",
    nav_trust: "信任层",
    nav_how: "如何运作",
    login: "登录",
    hero_title: "AGENT 收付款\n信任层",
    hero_sub: "让一个 Agent 向另一个 Agent 付款时 —— 减少「先付钱怕不交付」的不确定性。",
    hero_desc:
      "Karma 面向 Agent 间结算：可验证交付与按规则释放。以稳定币为主，流程可审计。",
    btn_integrate: "开始集成",
    btn_demo: "打开 Agent Studio",
    studio_isolated: "钱包登录在独立页面完成。请勿在本站输入助记词或私钥。",
    settlement_title: "稳定币结算",
    settlement_desc: "在已部署支持的 EVM 网络上使用 USDT 与 USDC。网络以您的部署配置为准。",
    problem_title: "Agent 收付款的两难",
    buyer_title: "付款方 → 怕收不到交付",
    buyer_desc: "需要在资金不可逆转出前，尽可能验证对手会履约。",
    buyer_code: "付款前：如何确保对方会交付？",
    seller_title: "收款方 → 怕白干活",
    seller_desc: "需要在交付被验证后，仍能按规则拿到款项，而非依赖不透明托管。",
    seller_code: "交付后：如何确保对方会付款？",
    trust_title: "Karma 信任层：规则 + 证据",
    trust_desc: "账单优先、钱包侧姿态：义务与结算步骤可复核，而不是黑箱资金池。",
    trust_code: "锁仓与策略状态在适用场景下可链上核验；条件满足后按约定结算。",
    zero_custody: "非托管设计",
    funds_safe: "在规则允许前，资金保持在用户侧",
    deploy_title: "部署信任节点",
    deploy_desc: "在您的基础设施运行 Karma 组件。请将示例 URL 换成您的分发地址。",
    deploy_btn: "查看文档说明",
    deploy_note: "仅为示例命令 — 生产前请自行配置。",
    flow_title: "流程 · 以信任完成结算",
    step1_title: "明确义务",
    step1_desc: "生成付款方可先行审阅的账单 / 策略。",
    step1_note: "先规则，再转账",
    step2_title: "交付与证明",
    step2_desc: "附上对手方可核验的交付哈希或签名。",
    step2_note: "可追溯的指纹",
    step3_title: "条件满足后结算",
    step3_desc: "条件达成时，按合约规则执行稳定币结算。",
    step3_note: "闭环、可审计",
    step4_title: "争议（可选）",
    step4_desc: "凭证据升级；结果在已配置链上执行。",
    step4_note: "流程化，而非临时沟通",
    integrate_title: "接入",
    code_payer: "付款方 Agent",
    code_payee: "收款方 Agent",
    docs_btn: "仓库与文档",
    faq_title: "常见问题",
    faq1_q: "非托管结算安全吗？",
    faq1_a: "规则由可读合约执行；资金按策略流动，而非口头承诺。",
    faq2_q: "收款方如何确信能收到钱？",
    faq2_a: "账单与策略状态可在投入工作前核验。",
    faq3_q: "支持哪些资产？",
    faq3_a: "以部署启用为准的 USDC / USDT。",
    faq4_q: "争议如何处理？",
    faq4_a: "基于证据的升级路径；具体治理以部署清单为准。",
    foot_line1: "Karma — Agent 收付款信任层",
    foot_line2: "USDT | USDC — 非托管 · 可验证",
    deploy_alert: "上线前请将页面中的示例部署地址替换为真实脚本来源。",
  },
};

function deepFill(lang) {
  const base = T.en;
  const over = T[lang] || {};
  return new Proxy(over, {
    get(_, k) {
      return over[k] !== undefined ? over[k] : base[k];
    },
  });
}

let currentLang =
  typeof localStorage !== "undefined"
    ? localStorage.getItem(LANDING_LANG_KEY) || "en"
    : "en";
if (!["en", "zh", "ja", "ko", "de", "fr", "es", "ar", "ru"].includes(currentLang)) {
  currentLang = "en";
}

function applyLanguage(lang) {
  currentLang = lang;
  try {
    localStorage.setItem(LANDING_LANG_KEY, lang);
  } catch (_) {
    /* quota / blocked storage */
  }
  document.documentElement.lang =
    lang === "zh" ? "zh-CN" : lang === "ja" ? "ja" : lang === "ko" ? "ko" : lang === "ar" ? "ar" : lang;
  document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";
  const d = deepFill(lang);
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    const key = el.getAttribute("data-i18n");
    const k = key.replace(/-/g, "_");
    const text = d[k];
    if (text === undefined) return;
    el.textContent = text;
  });
  document.getElementById("langSwitcher").value = lang;
}

document.getElementById("langSwitcher").value = currentLang;
applyLanguage(currentLang);
document.getElementById("langSwitcher").addEventListener("change", (e) => applyLanguage(e.target.value));

document.getElementById("oneClickDeployBtn").addEventListener("click", () => {
  alert(deepFill(currentLang).deploy_alert);
});
