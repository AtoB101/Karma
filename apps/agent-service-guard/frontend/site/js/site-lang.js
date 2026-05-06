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
        badge: "Audience routing",
        step1: "STEP 1 / 2",
        step2: "STEP 2 / 2",
        footerHint: "Your choice is stored locally for future campaign relevance (no personal data sent).",
        back: "Back",
        quizFooter: "Your answers determine which public page fits you.",
        studioLogin: "Web3 login — user studio",
        routeTitlePro: "Professional overview",
        routeTextPro: "Trust-first copy, problem statement, and official links.",
        routeTitleLoyal: "Loyal / high-intent view",
        routeTextLoyal: "Same cyber energy as before: sovereignty, community, direct voice.",
        enter: "Continue",
        q1h: "Find your entry point",
        q1q: "Which option fits you best?",
        q1hint: "We route you to one of two public pages. No account required.",
        q1a: "I want a clear, professional overview (general audience).",
        q1b: "I want the bold, high-intent experience (loyal community style).",
        q1c: "Not sure — ask me one more question.",
        q2h: "One more question",
        q2q: "What should we prioritize for you today?",
        q2hint: "Helps us label your segment for future campaigns (stored in this browser only).",
        q2a: "Trust, clarity, and verifiable settlement facts.",
        q2b: "Speed, control, and community energy.",
      },
      professional: {
        navGateway: "Gateway",
        navPro: "Overview",
        navLoyal: "Loyal",
        navLogin: "Web3 login",
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
        ctaGateway: "Retake routing quiz",
        ctaLogin: "Open user studio",
        footNote: "Official channels (placeholders — replace when ready)",
        footX: "Official X:",
        footGh: "Repository:",
      },
      loyal: {
        navGateway: "Gateway",
        navPro: "Overview",
        navLoyal: "Loyal",
        navLogin: "Web3 login",
        title: "Loyal view",
        lead:
          "For builders and power users who want the direct story: sovereignty over settlement rails, verifiable bills, and less middleman drag.",
        b1: "No platform slush fund — funds stay user-side until rules say otherwise.",
        b2: "Bill-first — evidence and state you can audit.",
        b3: "Disputes anchored in process, not opaque queues.",
        community: "Community",
        communityHint: "Join the community (link placeholder — add your Discord / Telegram / etc.).",
        joinCta: "Join community",
        ctaPro: "Prefer the professional overview?",
        ctaLogin: "Web3 login — studio",
      },
      login: {
        titleBar: "KARMA.PAY / LOGIN",
        qrExpires: "QR refreshes in",
        sec: "s",
        mnemonicToggle: "Log in with recovery phrase (12 words)",
        mnemonicHint: "Demo only — never enter a real seed on shared devices.",
        wordLabel: "Word",
        mnemonicSubmit: "Continue with phrase",
        mnemonicError: "Invalid phrase. Check spelling and order (BIP-39 English).",
        statusInit: "Initializing…",
        statusConn: "Scan with your wallet. QR rotates every 60 seconds.",
        cfgOnce: "WalletConnect Project ID (saved in this browser)",
        navGateway: "Gateway",
        navPro: "Overview",
        navLoyal: "Loyal",
      },
    },
    ja: {
      langLabel: "言語",
      gateway: {
        badge: "オーディエンス振分",
        step1: "ステップ 1/2",
        step2: "ステップ 2/2",
        footerHint: "選択はキャンペーン用にローカル保存（個人情報は送信されません）。",
        back: "戻る",
        quizFooter: "回答に応じて公開ページを振り分けます。",
        studioLogin: "Web3 ログイン — スタジオ",
        routeTitlePro: "プロ向け概要",
        routeTextPro: "信頼重視の説明、課題提示、公式リンク。",
        routeTitleLoyal: "忠実ユーザー向け",
        routeTextLoyal: "高意図・コミュニティ色の強いビュー。",
        enter: "進む",
        q1h: "入口を選ぶ",
        q1q: "どれに近いですか？",
        q1hint: "公開ページは2種類から選ばれます。アカウント不要。",
        q1a: "わかりやすいプロ品質の概要が欲しい。",
        q1b: "ダイレクトで熱量の高い体験が欲しい。",
        q1c: "わからない — もう一問。",
        q2h: "もう一問",
        q2q: "今日は何を優先しますか？",
        q2hint: "キャンペーン向けセグメント（このブラウザのみ保存）。",
        q2a: "信頼・明瞭さ・検証可能な決済。",
        q2b: "速度・主権・コミュニティの熱量。",
      },
      professional: {
        navGateway: "ゲートウェイ",
        navPro: "概要",
        navLoyal: "ロイヤル",
        navLogin: "Web3",
        heroKicker: "ノンカストディ決済",
        heroTitle: "資金はユーザーウォレットに。ルールで実行。",
        heroLead:
          "KarmaPay はエージェントサービス向けに請求優先フローを提供し、プラットフォーム預かりを減らし、状態を監査可能にします。",
        probTitle: "課題",
        probBody: "カストディ型は資金をプールし、ルールを不明瞭にし、出金を遅らせます。",
        solTitle: "提供すること",
        solBody: "預託と義務を分離し、条件達成時の決済と第三者が見れる証跡を重視します。",
        ctaGateway: "振分クイズをやり直す",
        ctaLogin: "スタジオを開く",
        footNote: "公式チャネル（プレースホルダ）",
        footX: "公式 X:",
        footGh: "リポジトリ:",
      },
      loyal: {
        navGateway: "ゲートウェイ",
        navPro: "概要",
        navLoyal: "ロイヤル",
        navLogin: "Web3",
        title: "ロイヤルビュー",
        lead: "ビルダー向けのストレートな説明：決済レールの主権と検証可能な請求。",
        b1: "プラットフォーム資金プールを避け、ユーザーサイドに。",
        b2: "請求ファーストで証跡を監査可能に。",
        b3: "不透明なキューではなく、プロセスに沿った争い。",
        community: "コミュニティ",
        communityHint: "コミュニティ参加（リンクは後で設定）。",
        joinCta: "参加する",
        ctaPro: "プロ概要が良い？",
        ctaLogin: "Web3 — スタジオ",
      },
      login: {
        titleBar: "KARMA.PAY / ログイン",
        qrExpires: "QR 更新まで",
        sec: "秒",
        mnemonicToggle: "シードフレーズ（12語）でログイン",
        mnemonicHint: "デモのみ — 共有端末で本物のシードを入力しないでください。",
        wordLabel: "語",
        mnemonicSubmit: "フレーズで続行",
        mnemonicError: "無効なフレーズです。",
        statusInit: "初期化中…",
        statusConn: "ウォレットでスキャン。QR は 60 秒ごとに更新。",
        cfgOnce: "WalletConnect Project ID（このブラウザに保存）",
        navGateway: "ゲートウェイ",
        navPro: "概要",
        navLoyal: "ロイヤル",
      },
    },
    ko: {
      langLabel: "언어",
      gateway: {
        badge: "라우팅",
        step1: "1/2 단계",
        step2: "2/2 단계",
        footerHint: "선택은 캠페인용으로 로컬 저장됩니다.",
        back: "뒤로",
        quizFooter: "답에 따라 공개 페이지가 결정됩니다.",
        studioLogin: "Web3 로그인 — 스튜디오",
        routeTitlePro: "전문가용 개요",
        routeTextPro: "신뢰 중심 설명 및 공식 링크.",
        routeTitleLoyal: "충성 사용자 뷰",
        routeTextLoyal: "고의도·커뮤니티 스타일.",
        enter: "계속",
        q1h: "입구 선택",
        q1q: "어디에 가깝습니까?",
        q1hint: "두 가지 공개 페이지 중 하나로 연결됩니다.",
        q1a: "명확하고 전문적인 개요.",
        q1b: "대담한 고의도 경험.",
        q1c: "잘 모르겠음 — 한 질문 더.",
        q2h: "한 질문 더",
        q2q: "오늘 무엇을 우선할까요?",
        q2hint: "세그먼트 라벨(로컬만).",
        q2a: "신뢰·명확성·검증 가능한 정산.",
        q2b: "속도·통제·커뮤니티 에너지.",
      },
      professional: {
        navGateway: "게이트웨이",
        navPro: "개요",
        navLoyal: "로열",
        navLogin: "Web3",
        heroKicker: "비수탁 정산",
        heroTitle: "자금은 사용자 지갑에. 규칙으로 실행.",
        heroLead: "KarmaPay는 청구 우선 흐름으로 에이전트 서비스 정산을 돕습니다.",
        probTitle: "문제",
        probBody: "수탁 모델은 자금을 모으고 규칙을 불투명하게 합니다.",
        solTitle: "우리가 하는 일",
        solBody: "의무와 수탁을 분리하고 조건 충족 시 정산과 감사 가능한 상태를 제공합니다.",
        ctaGateway: "퀴즈 다시",
        ctaLogin: "스튜디오 열기",
        footNote: "공식 채널(플레이스홀더)",
        footX: "공식 X:",
        footGh: "저장소:",
      },
      loyal: {
        navGateway: "게이트웨이",
        navPro: "개요",
        navLoyal: "로열",
        navLogin: "Web3",
        title: "로열 뷰",
        lead: "파워 유저용 직설: 정산 주권과 검증 가능한 청구.",
        b1: "플랫폼 풀 없이 사용자 측 자금.",
        b2: "청구 우선 — 감사 가능.",
        b3: "불투명한 대기열이 아닌 프로세스.",
        community: "커뮤니티",
        communityHint: "커뮤니티 링크(나중에 추가).",
        joinCta: "참여",
        ctaPro: "전문 개요가 필요하신가요?",
        ctaLogin: "Web3 — 스튜디오",
      },
      login: {
        titleBar: "KARMA.PAY / 로그인",
        qrExpires: "QR 갱신까지",
        sec: "초",
        mnemonicToggle: "니모닉(12단어)으로 로그인",
        mnemonicHint: "데모 전용 — 실제 시드 입력 금지.",
        wordLabel: "단어",
        mnemonicSubmit: "니모닉으로 계속",
        mnemonicError: "유효하지 않은 니모닉입니다.",
        statusInit: "초기화 중…",
        statusConn: "지갑으로 스캔. QR은 60초마다 갱신.",
        cfgOnce: "WalletConnect Project ID",
        navGateway: "게이트웨이",
        navPro: "개요",
        navLoyal: "로열",
      },
    },
    zh: {
      langLabel: "语言",
      gateway: {
        badge: "人群分流",
        step1: "第 1 / 2 步",
        step2: "第 2 / 2 步",
        footerHint: "选择仅保存在本地浏览器，用于后续活动分段。",
        back: "返回",
        quizFooter: "答案决定展示哪一版公开页。",
        studioLogin: "Web3 登录 — 用户端",
        routeTitlePro: "专业概览",
        routeTextPro: "信任导向、问题陈述与官方链接。",
        routeTitleLoyal: "忠实用户版",
        routeTextLoyal: "高能、直接的社区向呈现。",
        enter: "继续",
        q1h: "选择入口",
        q1q: "你更偏向哪一种？",
        q1hint: "系统将二选一公开页，无需注册。",
        q1a: "我要清晰、专业的介绍（普通用户）。",
        q1b: "我要强烈、高意向的体验（忠实用户风格）。",
        q1c: "不确定 — 再问我一题。",
        q2h: "再一题",
        q2q: "今天你最看重什么？",
        q2hint: "用于本地分段标记，不向服务器发送个人信息。",
        q2a: "信任、清晰、可验证结算。",
        q2b: "速度、掌控与社区能量。",
      },
      professional: {
        navGateway: "入口",
        navPro: "概览",
        navLoyal: "忠实版",
        navLogin: "Web3 登录",
        heroKicker: "非托管结算",
        heroTitle: "资金留在用户钱包，用规则执行。",
        heroLead: "KarmaPay 为智能体服务提供账单优先流程，减少平台沉淀资金，状态可审计。",
        probTitle: "问题",
        probBody: "托管模式沉淀用户资金、规则不透明、提现慢，集中风险并削弱信任。",
        solTitle: "我们做什么",
        solBody: "区分托管与合约义务：条件满足时结算稳定币，过程与证据可被第三方复核。",
        ctaGateway: "重新做分流题",
        ctaLogin: "打开用户端",
        footNote: "官方渠道（占位，后续替换）",
        footX: "官方 X:",
        footGh: "仓库:",
      },
      loyal: {
        navGateway: "入口",
        navPro: "概览",
        navLoyal: "忠实版",
        navLogin: "Web3 登录",
        title: "忠实用户版",
        lead: "面向_builder 与高能用户：强调结算主权、可验证账单、减少中间环节。",
        b1: "避免平台资金池，资金在用户侧。",
        b2: "账单优先 — 状态可审计。",
        b3: "争议流程可追踪，而非黑箱排队。",
        community: "社区",
        communityHint: "加入社区（链接占位，后续填写 Discord/Telegram 等）",
        joinCta: "加入社区",
        ctaPro: "想看专业概览？",
        ctaLogin: "Web3 — 用户端",
      },
      login: {
        titleBar: "KARMA.PAY / 登录",
        qrExpires: "二维码刷新还剩",
        sec: "秒",
        mnemonicToggle: "使用助记词（12 个词）登录",
        mnemonicHint: "仅演示 — 切勿在公共设备输入真实助记词。",
        wordLabel: "词",
        mnemonicSubmit: "使用助记词继续",
        mnemonicError: "助记词无效，请检查拼写与顺序（BIP-39 英文）。",
        statusInit: "初始化中…",
        statusConn: "用钱包扫码；二维码每 60 秒刷新。",
        cfgOnce: "WalletConnect Project ID（保存在本浏览器）",
        navGateway: "入口",
        navPro: "概览",
        navLoyal: "忠实版",
      },
    },
    de: {
      langLabel: "Sprache",
      gateway: {
        badge: "Routing",
        step1: "SCHRITT 1/2",
        step2: "SCHRITT 2/2",
        footerHint: "Lokal gespeichert für Kampagnen-Segmentierung.",
        back: "Zurück",
        quizFooter: "Ihre Antworten bestimmen die öffentliche Seite.",
        studioLogin: "Web3 Login — Studio",
        routeTitlePro: "Professionelle Übersicht",
        routeTextPro: "Vertrauen, Problemstellung, offizielle Links.",
        routeTitleLoyal: "Loyal / High-Intent",
        routeTextLoyal: "Direkte Community-Stimme.",
        enter: "Weiter",
        q1h: "Einstieg wählen",
        q1q: "Was passt am besten?",
        q1hint: "Zwei öffentliche Seiten, kein Konto nötig.",
        q1a: "Klare professionelle Übersicht.",
        q1b: "Kühne High-Intent-Erfahrung.",
        q1c: "Unsicher — eine Frage mehr.",
        q2h: "Noch eine Frage",
        q2q: "Was ist heute wichtiger?",
        q2hint: "Segment (nur lokal).",
        q2a: "Vertrauen, Klarheit, prüfbare Abwicklung.",
        q2b: "Geschwindigkeit, Kontrolle, Community.",
      },
      professional: {
        navGateway: "Gateway",
        navPro: "Übersicht",
        navLoyal: "Loyal",
        navLogin: "Web3",
        heroKicker: "Nicht-verwahrte Abwicklung",
        heroTitle: "Geld bleibt in Nutzer-Wallets. Regeln ausführen.",
        heroLead:
          "KarmaPay unterstützt Agent-Services mit rechnungs-first Flows und auditierbarem Zustand.",
        probTitle: "Problem",
        probBody: "Verwahrmodelle bündeln Risiken und verzögern Auszahlungen.",
        solTitle: "Was wir tun",
        solBody: "Verpflichtungen trennen von Verwahrung — Abrechnung bei erfüllten Bedingungen.",
        ctaGateway: "RoutingQuiz erneut",
        ctaLogin: "Studio öffnen",
        footNote: "Offizielle Kanäle (Platzhalter)",
        footX: "Offizielles X:",
        footGh: "Repository:",
      },
      loyal: {
        navGateway: "Gateway",
        navPro: "Übersicht",
        navLoyal: "Loyal",
        navLogin: "Web3",
        title: "Loyal-Ansicht",
        lead: "Für Power-User: Souveränität, prüfbare Rechnungen.",
        b1: "Kein Plattform-Pool",
        b2: "Bill-first, auditierbar",
        b3: "Streit nachvollziehbar",
        community: "Community",
        communityHint: "Community beitreten (Link später)",
        joinCta: "Beitreten",
        ctaPro: "Professionelle Übersicht?",
        ctaLogin: "Web3 — Studio",
      },
      login: {
        titleBar: "KARMA.PAY / LOGIN",
        qrExpires: "QR erneuert in",
        sec: "s",
        mnemonicToggle: "Mit Recovery Phrase (12 Wörter)",
        mnemonicHint: "Nur Demo — keine echten Seeds.",
        wordLabel: "Wort",
        mnemonicSubmit: "Mit Phrase fortfahren",
        mnemonicError: "Ungültige Phrase.",
        statusInit: "Initialisiere…",
        statusConn: "Wallet scannen. QR alle 60s neu.",
        cfgOnce: "WalletConnect Project ID",
        navGateway: "Gateway",
        navPro: "Übersicht",
        navLoyal: "Loyal",
      },
    },
    fr: {
      langLabel: "Langue",
      gateway: {
        badge: "Routage",
        step1: "ÉTAPE 1/2",
        step2: "ÉTAPE 2/2",
        footerHint: "Stocké localement pour le ciblage.",
        back: "Retour",
        quizFooter: "Vos réponses choisissent la page publique.",
        studioLogin: "Web3 — studio",
        routeTitlePro: "Vue professionnelle",
        routeTextPro: "Confiance, problème, liens officiels.",
        routeTitleLoyal: "Vue loyal / fort engagement",
        routeTextLoyal: "Style communautaire direct.",
        enter: "Continuer",
        q1h: "Choisissez une entrée",
        q1q: "Quelle option vous correspond ?",
        q1hint: "Deux pages publiques, sans compte.",
        q1a: "Aperçu professionnel clair.",
        q1b: "Expérience forte et directe.",
        q1c: "Pas sûr — une question de plus.",
        q2h: "Encore une question",
        q2q: "Quelle priorité aujourd’hui ?",
        q2hint: "Segment (local seulement).",
        q2a: "Confiance, clarté, règlement vérifiable.",
        q2b: "Vitesse, contrôle, énergie communautaire.",
      },
      professional: {
        navGateway: "Passerelle",
        navPro: "Aperçu",
        navLoyal: "Loyal",
        navLogin: "Web3",
        heroKicker: "Règlement non dépositaire",
        heroTitle: "Les fonds restent dans les portefeuilles.",
        heroLead: "KarmaPay aide les services d’agents avec des flux facture d’abord.",
        probTitle: "Problème",
        probBody: "Les modèles dépositaires concentrent les risques.",
        solTitle: "Ce que nous faisons",
        solBody: "Séparer garde et obligations — règlement quand les conditions sont remplies.",
        ctaGateway: "Refaire le quiz",
        ctaLogin: "Ouvrir le studio",
        footNote: "Canaux officiels (placeholder)",
        footX: "X officiel :",
        footGh: "Dépôt :",
      },
      loyal: {
        navGateway: "Passerelle",
        navPro: "Aperçu",
        navLoyal: "Loyal",
        navLogin: "Web3",
        title: "Vue loyal",
        lead: "Pour utilisateurs avancés : souveraineté et factures vérifiables.",
        b1: "Pas de pool plateforme",
        b2: "Facture d’abord",
        b3: "Litiges traçables",
        community: "Communauté",
        communityHint: "Rejoindre (lien plus tard)",
        joinCta: "Rejoindre",
        ctaPro: "Vue professionnelle ?",
        ctaLogin: "Web3 — studio",
      },
      login: {
        titleBar: "KARMA.PAY / LOGIN",
        qrExpires: "QR renouvelé dans",
        sec: "s",
        mnemonicToggle: "Phrase de récupération (12 mots)",
        mnemonicHint: "Démo seulement.",
        wordLabel: "Mot",
        mnemonicSubmit: "Continuer avec la phrase",
        mnemonicError: "Phrase invalide.",
        statusInit: "Initialisation…",
        statusConn: "Scannez avec le wallet. QR 60s.",
        cfgOnce: "WalletConnect Project ID",
        navGateway: "Passerelle",
        navPro: "Aperçu",
        navLoyal: "Loyal",
      },
    },
    ar: {
      langLabel: "اللغة",
      gateway: {
        badge: "التوجيه",
        step1: "الخطوة 1/2",
        step2: "الخطوة 2/2",
        footerHint: "يُحفظ محليًا لاستهداف الحملات.",
        back: "رجوع",
        quizFooter: "تُحدد إجاباتك الصفحة العامة.",
        studioLogin: "Web3 — الاستوديو",
        routeTitlePro: "نظرة احترافية",
        routeTextPro: "ثقة ومشكلة وروابط رسمية.",
        routeTitleLoyal: "نسخة المستخدمين المخلصين",
        routeTextLoyal: "أسلوب مباشر وعالي النية.",
        enter: "متابعة",
        q1h: "اختر نقطة الدخول",
        q1q: "أي خيار يناسبك؟",
        q1hint: "صفحتان عامتان، دون حساب.",
        q1a: "أريد نظرة مهنية واضحة.",
        q1b: "أريد تجربة قوية ومباشرة.",
        q1c: "لست متأكدًا — سؤال آخر.",
        q2h: "سؤال إضافي",
        q2q: "ما الأهم اليوم؟",
        q2hint: "شريحة محلية فقط.",
        q2a: "الثقة والوضوح والتسوية القابلة للتحقق.",
        q2b: "السرعة والسيطرة وطاقة المجتمع.",
      },
      professional: {
        navGateway: "البوابة",
        navPro: "نظرة عامة",
        navLoyal: "المخلصون",
        navLogin: "Web3",
        heroKicker: "تسوية غير وصائية",
        heroTitle: "الأموال تبقى في محافظ المستخدمين.",
        heroLead: "تساعد KarmaPay خدمات الوكلاء بتدفقات الفاتورة أولًا.",
        probTitle: "المشكلة",
        probBody: "نماذج الحجز تركز المخاطر وتؤخر السداد.",
        solTitle: "ما نفعله",
        solBody: "فصل الضمان عن الالتزامات — تسوية عند تحقق الشروط.",
        ctaGateway: "إعادة الاختبار",
        ctaLogin: "افتح الاستوديو",
        footNote: "قنوات رسمية (عناصر نائبة)",
        footX: "X الرسمي:",
        footGh: "المستودع:",
      },
      loyal: {
        navGateway: "البوابة",
        navPro: "نظرة عامة",
        navLoyal: "المخلصون",
        navLogin: "Web3",
        title: "عرض المخلصين",
        lead: "للمستخدمين المتقدمين: سيادة التسوية وفواتير قابلة للتحقق.",
        b1: "لا تجمع منصة",
        b2: "الفاتورة أولاً",
        b3: "نزاعات يمكن تتبعها",
        community: "المجتمع",
        communityHint: "انضمام (الرابط لاحقًا)",
        joinCta: "انضم",
        ctaPro: "النسخة المهنية؟",
        ctaLogin: "Web3 — الاستوديو",
      },
      login: {
        titleBar: "KARMA.PAY / تسجيل",
        qrExpires: "تجديد QR خلال",
        sec: "ث",
        mnemonicToggle: "دخول بعبارة استرداد (12 كلمة)",
        mnemonicHint: "تجريبي فقط.",
        wordLabel: "كلمة",
        mnemonicSubmit: "متابعة بالعبارة",
        mnemonicError: "عبارة غير صالحة.",
        statusInit: "جارٍ التهيئة…",
        statusConn: "امسح بالمحفظة. تجديد كل 60 ثانية.",
        cfgOnce: "WalletConnect Project ID",
        navGateway: "البوابة",
        navPro: "نظرة عامة",
        navLoyal: "المخلصون",
      },
    },
    es: {
      langLabel: "Idioma",
      gateway: {
        badge: "Enrutamiento",
        step1: "PASO 1/2",
        step2: "PASO 2/2",
        footerHint: "Guardado localmente para campañas.",
        back: "Atrás",
        quizFooter: "Tus respuestas eligen la página pública.",
        studioLogin: "Web3 — estudio",
        routeTitlePro: "Vista profesional",
        routeTextPro: "Confianza, problema, enlaces oficiales.",
        routeTitleLoyal: "Vista leal",
        routeTextLoyal: "Estilo directo y de comunidad.",
        enter: "Continuar",
        q1h: "Elige entrada",
        q1q: "¿Qué opción encaja?",
        q1hint: "Dos páginas públicas, sin cuenta.",
        q1a: "Resumen profesional claro.",
        q1b: "Experiencia intensa y directa.",
        q1c: "No estoy seguro — otra pregunta.",
        q2h: "Otra pregunta",
        q2q: "¿Qué priorizas hoy?",
        q2hint: "Segmento solo local.",
        q2a: "Confianza, claridad, liquidación verificable.",
        q2b: "Velocidad, control, energía comunitaria.",
      },
      professional: {
        navGateway: "Gateway",
        navPro: "Resumen",
        navLoyal: "Leal",
        navLogin: "Web3",
        heroKicker: "Liquidación no custodial",
        heroTitle: "Los fondos permanecen en las carteras del usuario.",
        heroLead: "KarmaPay ayuda a servicios de agentes con flujos factura primero.",
        probTitle: "Problema",
        probBody: "Los modelos de custodia concentran riesgos.",
        solTitle: "Qué hacemos",
        solBody: "Separar obligaciones de custodia — liquidación cuando se cumplen reglas.",
        ctaGateway: "Repetir cuestionario",
        ctaLogin: "Abrir estudio",
        footNote: "Canales oficiales (placeholder)",
        footX: "X oficial:",
        footGh: "Repositorio:",
      },
      loyal: {
        navGateway: "Gateway",
        navPro: "Resumen",
        navLoyal: "Leal",
        navLogin: "Web3",
        title: "Vista leal",
        lead: "Para usuarios avanzados: soberanía y facturas verificables.",
        b1: "Sin pool en plataforma",
        b2: "Factura primero",
        b3: "Disputas trazables",
        community: "Comunidad",
        communityHint: "Unirse (enlace después)",
        joinCta: "Unirse",
        ctaPro: "¿Vista profesional?",
        ctaLogin: "Web3 — estudio",
      },
      login: {
        titleBar: "KARMA.PAY / LOGIN",
        qrExpires: "QR se renueva en",
        sec: "s",
        mnemonicToggle: "Frase de recuperación (12 palabras)",
        mnemonicHint: "Solo demo.",
        wordLabel: "Palabra",
        mnemonicSubmit: "Continuar con frase",
        mnemonicError: "Frase inválida.",
        statusInit: "Inicializando…",
        statusConn: "Escanear con la wallet. QR cada 60s.",
        cfgOnce: "WalletConnect Project ID",
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
