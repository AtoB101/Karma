/**
 * Cyber console i18n — zh-CN, en, ja, ko, es, fr, de, pt-BR.
 * Missing keys fall back: locale → en → zh-CN → key.
 */
(function (global) {
  const STORAGE_KEY = "karma_cyber_lang";

  const zhCN = {
    "api.lang": "语言",
    "api.base": "API 根地址",
    "api.key": "API Key (X-Karma-Api-Key)",
    "api.identity": "身份 ID",
    "api.save": "保存连接",
    "api.refresh": "从 API 刷新额度",
    "api.lookup": "查询结算任务",
    "api.task_id": "任务 ID",
    "api.fetch_settlement": "拉取 Settlement",
    "api.status_ok": "已连接",
    "api.status_idle": "未请求",
    "api.status_err": "错误",
    "brand.title": "Karma Console",
    "brand.tagline": "赛博责任网络",
    "nav.overview": "总览",
    "nav.center": "收付中心",
    "nav.tasks": "任务执行",
    "nav.receipts": "回执证明",
    "nav.bills": "账单",
    "nav.disputes": "争议",
    "nav.identity": "身份",
    "nav.settings": "设置",
    "side.rule_title": "资金安全规则",
    "side.rule_body": "管理员只能暂停，不能改账、不能提现。所有责任额度永远 1:1 锚定 USDC。",
    "id.current": "当前身份",
    "id.status": "正常",
    "id.buyer_sub": "付款子身份",
    "id.seller_sub": "收款子身份",
    "top.sub": "切换子身份",
    "top.export": "导出记录",
    "top.lock": "增加锁仓额度",
    "page.overview.title": "总览",
    "page.overview.sub": "资金、额度、任务、收款和争议一屏掌握。",
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
    "page.identity.title": "身份",
    "page.identity.sub": "管理 Karma Identity SBT、展示编号和子身份。",
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
  };

  const en = {
    "api.lang": "Language",
    "api.base": "API base URL",
    "api.key": "API key (X-Karma-Api-Key)",
    "api.identity": "Identity ID",
    "api.save": "Save connection",
    "api.refresh": "Refresh balances from API",
    "api.lookup": "Settlement lookup",
    "api.task_id": "Task ID",
    "api.fetch_settlement": "Fetch settlement",
    "api.status_ok": "Connected",
    "api.status_idle": "Idle",
    "api.status_err": "Error",
    "brand.title": "Karma Console",
    "brand.tagline": "Cyber responsibility network",
    "nav.overview": "Overview",
    "nav.center": "Payments hub",
    "nav.tasks": "Tasks",
    "nav.receipts": "Receipts",
    "nav.bills": "Bills",
    "nav.disputes": "Disputes",
    "nav.identity": "Identity",
    "nav.settings": "Settings",
    "side.rule_title": "Fund safety rules",
    "side.rule_body":
      "Admins can only pause — no ledger tampering or withdrawals. Bill credits stay 1:1 anchored to USDC.",
    "id.current": "Current identity",
    "id.status": "OK",
    "id.buyer_sub": "Buyer sub-identity",
    "id.seller_sub": "Seller sub-identity",
    "top.sub": "Switch sub-identity",
    "top.export": "Export records",
    "top.lock": "Increase lock",
    "page.overview.title": "Overview",
    "page.overview.sub": "Balances, tasks, receipts, and disputes at a glance.",
    "page.center.title": "Payments hub",
    "page.center.sub": "One identity can pay and receive depending on the task.",
    "page.tasks.title": "Tasks",
    "page.tasks.sub": "Progress, receipts, regret liability, and settlement.",
    "page.receipts.title": "Receipts",
    "page.receipts.sub": "Execution receipts, evidence hashes, runtime logs.",
    "page.bills.title": "Bills",
    "page.bills.sub": "Internal bill-credit state visible only to the identity owner.",
    "page.disputes.title": "Disputes",
    "page.disputes.sub": "Evidence, frozen funds, arbitration.",
    "page.identity.title": "Identity",
    "page.identity.sub": "SBT, display IDs, and sub-identities.",
    "page.settings.title": "Settings",
    "page.settings.sub": "Safety, receipt rules, settlement, privacy, webhooks.",
    "m.locked": "Locked USDC",
    "m.locked_hint": "On-chain anchor",
    "m.available": "Available credits",
    "m.available_hint": "Can create vouchers",
    "m.exec": "In execution",
    "m.exec_hint": "Frozen for active tasks",
    "m.pending": "Pending receipt",
    "m.pending_hint": "Accepted / pending settlement",
    "m.dispute": "Dispute hold",
    "m.dispute_hint": "Awaiting arbitration",
  };

  const overrides = {
    ja: {
      "nav.overview": "概要",
      "nav.center": "決済ハブ",
      "nav.tasks": "タスク",
      "nav.receipts": "レシート",
      "nav.bills": "請求",
      "nav.disputes": "紛争",
      "nav.identity": "身元",
      "nav.settings": "設定",
      "api.lang": "言語",
      "api.refresh": "API から更新",
    },
    ko: {
      "nav.overview": "개요",
      "nav.center": "결제 허브",
      "nav.tasks": "작업",
      "nav.receipts": "영수증",
      "nav.bills": "청구",
      "nav.disputes": "분쟁",
      "nav.identity": "신원",
      "nav.settings": "설정",
      "api.lang": "언어",
      "api.refresh": "API에서 새로고침",
    },
    es: {
      "nav.overview": "Resumen",
      "nav.center": "Centro de pagos",
      "nav.tasks": "Tareas",
      "nav.receipts": "Recibos",
      "nav.bills": "Facturas",
      "nav.disputes": "Disputas",
      "nav.identity": "Identidad",
      "nav.settings": "Ajustes",
      "api.lang": "Idioma",
      "api.refresh": "Actualizar desde API",
    },
    fr: {
      "nav.overview": "Vue d’ensemble",
      "nav.center": "Hub paiements",
      "nav.tasks": "Tâches",
      "nav.receipts": "Reçus",
      "nav.bills": "Factures",
      "nav.disputes": "Litiges",
      "nav.identity": "Identité",
      "nav.settings": "Paramètres",
      "api.lang": "Langue",
      "api.refresh": "Rafraîchir (API)",
    },
    de: {
      "nav.overview": "Übersicht",
      "nav.center": "Zahlungs-Hub",
      "nav.tasks": "Aufgaben",
      "nav.receipts": "Belege",
      "nav.bills": "Rechnungen",
      "nav.disputes": "Streitfälle",
      "nav.identity": "Identität",
      "nav.settings": "Einstellungen",
      "api.lang": "Sprache",
      "api.refresh": "Von API aktualisieren",
    },
    "pt-BR": {
      "nav.overview": "Visão geral",
      "nav.center": "Central de pagamentos",
      "nav.tasks": "Tarefas",
      "nav.receipts": "Recibos",
      "nav.bills": "Faturas",
      "nav.disputes": "Disputas",
      "nav.identity": "Identidade",
      "nav.settings": "Configurações",
      "api.lang": "Idioma",
      "api.refresh": "Atualizar da API",
    },
  };

  function merge(base, extra) {
    return Object.assign({}, base, extra || {});
  }

  const PACKS = {
    "zh-CN": zhCN,
    en: en,
    ja: merge(en, overrides.ja),
    ko: merge(en, overrides.ko),
    es: merge(en, overrides.es),
    fr: merge(en, overrides.fr),
    de: merge(en, overrides.de),
    "pt-BR": merge(en, overrides["pt-BR"]),
  };

  function getLang() {
    try {
      const s = localStorage.getItem(STORAGE_KEY);
      if (s && PACKS[s]) return s;
    } catch (_) {}
    const html = (document.documentElement.getAttribute("lang") || "").trim();
    if (html && PACKS[html]) return html;
    return "zh-CN";
  }

  function setLang(code) {
    if (!PACKS[code]) return;
    try {
      localStorage.setItem(STORAGE_KEY, code);
    } catch (_) {}
    document.documentElement.lang = code;
  }

  function t(key) {
    const L = getLang();
    if (PACKS[L] && PACKS[L][key]) return PACKS[L][key];
    if (PACKS.en[key]) return PACKS.en[key];
    if (zhCN[key]) return zhCN[key];
    return key;
  }

  function applyCyberI18n() {
    document.querySelectorAll("[data-i18n]").forEach(function (el) {
      const key = el.getAttribute("data-i18n");
      if (!key) return;
      const val = t(key);
      if (el.tagName === "INPUT" || el.tagName === "TEXTAREA") {
        if (el.hasAttribute("data-i18n-placeholder")) {
          el.setAttribute("placeholder", t(el.getAttribute("data-i18n-placeholder")));
        } else {
          el.value = val;
        }
      } else {
        el.textContent = val;
      }
    });
    document.querySelectorAll("[data-i18n-placeholder]").forEach(function (el) {
      const pk = el.getAttribute("data-i18n-placeholder");
      if (pk && (el.tagName === "INPUT" || el.tagName === "TEXTAREA")) {
        el.setAttribute("placeholder", t(pk));
      }
    });
  }

  global.CYBER_I18N = { PACKS, getLang, setLang, t, applyCyberI18n, STORAGE_KEY };
})(window);
