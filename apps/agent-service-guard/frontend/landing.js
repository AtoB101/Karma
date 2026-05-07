/**
 * Karma marketing portal i18n (no network). Console entry stays on web3-login.html.
 */
const LANDING_LANG_KEY = "karma_landing_lang";

const LANG_GROUPS = [
  { label: "Global", codes: ["en", "zh", "ja", "ko", "de", "fr", "es", "pt", "it", "ru", "ar"] },
  { label: "Southeast Asia", codes: ["th", "vi", "id", "ms", "fil"] },
  { label: "Africa", codes: ["sw", "ha", "am", "zu"] },
];

const LANG_LABELS = {
  en: "English",
  zh: "中文",
  ja: "日本語",
  ko: "한국어",
  de: "Deutsch",
  fr: "Français",
  es: "Español",
  pt: "Português",
  it: "Italiano",
  ru: "Русский",
  ar: "العربية",
  th: "ไทย",
  vi: "Tiếng Việt",
  id: "Bahasa Indonesia",
  ms: "Bahasa Melayu",
  fil: "Filipino",
  sw: "Kiswahili",
  ha: "Hausa",
  am: "አማርኛ",
  zu: "isiZulu",
};

const ALL_LANG_CODES = LANG_GROUPS.flatMap((g) => g.codes);

const EN = {
  meta_title: "Karma Protected｜Trusted AI service commerce",
  meta_desc:
    "Buyer funds lock first; seller performance bond. Evidence-backed delivery, dispute freezes, and rules-based settlement for AI agents, APIs, and digital services.",
  brand_domain: "karma-network.ai",
  nav_pain: "Pain points",
  nav_solution: "Protection",
  nav_users: "Who it’s for",
  nav_security: "Security design",
  nav_sign_in: "Sign in",
  nav_how_btn: "How it works",
  nav_console_btn: "Open console",
  hero_badge: "Karma Protected",
  hero_h2_line1: "AI service deals shouldn’t rely on luck.",
  hero_h2_line2: "Funds lock first. Evidence settles disputes.",
  hero_lead:
    "Buyers lock funds; sellers post a performance bond. Delivery generates evidence; disputes can freeze funds; confirmation triggers settlement. Built for agents, APIs, AI automation, and digital delivery teams.",
  hero_cta_console: "Open console",
  hero_cta_how: "See how protection works",
  pill_1: "Buyer lock",
  pill_2: "Seller bond",
  pill_3: "Auto evidence",
  pill_4: "Dispute freeze",
  pill_5: "Auto settlement",
  mock_title: "Protected order",
  mock_seller_tag: "A+ seller",
  mm_buyer: "Buyer locked",
  mm_bond: "Seller bond",
  mm_excess: "Extra lock",
  mm_settle: "Settleable",
  f1_t: "AI Data API",
  f1_s: "Evidence ready · awaiting confirmation",
  f1_tag: "Pending settlement",
  f2_t: "AI video delivery",
  f2_s: "Bond frozen · more proof needed",
  f2_tag: "In dispute",
  f3_t: "Trust badge",
  f3_s: "High-assurance seller · visible to buyers",
  f3_tag: "Protected",
  pain_h: "The hard part isn’t paying.",
  pain_p: "Buyers fear paying first; sellers fear unpaid work; after delivery, disputes lack proof.",
  c1_h: "Buyers hesitate",
  c1_p: "Hard to tell if the service is real, delivery is valid, or the seller will disappear.",
  c2_h: "Sellers get stiffed",
  c2_p: "Digital work is easy to copy, deny, or dispute without strong records.",
  c3_h: "Disputes lack evidence",
  c3_p: "Without request/response logs, outputs, and attestations, resolution becomes arguing.",
  sol_h: "How Karma protects deals",
  sol_p: "Every protected order follows one state machine: funds, responsibility, evidence, disputes, settlement.",
  st1_h: "Create a protected order",
  st1_p: "Define scope, price, delivery standard, and confirmation window.",
  st2_h: "Buyer locks funds",
  st2_p: "Buyer locks the full amount to prove ability to pay.",
  st3_h: "Seller locks bond",
  st3_p: "Seller locks minimum performance bond for baseline recourse.",
  st4_h: "Evidence auto-captured",
  st4_p: "Requests, responses, execution logs, and delivery proofs are recorded.",
  st5_h: "Settle or freeze",
  st5_p: "Confirm to release funds; disputes freeze relevant amounts for resolution.",
  users_h: "Who should use Karma",
  users_p: "Remote delivery, automated execution, cross-border payments, or dispute-prone services.",
  sell_panel_h: "Built for sellers",
  sb1_b: "Agent service sellers",
  sb1_p: "Automated tasks and outputs need trustworthy collection and evidence.",
  sb2_b: "API / data providers",
  sb2_p: "Per-call, per-package, or per-result billing maps cleanly to usage evidence.",
  sb3_b: "AI automation teams",
  sb3_p: "Video, content, marketing, bots, and workflows delivered digitally.",
  buy_panel_h: "What buyers gain",
  bb1_b: "Funds don’t release blindly",
  bb1_p: "Until delivery is clear, funds aren’t handed to the seller.",
  bb2_b: "Seller bond backs the deal",
  bb2_p: "Default scenarios have a funded baseline for remediation.",
  bb3_b: "Evidence is traceable",
  bb3_p: "Each order keeps execution and delivery records for disputes.",
  sec_h: "Marketing site is the front door; trading happens in the isolated console.",
  sec_p:
    "This site explains the product and routes you to the console. Wallet connection, orders, locks, signatures, evidence, and disputes run in a dedicated console — not here — so the homepage stays clean and we never ask for seed phrases on the brochure page.",
  sec_cta_console: "Open console",
  sec_cta_how: "How protection works",
  rw_site: "Website",
  rw_site_v: "Learn & enter",
  rw_wallet: "Wallet connect",
  rw_wallet_v: "In console",
  rw_orders: "Orders & locks",
  rw_orders_v: "In console",
  rw_keys: "Private keys / seed",
  rw_keys_v: "Never collected",
  rw_evid: "Evidence & disputes",
  rw_evid_v: "In console",
  cta_h: "Start with Karma Protected",
  cta_p:
    "Open the isolated console to create protected orders, set seller bonds, manage lock balances, review evidence bundles, and handle settlement and disputes.",
  cta_go: "Open console",
  cta_learn: "Learn the mechanics first",
  studio_hint: "Wallet sign-in uses a separate page. Do not enter a seed phrase on this marketing site.",
  foot1: "© 2026 Karma Network. Trust infrastructure for AI commerce.",
  foot2: "Karma Protected · Karma Evidence · Karma Score · Karma Resolve",
};

const ZH = {
  meta_title: "Karma Protected｜可信 AI 服务交易网络",
  meta_desc:
    "买家先锁款，卖家锁责任金。交付有证据，争议可冻结，确认后自动结算。面向 Agent、API、AI 自动化与数字交付团队的可信交易保护。",
  brand_domain: "karma-network.ai",
  nav_pain: "交易痛点",
  nav_solution: "保护机制",
  nav_users: "适合用户",
  nav_security: "安全设计",
  nav_sign_in: "登录",
  nav_how_btn: "查看机制",
  nav_console_btn: "进入操作台",
  hero_badge: "Karma Protected",
  hero_h2_line1: "让 AI 服务交易",
  hero_h2_line2: "不再靠运气。",
  hero_lead:
    "买家先锁款，卖家锁责任金。交付有证据，争议可冻结，确认后自动结算。Karma 为 Agent、API、AI 自动化服务和数字交付团队提供可信交易保护。",
  hero_cta_console: "进入操作台",
  hero_cta_how: "查看如何保护交易",
  pill_1: "买家锁款",
  pill_2: "卖家责任金",
  pill_3: "自动证据",
  pill_4: "争议冻结",
  pill_5: "自动结算",
  mock_title: "Protected Order",
  mock_seller_tag: "A+ Seller",
  mm_buyer: "买家锁款",
  mm_bond: "卖家责任金",
  mm_excess: "超额锁仓",
  mm_settle: "可结算",
  f1_t: "AI Data API 服务",
  f1_s: "证据已生成 · 等待确认",
  f1_tag: "待结算",
  f2_t: "AI 视频交付",
  f2_s: "责任金冻结 · 等待补证",
  f2_tag: "争议中",
  f3_t: "Trust Badge",
  f3_s: "高保障卖家 · 买家可见",
  f3_tag: "Protected",
  pain_h: "交易真正的问题，不是付款。",
  pain_p: "真实交易里最难的是：买家不敢先付，卖家怕被白嫖，交付后争议没有证据。",
  c1_h: "买家不敢付款",
  c1_p: "服务是否真实执行、交付是否有效、卖家是否会跑路，买家很难提前判断。",
  c2_h: "卖家怕被白嫖",
  c2_p: "数字服务交付后容易被复制、否认、拖款或恶意争议，卖家缺少保护。",
  c3_h: "争议没有证据",
  c3_p: "没有完整调用记录、输出记录、交付证明和签名，最后只能靠扯皮。",
  sol_h: "Karma 怎么保护交易",
  sol_p: "每一笔受保护订单都经过同一套状态机：资金、责任、证据、争议、结算全部有规则。",
  st1_h: "创建受保护订单",
  st1_p: "明确服务内容、价格、交付标准和确认时间。",
  st2_h: "买家锁款",
  st2_p: "买家锁定订单全额，证明具备付款能力。",
  st3_h: "卖家锁责任金",
  st3_p: "卖家锁定最低违约金，提供基础赔付能力。",
  st4_h: "自动生成证据",
  st4_p: "记录请求、响应、执行日志和交付证明。",
  st5_h: "结算或冻结",
  st5_p: "确认后放款；争议时冻结并进入处理流程。",
  users_h: "谁适合使用 Karma",
  users_p: "只要你的服务需要远程交付、自动执行、跨境收款或争议保护，就适合接入 Karma Protected。",
  sell_panel_h: "适合卖家",
  buy_panel_h: "买家获得什么",
  sb1_b: "Agent 服务卖家",
  sb1_p: "自动执行任务、自动交付结果，需要可信收款与证据记录。",
  sb2_b: "API / 数据服务商",
  sb2_p: "按次调用、按包收费、按结果交付，适合自动生成调用证据。",
  sb3_b: "AI 自动化团队",
  sb3_p: "提供视频、内容、营销、脚本、Bot、工作流等数字服务。",
  bb1_b: "资金不乱放",
  bb1_p: "交付不清楚，资金不会直接释放给卖家。",
  bb2_b: "卖家有责任金",
  bb2_p: "卖家违约时，系统有基础赔付来源。",
  bb3_b: "证据可追溯",
  bb3_p: "每笔订单都有执行记录、交付记录和争议材料。",
  sec_h: "官网只做入口，交易进入独立操作台。",
  sec_p:
    "官网用于了解产品、查看机制、进入 Console。钱包连接、订单创建、锁仓、签名、证据和争议处理都在独立操作台完成。这样既保持商业官网的清晰转化，也避免在官网页面采集钱包、密钥等敏感内容。",
  sec_cta_console: "进入操作台",
  sec_cta_how: "查看保护机制",
  rw_site: "官网",
  rw_site_v: "介绍与入口",
  rw_wallet: "钱包连接",
  rw_wallet_v: "Console 完成",
  rw_orders: "订单与锁仓",
  rw_orders_v: "Console 完成",
  rw_keys: "私钥 / 助记词",
  rw_keys_v: "不采集",
  rw_evid: "证据与争议",
  rw_evid_v: "Console 管理",
  cta_h: "开始使用 Karma Protected",
  cta_p:
    "进入独立操作台，创建受保护订单，设置卖家责任金，管理锁仓资金，查看证据包，并处理结算与争议。",
  cta_go: "进入操作台",
  cta_learn: "先了解工作原理",
  studio_hint: "登录与签名在独立页面完成。请勿在本站输入助记词或私钥。",
  foot1: "© 2026 Karma Network. Trust Infrastructure for AI Commerce.",
  foot2: "Karma Protected · Karma Evidence · Karma Score · Karma Resolve",
};

function merge(base, patch) {
  return { ...base, ...patch };
}

/** Remaining languages: merge onto EN for any missing key. */
const T = {
  en: EN,
  zh: merge(EN, ZH),
  ja: merge(EN, {
    meta_title: "Karma Protected｜信頼できるAIサービス取引",
    meta_desc:
      "買い手が資金をロック、売り手がパフォーマンスボンド。証拠に基づく納品、紛争時の凍結、確認後の自動決済。",
    nav_pain: "課題",
    nav_solution: "保護",
    nav_users: "対象",
    nav_security: "セキュリティ",
    nav_sign_in: "サインイン",
    nav_how_btn: "しくみを見る",
    nav_console_btn: "コンソールへ",
    hero_h2_line1: "AIサービスの取引は、運任せにしない。",
    hero_h2_line2: "資金ロック、証拠で紛争解決。",
    hero_lead:
      "買い手は資金をロックし、売り手は保証金を預けます。納品証拠、紛争時の凍結、確認後の決済。エージェント/API/自動化向け。",
    hero_cta_console: "コンソールへ",
    hero_cta_how: "保護のしくみ",
    pill_1: "買い手ロック",
    pill_2: "売り手ボンド",
    pill_3: "自動証拠",
    pill_4: "紛争凍結",
    pill_5: "自動決済",
    pain_h: "難しいのは支払いそのものではない。",
    pain_p: "先払いへの不安、未払いリスク、納品後の証拠不足。",
    sol_h: "Karmaの保護の仕組み",
    sol_p: "すべての注文が同じ状態機械に従います。",
    sec_h: "マーケサイトは入口。取引は分離コンソールで。",
    sec_p:
      "このサイトは説明と導線のみ。ウォレット接続・注文・署名・証拠・紛争は専用コンソールで処理し、シードフレーズはここでは求めません。",
    sec_cta_console: "コンソールへ",
    cta_go: "コンソールへ",
    cta_learn: "しくみを先に",
    studio_hint: "サインインは別ページです。シードフレーズを入力しないでください。",
  }),
  ko: merge(EN, {
    meta_title: "Karma Protected｜신뢰할 수 있는 AI 서비스 거래",
    nav_sign_in: "로그인",
    nav_how_btn: "작동 방식",
    nav_console_btn: "콘솔 열기",
    hero_h2_line1: "AI 서비스 거래는 운에 맡기지 마세요.",
    hero_h2_line2: "자금 선불 담보. 증거로 분쟁 해결.",
    hero_cta_console: "콘솔 열기",
    hero_cta_how: "보호 방식 보기",
    sec_h: "마케팅 사이트는 입구, 거래는 분리된 콘솔에서.",
    sec_p:
      "지갑 연결·주문·서명·증거·분쟁은 전용 콘솔에서 처리합니다. 이 페이지에서는 시드 구문을 요청하지 않습니다.",
    cta_go: "콘솔 열기",
    studio_hint: "로그인은 별도 페이지입니다. 시드 문구를 입력하지 마세요.",
  }),
  de: merge(EN, {
    meta_title: "Karma Protected｜Vertrauenswürdiger AI-Service-Handel",
    nav_how_btn: "Funktionsweise",
    nav_console_btn: "Konsole öffnen",
    hero_h2_line1: "KI-Service-Deals sollten nicht vom Glück abhängen.",
    hero_h2_line2: "Zuerst Sperre. Beweise klären Streit.",
    sec_h: "Marketing ist die Eingangstür; Handel in isolierter Konsole.",
    cta_go: "Konsole öffnen",
    studio_hint: "Wallet-Anmeldung auf separater Seite. Keine Seed-Phrase hier eingeben.",
  }),
  fr: merge(EN, {
    meta_title: "Karma Protected｜Commerce de services IA fiable",
    nav_how_btn: "Voir le mécanisme",
    nav_console_btn: "Ouvrir la console",
    hero_h2_line1: "Les deals IA ne doivent pas dépendre du hasard.",
    hero_h2_line2: "Fonds verrouillés. Preuves pour les litiges.",
    sec_h: "Le site marketing ouvre la porte ; le trading se fait dans la console isolée.",
    cta_go: "Ouvrir la console",
    studio_hint: "Connexion wallet sur une page séparée. Ne saisissez pas de phrase secrète ici.",
  }),
  es: merge(EN, {
    meta_title: "Karma Protected｜Comercio confiable de servicios de IA",
    nav_console_btn: "Abrir consola",
    hero_h2_line1: "Los acuerdos de IA no deberían depender de la suerte.",
    hero_h2_line2: "Fondos bloqueados. Evidencia para disputas.",
    sec_h: "La web es la puerta; el trading va en la consola aislada.",
    cta_go: "Abrir consola",
    studio_hint: "El inicio de sesión con wallet es en otra página. No ingrese frases semilla aquí.",
  }),
  pt: merge(EN, {
    meta_title: "Karma Protected｜Comércio confiável de serviços de IA",
    nav_console_btn: "Abrir console",
    hero_h2_line1: "Negócios de IA não devem depender da sorte.",
    sec_h: "O site é a entrada; as operações ficam na console isolada.",
    cta_go: "Abrir console",
    studio_hint: "Login da carteira em página separada. Não digite seed aqui.",
  }),
  it: merge(EN, {
    meta_title: "Karma Protected｜Commercio affidabile di servizi IA",
    nav_console_btn: "Apri console",
    sec_h: "Il sito è l’ingresso; il trading avviene nella console isolata.",
    cta_go: "Apri console",
  }),
  ru: merge(EN, {
    meta_title: "Karma Protected｜Надёжная торговля AI‑услугами",
    nav_console_btn: "Открыть консоль",
    hero_h2_line1: "Сделки с AI не должны строиться на удаче.",
    sec_h: "Сайт — вход; операции — в изолированной консоли.",
    cta_go: "Открыть консоль",
    studio_hint: "Вход с кошельком на отдельной странице. Не вводите сид-фразу здесь.",
  }),
  ar: merge(EN, {
    meta_title: "Karma Protected｜تجارة موثوقة لخدمات الذكاء الاصطناعي",
    nav_console_btn: "فتح لوحة التحكم",
    hero_h2_line1: "صفقات خدمات الذكاء الاصطناعي لا يجب أن تعتمد على الحظ.",
    sec_h: "الموقع للتعريف؛ التداول في لوحة معزولة.",
    cta_go: "فتح لوحة التحكم",
    studio_hint: "تسجيل الدخول عبر صفحة منفصلة. لا تُدخل عبارة الاسترداد هنا.",
  }),
  th: merge(EN, {
    meta_title: "Karma Protected｜เครือข่ายการค้าบริการ AI ที่เชื่อถือได้",
    nav_pain: "จุดเจ็บของการเทรด",
    nav_solution: "การปกป้อง",
    nav_users: "เหมาะกับใคร",
    nav_security: "การออกแบบความปลอดภัย",
    nav_sign_in: "เข้าสู่ระบบ",
    nav_how_btn: "ดูกลไก",
    nav_console_btn: "เปิดคอนโซล",
    hero_h2_line1: "การค้าบริการ AI ไม่ควรพึ่งโชค",
    hero_h2_line2: "ล็อกเงินก่อน หลักฐานระงับข้อพิพาท",
    hero_lead:
      "ผู้ซื้อล็อกเงิน ผู้ขายวางหลักประกัน มีหลักฐานการส่งมอบ ข้อพิพาทระงับได้ ยืนยันแล้วชำระอัตโนมัติ เหมาะกับตัวแทน API และทีมอัตโนมัติ",
    hero_cta_console: "เปิดคอนโซล",
    hero_cta_how: "ดูวิธีปกป้องการค้า",
    pill_1: "ผู้ซื้อล็อกเงิน",
    pill_2: "หลักประกันผู้ขาย",
    pill_3: "หลักฐานอัตโนมัติ",
    pill_4: "อายัดข้อพิพาท",
    pill_5: "ชำระอัตโนมัติ",
    pain_h: "ปัญหาไม่ได้อยู่ที่การจ่ายเงิน",
    pain_p: "กลัวจ่ายก่อน กลัวโดนใช้ฟรี หลังส่งมอบไม่มีหลักฐาน",
    sol_h: "Karma ปกป้องอย่างไร",
    sol_p: "ทุกคำสั่งซื้อใช้สภาวะและกฎเดียวกัน",
    sec_h: "เว็บไซต์คือทางเข้า การซื้อขายในคอนโซลแยก",
    sec_p:
      "เชื่อมกระเป๋า คำสั่งซื้อ ล็อก ลายเซ็น หลักฐานและข้อพิพาททำในคอนโซลเท่านั้น ไม่เก็บ seed บนหน้าโฆษณา",
    cta_go: "เปิดคอนโซล",
    studio_hint: "เข้าสู่ระบบอีกหน้า อย่าใส่กู้ดึงคำช่วยจำบนหน้านี้",
    foot1: "© 2026 Karma Network. โครงสร้างความเชื่อถือสำหรับการค้า AI",
  }),
  vi: merge(EN, {
    meta_title: "Karma Protected｜Mạng lưới giao dịch dịch vụ AI đáng tin cậy",
    nav_pain: "Điểm đau",
    nav_solution: "Cơ chế bảo vệ",
    nav_users: "Phù hợp với ai",
    nav_security: "Thiết kế an toàn",
    nav_sign_in: "Đăng nhập",
    nav_how_btn: "Xem cơ chế",
    nav_console_btn: "Vào bảng điều khiển",
    hero_h2_line1: "Giao dịch dịch vụ AI không nên trông chờ may rủi.",
    hero_h2_line2: "Khóa tiền trước. Bằng chứng giải quyết tranh chấp.",
    hero_lead:
      "Người mua khóa tiền; người bán ký quỹ. Giao hàng có bằng chứng; tranh chấp có thể đóng băng; xác nhận rồi tự động thanh toán.",
    hero_cta_console: "Vào bảng điều khiển",
    hero_cta_how: "Xem cách bảo vệ",
    pill_1: "Khóa tiền người mua",
    pill_2: "Ký quỹ người bán",
    pill_3: "Bằng chứng tự động",
    pill_4: "Đóng băng tranh chấp",
    pill_5: "Thanh toán tự động",
    pain_h: "Khó không phải ở việc trả tiền.",
    sec_h: "Trang chỉ là cửa vào; giao dịch trên console tách biệt.",
    sec_p:
      "Kết nối ví, đơn hàng, khóa, chữ ký, bằng chứng và tranh chấp thực hiện trên console riêng, không thu cụm từ khôi phục tại trang giới thiệu.",
    cta_go: "Vào bảng điều khiển",
    studio_hint: "Đăng nhập ví ở trang riêng. Không nhập cụm từ khôi phục tại đây.",
  }),
  id: merge(EN, {
    meta_title: "Karma Protected｜Jaringan perdagangan layanan AI terpercaya",
    nav_console_btn: "Buka konsol",
    hero_h2_line1: "Transaksi layanan AI tidak boleh mengandalkan keberuntungan.",
    hero_h2_line2: "Dana dikunci dulu. Bukti menyelesaikan sengketa.",
    sec_h: "Situs pemasaran adalah pintu masuk; perdagangan di konsol terpisah.",
    sec_p:
      "Koneksi dompet, pesanan, kunci, tanda tangan, bukti, dan sengketa dilakukan di konsol khusus — tidak meminta frase benih di sini.",
    cta_go: "Buka konsol",
    studio_hint: "Masuk dompet di halaman terpisah. Jangan masukkan frase benih di situs ini.",
  }),
  ms: merge(EN, {
    meta_title: "Karma Protected｜Rangkaian dagangan perkhidmatan AI dipercayai",
    nav_console_btn: "Buka konsol",
    hero_h2_line1: "Perdagangan perkhidmatan AI tidak harus bergantung kepada nasib.",
    sec_h: "Laman adalah pintu masuk; dagangan dalam konsol terasing.",
    cta_go: "Buka konsol",
    studio_hint: "Log masuk dompet di halaman berasingan. Jangan masukkan frasa benih di sini.",
  }),
  fil: merge(EN, {
    meta_title: "Karma Protected｜Mapagkakatiwalaang network ng AI services",
    nav_console_btn: "Buksan ang console",
    hero_h2_line1: "Ang mga deal sa AI service ay hindi dapat nakadepende sa swerte.",
    sec_h: "Ang website ay pasukan; ang trading ay sa hiwalay na console.",
    cta_go: "Buksan ang console",
    studio_hint: "Mag-sign in sa ibang pahina. Huwag maglagay ng seed phrase dito.",
  }),
  sw: merge(EN, {
    meta_title: "Karma Protected｜Mtandao wa biashara ya huduma za AI unaoweza kuaminika",
    nav_console_btn: "Fungua console",
    hero_h2_line1: "Makubaliano ya huduma za AI hayapaswi kutegemea bahati.",
    sec_h: "Tovuti ni mlango; biashara iko kwenye console iliyotenganishwa.",
    sec_p:
      "Muunganisho wa pochi, maagizo, kufunga, saini, ushahidi na migogoro hufanyika kwenye console maalum — hatutaki maneno ya kurejesha hapa.",
    cta_go: "Fungua console",
    studio_hint: "Kuingia kwa pochi ni ukurasa tofauti. Usiandike seed hapa.",
  }),
  ha: merge(EN, {
    meta_title: "Karma Protected｜Hanyar ciniki da za a iya dogara da shi na sabis na AI",
    nav_console_btn: "Buɗe console",
    hero_h2_line1: "Ma’amala ta sabis na AI bai kamata ya dogara da sa’a ba.",
    sec_h: "Gidan yanar gizo shine ƙofar shiga; ciniki a cikin console daban.",
    cta_go: "Buɗe console",
    studio_hint: "Shigar wallet a wani shafi. Kada ku shigar da kalmar mafi girma anan.",
  }),
  am: merge(EN, {
    meta_title: "Karma Protected｜ታመናለህ የሚባል የ AI አገልግሎት ንግድ አውታረለኝ",
    nav_console_btn: "ኮንሶል ክፈት",
    hero_h2_line1: "የ AI አገልግሎት ግብይቶች በዕድል ላይ መደረግ የለባቸውም።",
    sec_h: "ድረ‑ገጹ መግቢያ ነው፤ ንግድ በተለየ ኮንሶል ውስጥ።",
    cta_go: "ኮንሶል ክፈት",
    studio_hint: "የኪስ ግባት በተለየ ገጽ። እዚህ seed phrase አይጻፉ።",
  }),
  zu: merge(EN, {
    meta_title: "Karma Protected｜Inethiwekhi yokuhweba ye‑AI ethembekile",
    nav_console_btn: "Vula i-console",
    hero_h2_line1: "Izivumelwano ze‑AI azifanele zithembele enaseni.",
    sec_h: "Iwebhusayithi iyango; ukuhweba kwi-console ehlukile.",
    cta_go: "Vula i-console",
    studio_hint: "Ngena nge-wallet ekhasini elihlukile. Ungafaki iseed lapha.",
  }),
};

function htmlLangAttr(code) {
  const m = { zh: "zh-CN", fil: "fil" };
  return m[code] || code;
}

function deepFill(lang) {
  const base = T.en;
  const over = T[lang] || base;
  return new Proxy(over, {
    get(_, k) {
      return over[k] !== undefined ? over[k] : base[k];
    },
  });
}

let currentLang =
  typeof localStorage !== "undefined" ? localStorage.getItem(LANDING_LANG_KEY) || "en" : "en";
if (!ALL_LANG_CODES.includes(currentLang)) currentLang = "en";

function fillLangSelect() {
  const sel = document.getElementById("langSwitcher");
  if (!sel) return;
  sel.innerHTML = "";
  for (const g of LANG_GROUPS) {
    const og = document.createElement("optgroup");
    og.label = g.label;
    for (const code of g.codes) {
      const opt = document.createElement("option");
      opt.value = code;
      opt.textContent = LANG_LABELS[code] || code;
      og.appendChild(opt);
    }
    sel.appendChild(og);
  }
}

function applyLanguage(lang) {
  if (!ALL_LANG_CODES.includes(lang)) lang = "en";
  currentLang = lang;
  try {
    localStorage.setItem(LANDING_LANG_KEY, lang);
  } catch (_) {}
  document.documentElement.lang = htmlLangAttr(lang);
  document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";
  const d = deepFill(lang);
  document.title = d.meta_title;
  const metaDesc = document.querySelector('meta[name="description"]');
  if (metaDesc) metaDesc.setAttribute("content", d.meta_desc);
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    const key = el.getAttribute("data-i18n").replace(/-/g, "_");
    const text = d[key];
    if (text === undefined) return;
    el.textContent = text;
  });
  const sel = document.getElementById("langSwitcher");
  if (sel) sel.value = lang;
}

fillLangSelect();
applyLanguage(currentLang);
document.getElementById("langSwitcher")?.addEventListener("change", (e) => applyLanguage(e.target.value));
