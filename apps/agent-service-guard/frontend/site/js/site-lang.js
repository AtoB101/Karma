/**
 * KarmaPay site i18n — default English; languages: en, ja, ko, zh, de, fr, ar, es.
 * Pages add data-i18n="key.path" for static text. Gateway overrides steps via applyGatewayLang().
 */
(function () {
  const STORAGE_KEY = "karma_site_lang";
  /** @type {const} */ // eslint-disable-line
  const SUPPORTED = ["en", "ja", "ko", "zh", "de", "fr", "ar", "es"];

  const DICT = {
    en: {
      langLabel: "Language",
      gateway: {
        badge: "",
        step1: "STEP 1 / 2",
        step2: "STEP 2 / 2",
        footerHint: "",
        back: "Back",
        quizFooter: "",
        studioLogin: "Sign in",
        routeTitlePro: "Overview",
        routeTextPro: "Continue to the product introduction.",
        routeTitleLoyal: "Alternate view",
        routeTextLoyal: "Continue to the alternate presentation.",
        enter: "Continue",
        q1h: "Choose your experience",
        q1q: "What would you like to see first?",
        q1hint: "Takes a few seconds.",
        q1a: "Product overview (recommended)",
        q1b: "Alternate presentation",
        q1c: "I'm not sure — help me choose",
        q2h: "Pick a focus",
        q2q: "Which matters more to you right now?",
        q2hint: "",
        q2a: "Clarity, trust, and compliance-oriented explanation",
        q2b: "Speed, control, and hands-on product depth",
      },
      professional: {
        navGateway: "Gateway",
        navPro: "Overview",
        navLoyal: "Alternate",
        navLogin: "Sign in",
        heroKicker: "Non-custodial settlement",
        heroTitle: "Keep funds in user wallets. Execute rules, not custody.",
        heroLead:
          "KarmaPay helps teams settle agent services and APIs with bill-first flows: less platform float, clearer disputes, auditable state.",
        probTitle: "Problem",
        probBody:
          "Custodial models pool user funds, hide rules behind support tickets, and delay payouts. That concentrates risk and weakens trust.",
        solTitle: "What we do",
        solBody:
          "We separate obligations from custody: agreements and bills on-chain where needed, stable settlement when conditions are met, evidence that third parties can review.",
        ctaGateway: "Quick preferences",
        ctaLogin: "Sign in",
        footNote: "Official channels",
        footX: "Official X:",
        footGh: "Repository:",
      },
      loyal: {
        navGateway: "Gateway",
        navPro: "Overview",
        navLoyal: "Alternate",
        navLogin: "Sign in",
        title: "Extended presentation",
        lead:
          "Non-custodial settlement for agent services and APIs: wallet-native funds, bill-first flows, and dispute evidence you can audit.",
        b1: "No platform slush fund — funds stay user-side until rules say otherwise.",
        b2: "Bill-first — evidence and state you can audit.",
        b3: "Disputes anchored in process, not opaque queues.",
        community: "Community",
        communityHint: "Community channels will be announced here.",
        joinCta: "Join community",
        ctaPro: "Standard overview",
        ctaLogin: "Sign in",
      },
      login: {
        titleBar: "KARMA.PAY / LOGIN",
        qrExpires: "QR refreshes in",
        sec: "s",
        mnemonicToggle: "Mnemonic login",
        mnemonicHint: "Use only on a device you trust.",
        wordLabel: "Word",
        mnemonicSubmit: "Continue",
        mnemonicError: "Invalid phrase. Check words and order.",
        statusInit: "Preparing connection…",
        statusConn: "Scan with your wallet.",
        statusNoConfig: "Sign-in is temporarily unavailable. Please try again later.",
        cfgOnce: "",
        navGateway: "Gateway",
        navPro: "Overview",
        navLoyal: "Loyal",
      },
    },
    ja: {
      langLabel: "言語",
      gateway: {
        badge: "",
        step1: "ステップ 1/2",
        step2: "ステップ 2/2",
        footerHint: "",
        back: "戻る",
        quizFooter: "",
        studioLogin: "サインイン",
        routeTitlePro: "概要",
        routeTextPro: "プロダクト紹介へ進みます。",
        routeTitleLoyal: "別のプレゼンテーション",
        routeTextLoyal: "別の形式の紹介へ進みます。",
        enter: "進む",
        q1h: "表示スタイルを選ぶ",
        q1q: "最初に何を見たいですか？",
        q1hint: "数秒で終わります。",
        q1a: "製品概要（おすすめ）",
        q1b: "別のプレゼンテーション",
        q1c: "わからない — おすすめを表示",
        q2h: "注目ポイント",
        q2q: "今もっとも重要なのはどちらですか？",
        q2hint: "",
        q2a: "明確さ・信頼・コンプライアンス寄りの説明",
        q2b: "速度・操作性・より踏み込んだ内容",
      },
      professional: {
        navGateway: "ゲートウェイ",
        navPro: "概要",
        navLoyal: "ロイヤル",
        navLogin: "サインイン",
        heroKicker: "ノンカストディ決済",
        heroTitle: "資金はユーザーウォレットに。ルールで実行。",
        heroLead:
          "KarmaPay はエージェントサービス向けに請求優先フローを提供し、プラットフォーム預かりを減らし、状態を監査可能にします。",
        probTitle: "課題",
        probBody: "カストディ型は資金をプールし、ルールを不明瞭にし、出金を遅らせます。",
        solTitle: "提供すること",
        solBody: "預託と義務を分離し、条件達成時の決済と第三者が見れる証跡を重視します。",
        ctaGateway: "選択をやり直す",
        ctaLogin: "サインイン",
        footNote: "公式チャネル",
        footX: "公式 X:",
        footGh: "リポジトリ:",
      },
      loyal: {
        navGateway: "ゲートウェイ",
        navPro: "概要",
        navLoyal: "ロイヤル",
        navLogin: "サインイン",
        title: "拡張プレゼンテーション",
        lead: "エージェントサービス向けのノンカストディ決済：ウォレット内資金、請求優先フロー、監査可能な証跡。",
        b1: "プラットフォーム資金プールを避け、ユーザーサイドに。",
        b2: "請求ファーストで証跡を監査可能に。",
        b3: "不透明なキューではなく、プロセスに沿った争い。",
        community: "コミュニティ",
        communityHint: "コミュニティ参加（リンクは後で設定）。",
        joinCta: "参加する",
        ctaPro: "プロ概要が良い？",
        ctaLogin: "サインイン",
      },
      login: {
        titleBar: "KARMA.PAY / ログイン",
        qrExpires: "QR 更新まで",
        sec: "秒",
        mnemonicToggle: "ニーモニックでログイン",
        mnemonicHint: "信頼できる端末でのみご利用ください。",
        wordLabel: "語",
        mnemonicSubmit: "フレーズで続行",
        mnemonicError: "無効なフレーズです。",
        statusInit: "初期化中…",
        statusConn: "ウォレットでスキャン。QR は 60 秒ごとに更新。",
        statusNoConfig: "サインインを一時的に利用できません。しばらくしてからお試しください。",
        cfgOnce: "",
        navGateway: "ゲートウェイ",
        navPro: "概要",
        navLoyal: "ロイヤル",
      },
    },
    ko: {
      langLabel: "언어",
      gateway: {
        badge: "",
        step1: "1/2 단계",
        step2: "2/2 단계",
        footerHint: "",
        back: "뒤로",
        quizFooter: "",
        studioLogin: "로그인",
        routeTitlePro: "개요",
        routeTextPro: "제품 소개로 이동합니다.",
        routeTitleLoyal: "대체 표시",
        routeTextLoyal: "대체 형식의 소개로 이동합니다.",
        enter: "계속",
        q1h: "표시 방식 선택",
        q1q: "무엇을 먼저 보시겠습니까?",
        q1hint: "잠시면 됩니다.",
        q1a: "제품 개요(권장)",
        q1b: "대체 표시",
        q1c: "잘 모르겠음 — 추천 표시",
        q2h: "초점",
        q2q: "지금 더 중요한 것은?",
        q2hint: "",
        q2a: "명확성·신뢰·컴플라이언스 중심 설명",
        q2b: "속도·제어·심화 내용",
      },
      professional: {
        navGateway: "게이트웨이",
        navPro: "개요",
        navLoyal: "로열",
        navLogin: "로그인",
        heroKicker: "비수탁 정산",
        heroTitle: "자금은 사용자 지갑에. 규칙으로 실행.",
        heroLead: "KarmaPay는 청구 우선 흐름으로 에이전트 서비스 정산을 돕습니다.",
        probTitle: "문제",
        probBody: "수탁 모델은 자금을 모으고 규칙을 불투명하게 합니다.",
        solTitle: "우리가 하는 일",
        solBody: "의무와 수탁을 분리하고 조건 충족 시 정산과 감사 가능한 상태를 제공합니다.",
        ctaGateway: "퀴즈 다시",
        ctaLogin: "로그인",
        footNote: "공식 채널",
        footX: "공식 X:",
        footGh: "저장소:",
      },
      loyal: {
        navGateway: "게이트웨이",
        navPro: "개요",
        navLoyal: "로열",
        navLogin: "로그인",
        title: "확장 표시",
        lead: "에이전트 서비스를 위한 비수탁 정산: 지갑 내 자금, 청구 우선 흐름, 감사 가능한 증거.",
        b1: "플랫폼 풀 없이 사용자 측 자금.",
        b2: "청구 우선 — 감사 가능.",
        b3: "불투명한 대기열이 아닌 프로세스.",
        community: "커뮤니티",
        communityHint: "커뮤니티 링크(나중에 추가).",
        joinCta: "참여",
        ctaPro: "전문 개요가 필요하신가요?",
        ctaLogin: "로그인",
      },
      login: {
        titleBar: "KARMA.PAY / 로그인",
        qrExpires: "QR 갱신까지",
        sec: "초",
        mnemonicToggle: "니모닉 로그인",
        mnemonicHint: "신뢰할 수 있는 기기에서만 사용하세요.",
        wordLabel: "단어",
        mnemonicSubmit: "니모닉으로 계속",
        mnemonicError: "유효하지 않은 니모닉입니다.",
        statusInit: "초기화 중…",
        statusConn: "지갑으로 스캔. QR은 60초마다 갱신.",
        statusNoConfig: "로그인을 일시적으로 사용할 수 없습니다. 나중에 다시 시도하세요.",
        cfgOnce: "",
        navGateway: "게이트웨이",
        navPro: "개요",
        navLoyal: "로열",
      },
    },
    zh: {
      langLabel: "语言",
      gateway: {
        badge: "",
        step1: "第 1 / 2 步",
        step2: "第 2 / 2 步",
        footerHint: "",
        back: "返回",
        quizFooter: "",
        studioLogin: "登录",
        routeTitlePro: "概览",
        routeTextPro: "进入产品介绍。",
        routeTitleLoyal: "另一版展示",
        routeTextLoyal: "进入另一版产品介绍。",
        enter: "继续",
        q1h: "选择浏览方式",
        q1q: "想先看什么？",
        q1hint: "仅需几秒。",
        q1a: "产品概览（推荐）",
        q1b: "另一版展示",
        q1c: "不确定 — 为我推荐",
        q2h: "关注点",
        q2q: "您目前更看重哪一点？",
        q2hint: "",
        q2a: "清晰、可信、合规导向的讲解",
        q2b: "速度、掌控与更深入的产品信息",
      },
      professional: {
        navGateway: "入口",
        navPro: "概览",
        navLoyal: "另一版",
        navLogin: "登录",
        heroKicker: "非托管结算",
        heroTitle: "资金留在用户钱包，用规则执行。",
        heroLead: "KarmaPay 为智能体服务提供账单优先流程，减少平台沉淀资金，状态可审计。",
        probTitle: "问题",
        probBody: "托管模式沉淀用户资金、规则不透明、提现慢，集中风险并削弱信任。",
        solTitle: "我们做什么",
        solBody: "区分托管与合约义务：条件满足时结算稳定币，过程与证据可被第三方复核。",
        ctaGateway: "重新选择",
        ctaLogin: "登录",
        footNote: "官方渠道",
        footX: "官方 X:",
        footGh: "仓库:",
      },
      loyal: {
        navGateway: "入口",
        navPro: "概览",
        navLoyal: "另一版",
        navLogin: "登录",
        title: "另一版展示",
        lead: "面向智能体服务的非托管结算：资金留在钱包、账单优先流程、可审计的争议证据。",
        b1: "避免平台资金池，资金在用户侧。",
        b2: "账单优先 — 状态可审计。",
        b3: "争议流程可追踪，而非黑箱排队。",
        community: "社区",
        communityHint: "社区入口将在此公布。",
        joinCta: "加入社区",
        ctaPro: "想看专业概览？",
        ctaLogin: "登录",
      },
      login: {
        titleBar: "KARMA.PAY / 登录",
        qrExpires: "二维码刷新还剩",
        sec: "秒",
        mnemonicToggle: "助记词登录",
        mnemonicHint: "请在您信任的设备上使用。",
        wordLabel: "词",
        mnemonicSubmit: "使用助记词继续",
        mnemonicError: "助记词无效，请检查拼写与顺序（BIP-39 英文）。",
        statusInit: "初始化中…",
        statusConn: "用钱包扫码；二维码每 60 秒刷新。",
        statusNoConfig: "暂时无法登录，请稍后再试。",
        cfgOnce: "",
        navGateway: "入口",
        navPro: "概览",
        navLoyal: "忠实版",
      },
    },
    de: {
      langLabel: "Sprache",
      gateway: {
        badge: "",
        step1: "SCHRITT 1/2",
        step2: "SCHRITT 2/2",
        footerHint: "",
        back: "Zurück",
        quizFooter: "",
        studioLogin: "Anmelden",
        routeTitlePro: "Übersicht",
        routeTextPro: "Weiter zur Produkteinführung.",
        routeTitleLoyal: "Alternativansicht",
        routeTextLoyal: "Weiter zur alternativen Darstellung.",
        enter: "Weiter",
        q1h: "Darstellung wählen",
        q1q: "Was möchten Sie zuerst sehen?",
        q1hint: "Dauert wenige Sekunden.",
        q1a: "Produktübersicht (empfohlen)",
        q1b: "Alternativansicht",
        q1c: "Unsicher — Vorschlag anzeigen",
        q2h: "Schwerpunkt",
        q2q: "Was ist Ihnen jetzt wichtiger?",
        q2hint: "",
        q2a: "Klarheit, Vertrauen, Compliance-erklärend",
        q2b: "Tempo, Kontrolle, mehr Tiefe",
      },
      professional: {
        navGateway: "Gateway",
        navPro: "Übersicht",
        navLoyal: "Loyal",
        navLogin: "Anmelden",
        heroKicker: "Nicht-verwahrte Abwicklung",
        heroTitle: "Geld bleibt in Nutzer-Wallets. Regeln ausführen.",
        heroLead:
          "KarmaPay unterstützt Agent-Services mit rechnungs-first Flows und auditierbarem Zustand.",
        probTitle: "Problem",
        probBody: "Verwahrmodelle bündeln Risiken und verzögern Auszahlungen.",
        solTitle: "Was wir tun",
        solBody: "Verpflichtungen trennen von Verwahrung — Abrechnung bei erfüllten Bedingungen.",
        ctaGateway: "Auswahl erneut",
        ctaLogin: "Anmelden",
        footNote: "Offizielle Kanäle",
        footX: "Offizielles X:",
        footGh: "Repository:",
      },
      loyal: {
        navGateway: "Gateway",
        navPro: "Übersicht",
        navLoyal: "Loyal",
        navLogin: "Anmelden",
        title: "Erweiterte Darstellung",
        lead: "Nicht-verwahrtes Settlement für Agent-Services: Gelder in Wallets, rechnungs-first, prüfbare Evidenz.",
        b1: "Kein Plattform-Pool",
        b2: "Bill-first, auditierbar",
        b3: "Streit nachvollziehbar",
        community: "Community",
        communityHint: "Community beitreten (Link später)",
        joinCta: "Beitreten",
        ctaPro: "Professionelle Übersicht?",
        ctaLogin: "Anmelden",
      },
      login: {
        titleBar: "KARMA.PAY / LOGIN",
        qrExpires: "QR erneuert in",
        sec: "s",
        mnemonicToggle: "Mnemonic-Anmeldung",
        mnemonicHint: "Nur auf einem vertrauenswürdigen Gerät verwenden.",
        wordLabel: "Wort",
        mnemonicSubmit: "Mit Phrase fortfahren",
        mnemonicError: "Ungültige Phrase.",
        statusInit: "Initialisiere…",
        statusConn: "Wallet scannen. QR alle 60s neu.",
        statusNoConfig: "Anmeldung vorübergehend nicht möglich. Bitte später erneut versuchen.",
        cfgOnce: "",
        navGateway: "Gateway",
        navPro: "Übersicht",
        navLoyal: "Loyal",
      },
    },
    fr: {
      langLabel: "Langue",
      gateway: {
        badge: "",
        step1: "ÉTAPE 1/2",
        step2: "ÉTAPE 2/2",
        footerHint: "",
        back: "Retour",
        quizFooter: "",
        studioLogin: "Connexion",
        routeTitlePro: "Aperçu",
        routeTextPro: "Continuer vers l’introduction produit.",
        routeTitleLoyal: "Autre présentation",
        routeTextLoyal: "Continuer vers une autre présentation.",
        enter: "Continuer",
        q1h: "Choisir le mode d’affichage",
        q1q: "Que souhaitez-vous voir en premier ?",
        q1hint: "Quelques secondes.",
        q1a: "Aperçu produit (recommandé)",
        q1b: "Autre présentation",
        q1c: "Je ne sais pas — me recommander",
        q2h: "Priorité",
        q2q: "Qu’est-ce qui compte le plus pour vous ?",
        q2hint: "",
        q2a: "Clarté, confiance, lecture compliance",
        q2b: "Vitesse, contrôle, contenu plus avancé",
      },
      professional: {
        navGateway: "Passerelle",
        navPro: "Aperçu",
        navLoyal: "Loyal",
        navLogin: "Connexion",
        heroKicker: "Règlement non dépositaire",
        heroTitle: "Les fonds restent dans les portefeuilles.",
        heroLead: "KarmaPay aide les services d’agents avec des flux facture d’abord.",
        probTitle: "Problème",
        probBody: "Les modèles dépositaires concentrent les risques.",
        solTitle: "Ce que nous faisons",
        solBody: "Séparer garde et obligations — règlement quand les conditions sont remplies.",
        ctaGateway: "Refaire le quiz",
        ctaLogin: "Connexion",
        footNote: "Canaux officiels",
        footX: "X officiel :",
        footGh: "Dépôt :",
      },
      loyal: {
        navGateway: "Passerelle",
        navPro: "Aperçu",
        navLoyal: "Loyal",
        navLogin: "Connexion",
        title: "Présentation étendue",
        lead: "Règlement non dépositaire pour services d’agents : fonds en portefeuille, flux facture d’abord, preuves auditables.",
        b1: "Pas de pool plateforme",
        b2: "Facture d’abord",
        b3: "Litiges traçables",
        community: "Communauté",
        communityHint: "Rejoindre (lien plus tard)",
        joinCta: "Rejoindre",
        ctaPro: "Vue professionnelle ?",
        ctaLogin: "Connexion",
      },
      login: {
        titleBar: "KARMA.PAY / LOGIN",
        qrExpires: "QR renouvelé dans",
        sec: "s",
        mnemonicToggle: "Connexion mnémonique",
        mnemonicHint: "Utilisez uniquement un appareil de confiance.",
        wordLabel: "Mot",
        mnemonicSubmit: "Continuer avec la phrase",
        mnemonicError: "Phrase invalide.",
        statusInit: "Initialisation…",
        statusConn: "Scannez avec le wallet. QR 60s.",
        statusNoConfig: "Connexion temporairement indisponible. Réessayez plus tard.",
        cfgOnce: "",
        navGateway: "Passerelle",
        navPro: "Aperçu",
        navLoyal: "Loyal",
      },
    },
    ar: {
      langLabel: "اللغة",
      gateway: {
        badge: "",
        step1: "الخطوة 1/2",
        step2: "الخطوة 2/2",
        footerHint: "",
        back: "رجوع",
        quizFooter: "",
        studioLogin: "تسجيل الدخول",
        routeTitlePro: "نظرة عامة",
        routeTextPro: "المتابعة إلى مقدمة المنتج.",
        routeTitleLoyal: "عرض بديل",
        routeTextLoyal: "المتابعة إلى صيغة عرض بديلة.",
        enter: "متابعة",
        q1h: "اختر طريقة العرض",
        q1q: "ماذا تريد أن ترى أولًا؟",
        q1hint: "ثوانٍ فقط.",
        q1a: "نظرة عامة على المنتج (موصى بها)",
        q1b: "عرض بديل",
        q1c: "لست متأكدًا — اقترح لي",
        q2h: "الأولوية",
        q2q: "ما الأهم لك الآن؟",
        q2hint: "",
        q2a: "الوضوح والثقة والإطار التنظيمي",
        q2b: "السرعة والتحكم والتعمق",
      },
      professional: {
        navGateway: "البوابة",
        navPro: "نظرة عامة",
        navLoyal: "بديل",
        navLogin: "تسجيل الدخول",
        heroKicker: "تسوية غير وصائية",
        heroTitle: "الأموال تبقى في محافظ المستخدمين.",
        heroLead: "تساعد KarmaPay خدمات الوكلاء بتدفقات الفاتورة أولًا.",
        probTitle: "المشكلة",
        probBody: "نماذج الحجز تركز المخاطر وتؤخر السداد.",
        solTitle: "ما نفعله",
        solBody: "فصل الضمان عن الالتزامات — تسوية عند تحقق الشروط.",
        ctaGateway: "إعادة الاختبار",
        ctaLogin: "تسجيل الدخول",
        footNote: "قنوات رسمية",
        footX: "X الرسمي:",
        footGh: "المستودع:",
      },
      loyal: {
        navGateway: "البوابة",
        navPro: "نظرة عامة",
        navLoyal: "بديل",
        navLogin: "تسجيل الدخول",
        title: "عرض موسّع",
        lead: "تسوية غير وصائية لخدمات الوكلاء: أموال في المحفظة، فواتير أولًا، أدلة قابلة للمراجعة.",
        b1: "لا تجمع منصة",
        b2: "الفاتورة أولاً",
        b3: "نزاعات يمكن تتبعها",
        community: "المجتمع",
        communityHint: "انضمام (الرابط لاحقًا)",
        joinCta: "انضم",
        ctaPro: "النسخة المهنية؟",
        ctaLogin: "تسجيل الدخول",
      },
      login: {
        titleBar: "KARMA.PAY / تسجيل",
        qrExpires: "تجديد QR خلال",
        sec: "ث",
        mnemonicToggle: "دخول بالذاكرة السرّية",
        mnemonicHint: "استخدم جهازًا تثق به فقط.",
        wordLabel: "كلمة",
        mnemonicSubmit: "متابعة بالعبارة",
        mnemonicError: "عبارة غير صالحة.",
        statusInit: "جارٍ التهيئة…",
        statusConn: "امسح بالمحفظة. تجديد كل 60 ثانية.",
        statusNoConfig: "تسجيل الدخول غير متاح مؤقتًا. أعِد المحاولة لاحقًا.",
        cfgOnce: "",
        navGateway: "البوابة",
        navPro: "نظرة عامة",
        navLoyal: "بديل",
      },
    },
    es: {
      langLabel: "Idioma",
      gateway: {
        badge: "",
        step1: "PASO 1/2",
        step2: "PASO 2/2",
        footerHint: "",
        back: "Atrás",
        quizFooter: "",
        studioLogin: "Iniciar sesión",
        routeTitlePro: "Resumen",
        routeTextPro: "Continuar a la introducción del producto.",
        routeTitleLoyal: "Vista alternativa",
        routeTextLoyal: "Continuar a una presentación alternativa.",
        enter: "Continuar",
        q1h: "Elige la experiencia",
        q1q: "¿Qué quieres ver primero?",
        q1hint: "Solo unos segundos.",
        q1a: "Resumen del producto (recomendado)",
        q1b: "Vista alternativa",
        q1c: "No estoy seguro — recomendar",
        q2h: "Enfoque",
        q2q: "¿Qué es más importante ahora?",
        q2hint: "",
        q2a: "Claridad, confianza y marco compliance",
        q2b: "Velocidad, control y profundidad",
      },
      professional: {
        navGateway: "Gateway",
        navPro: "Resumen",
        navLoyal: "Alternativa",
        navLogin: "Iniciar sesión",
        heroKicker: "Liquidación no custodial",
        heroTitle: "Los fondos permanecen en las carteras del usuario.",
        heroLead: "KarmaPay ayuda a servicios de agentes con flujos factura primero.",
        probTitle: "Problema",
        probBody: "Los modelos de custodia concentran riesgos.",
        solTitle: "Qué hacemos",
        solBody: "Separar obligaciones de custodia — liquidación cuando se cumplen reglas.",
        ctaGateway: "Repetir cuestionario",
        ctaLogin: "Iniciar sesión",
        footNote: "Canales oficiales",
        footX: "X oficial:",
        footGh: "Repositorio:",
      },
      loyal: {
        navGateway: "Gateway",
        navPro: "Resumen",
        navLoyal: "Alternativa",
        navLogin: "Iniciar sesión",
        title: "Presentación ampliada",
        lead: "Liquidación no custodial para servicios de agentes: fondos en la cartera, factura primero, evidencia auditable.",
        b1: "Sin pool en plataforma",
        b2: "Factura primero",
        b3: "Disputas trazables",
        community: "Comunidad",
        communityHint: "Unirse (enlace después)",
        joinCta: "Unirse",
        ctaPro: "¿Vista profesional?",
        ctaLogin: "Iniciar sesión",
      },
      login: {
        titleBar: "KARMA.PAY / LOGIN",
        qrExpires: "QR se renueva en",
        sec: "s",
        mnemonicToggle: "Inicio con mnemónica",
        mnemonicHint: "Use solo un dispositivo de confianza.",
        wordLabel: "Palabra",
        mnemonicSubmit: "Continuar con frase",
        mnemonicError: "Frase inválida.",
        statusInit: "Inicializando…",
        statusConn: "Escanear con la wallet. QR cada 60s.",
        statusNoConfig: "Inicio de sesión no disponible temporalmente. Inténtelo más tarde.",
        cfgOnce: "",
        navGateway: "Gateway",
        navPro: "Resumen",
        navLoyal: "Leal",
      },
    },
  };

  function getLang() {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored && SUPPORTED.includes(stored)) return stored;
    return "en";
  }

  function setLang(code) {
    if (!SUPPORTED.includes(code)) return;
    localStorage.setItem(STORAGE_KEY, code);
    applyDocumentLang(code);
    if (typeof window.__karmaGatewayRerender === "function") window.__karmaGatewayRerender();
    if (typeof window.__karmaLoginRerender === "function") window.__karmaLoginRerender();
    document.querySelectorAll("[data-i18n-root]").forEach(function (root) {
      applyToRoot(root, code);
    });
  }

  function t(path) {
    const lang = getLang();
    const pack = DICT[lang] || DICT.en;
    const parts = path.split(".");
    let cur = pack;
    for (const p of parts) {
      cur = cur && cur[p];
    }
    if (typeof cur === "string") return cur;
    const fb = DICT.en;
    let c2 = fb;
    for (const p of parts) c2 = c2 && c2[p];
    return typeof c2 === "string" ? c2 : path;
  }

  function applyDocumentLang(code) {
    document.documentElement.lang = code === "zh" ? "zh-CN" : code;
    if (code === "ar") {
      document.documentElement.dir = "rtl";
    } else {
      document.documentElement.dir = "ltr";
    }
  }

  function applyToRoot(root, code) {
    const pack = DICT[code] || DICT.en;
    root.querySelectorAll("[data-i18n]").forEach(function (el) {
      const key = el.getAttribute("data-i18n");
      if (!key) return;
      const parts = key.split(".");
      let cur = pack;
      for (const p of parts) cur = cur && cur[p];
      if (typeof cur !== "string") {
        cur = key;
        let c2 = DICT.en;
        for (const p of parts) c2 = c2 && c2[p];
        if (typeof c2 === "string") cur = c2;
      }
      el.textContent = cur;
    });
  }

  function injectLanguageSwitcher(containerSelector) {
    const host = document.querySelector(containerSelector);
    if (!host) return;
    const id = "karma-lang-select";
    if (document.getElementById(id)) return;
    const wrap = document.createElement("div");
    wrap.className = "karma-lang-switch";
    wrap.style.cssText = "display:flex;align-items:center;gap:8px;";
    const lab = document.createElement("span");
    lab.className = "muted";
    lab.style.fontSize = "0.82rem";
    const sel = document.createElement("select");
    sel.id = id;
    sel.setAttribute("aria-label", "Language");
    const labels = {
      en: "English",
      ja: "日本語",
      ko: "한국어",
      zh: "中文",
      de: "Deutsch",
      fr: "Français",
      ar: "العربية",
      es: "Español",
    };
    SUPPORTED.forEach(function (code) {
      const o = document.createElement("option");
      o.value = code;
      o.textContent = labels[code] || code;
      sel.appendChild(o);
    });
    sel.value = getLang();
    sel.addEventListener("change", function () {
      setLang(sel.value);
      lab.textContent = t("langLabel") + ":";
    });
    lab.textContent = t("langLabel") + ":";
    wrap.appendChild(lab);
    wrap.appendChild(sel);
    host.appendChild(wrap);
    applyDocumentLang(getLang());
  }

  window.KarmaSiteLang = {
    SUPPORTED,
    getLang,
    setLang,
    t,
    applyToRoot,
    injectLanguageSwitcher,
    applyDocumentLang,
    DICT,
  };

  applyDocumentLang(getLang());
})();
