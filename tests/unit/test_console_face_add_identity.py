# -*- coding: utf-8 -*-
"""操作台 · 刷脸即激活 + 追加身份同人比对 + 动额度前过 2FA（L3-3）。

契约（静态可查；真机由 tests/playwright/console_2fa_face_live.cjs 验）：

- 主身份激活只剩一步：**刷脸**。活体 + 多角度采集在本机完成，脸型模板加密后
  才上传，服务端拿密文 + 摘要 + 采集证据直接置「已激活」—— 不排复核队。
- 追加身份：填标准字段 → 再刷一次脸 → 与首次激活留下的模板比一个分数，
  分数过线 + 签名对得上 + 参考模板一致 + 不是重放 → 当场开通。
- 动钱的动作（加额 / 减额 / 取消授权、停用钥匙、取消绑定）都要过一次手机
  验证器生成的 6 位码（TOTP）。没绑 2FA 时退回「只有钱包签名一道锁」。
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONSOLE = ROOT / "apps" / "console"
CYBER = CONSOLE / "pages" / "cyber" / "index.html"
CSS = CONSOLE / "styles" / "cyber-console.css"
SCRIPTS = CONSOLE / "scripts"
PACK_DIR = SCRIPTS / "i18n-phrase"
SHIPPED_LANGS = ("en", "ja", "ko", "es-AR", "es-SV")

FACE_JS = SCRIPTS / "cyber-face-vault.js"
TWOFA_JS = SCRIPTS / "cyber-console-2fa.js"
MASTER_JS = SCRIPTS / "cyber-master-page.js"
API_JS = SCRIPTS / "karma-public-api.js"

# 签名原文两侧各拼一份（Python + JS），这里把「顺序 + 前缀」钉死：
# 谁改了其中一边，另一个文件里的同一行就找不到，测试立刻红。
ACTIVATION_LINES = (
    "Karma Face Activation v1",
    "identity_id:",
    "wallet_address:",
    "capture_digest:",
    "template_digest:",
)
CONSISTENCY_LINES = (
    "Karma Face Consistency v1",
    "owner_identity_id:",
    "profile_id:",
    "class:",
    "wallet_address:",
    "reference_digest:",
    "capture_digest:",
    "score:",
)


def _ordered(text: str, needles) -> bool:
    """needles 是否按这个顺序出现在 text 里（用来验签名原文的字段次序）。"""
    at = -1
    for needle in needles:
        i = text.find(needle, at + 1)
        if i < 0:
            return False
        at = i
    return True


# --------------------------------------------------------------------- 页面


def test_master_activation_is_one_face_check():
    """② 那一步从「去刷脸认证 →」跳页，改成原地刷脸激活。"""
    html = CYBER.read_text(encoding="utf-8")
    assert "② 刷脸激活" in html, "主身份那一步现在就叫刷脸激活"
    assert "开始刷脸激活 →" in html, "按钮要直接开始采集，不再跳去证件那一页"
    assert 'id="mst-activate-status"' in html, "刷脸结果要有落点（采集 / 提交 / 判定）"
    assert "证件核验 · 需要更高等级时再补" in html, "证件那一张改成「需要更高等级时再补」"
    assert "激活只看刷脸" in html, "页面要说清激活与证件是两条路"

    js = MASTER_JS.read_text(encoding="utf-8")
    assert "KarmaFaceVault" in js and "activateByFace" in js, "② 要接本机刷脸保险柜"
    assert 'cyberSwitchPage("identity", "personal")' not in js, "激活不再跳去别的卡片"


def test_new_console_modules_actually_bind_to_window():
    """IIFE 少了 window 参数 = 模块在浏览器里根本没挂上。

    `(function (global) { ... })();` 语法合法、``node --check`` 也过，但 global 是
    undefined，第一行 `global.KarmaX = ...` 就抛 TypeError —— 整页静默少一个模块
    （真机上就是这么踩到的）。所以这里钉死结尾形状。
    """
    for name in ("cyber-face-vault.js", "cyber-console-2fa.js"):
        js = (SCRIPTS / name).read_text(encoding="utf-8")
        assert "(function (global) {" in js, f"{name} 少了 IIFE 头"
        assert js.rstrip().endswith("})(window);"), f"{name} 的 IIFE 要显式传入 window"


def test_face_vault_stays_local_and_encrypted():
    """描述子是粗粒度数值、还要加密后才上传；密钥来自钱包签名（Karma 没有）。"""
    js = FACE_JS.read_text(encoding="utf-8")
    for needle in (
        "KFC-GRAY32-NCC-v1",
        "AES-GCM",
        "PBKDF2",
        "personal_sign",
        "crypto.subtle",
        "activateByFace",
        "confirmSamePerson",
        "getFaceTemplate",
        "confirmFaceConsistency",
        "MIN_STD",
    ):
        assert needle in js, f"刷脸保险柜缺 {needle}"
    # 明文不出设备：不上传照片，只交模板密文。
    assert "template_cipher" in js and "capture_digest" in js
    assert "toDataURL" not in js, "别把照片本体传上去"


def test_the_duplicate_add_identity_card_is_gone():
    """「追加身份 · 再刷一次脸就开通」那张卡已经并进「建立子身份」向导：
    同一件事不能在同一页说两遍。卡片、脚本、样式都不该再留。"""
    html = CYBER.read_text(encoding="utf-8")
    assert 'id="idv-add-identity"' not in html, "重复的「追加身份」卡还在页面上"
    assert "cyber-add-identity.js" not in html, "还在加载已删的脚本"
    assert not (SCRIPTS / "cyber-add-identity.js").exists(), "死代码不留：文件要一起删"
    css = CSS.read_text(encoding="utf-8")
    assert ".aid-grid" not in css and ".aid-hint" not in css, "旧卡片的样式也一起收掉"
    gate = (ROOT / "scripts" / "acceptance" / "console_last_mile_gate.sh").read_text(encoding="utf-8")
    assert "cyber-add-identity.js" not in gate, "闸门里还在查这个已删的脚本"

def test_activation_message_is_identical_on_both_sides():
    """签名原文只有一个出处：Python 侧与 JS 侧逐字一致，字段顺序也要一致。"""
    py = (ROOT / "services" / "face_activation.py").read_text(encoding="utf-8")
    js = FACE_JS.read_text(encoding="utf-8")
    assert _ordered(py, ACTIVATION_LINES), "Python 侧激活原文顺序变了"
    assert _ordered(js, ACTIVATION_LINES), "JS 侧激活原文与 Python 不一致"
    assert _ordered(py, CONSISTENCY_LINES), "Python 侧同人比对原文顺序变了"
    assert _ordered(js, CONSISTENCY_LINES), "JS 侧同人比对原文与 Python 不一致"
    # 分数在原文里的形状：固定四位小数，两边写法必须一致。
    assert 'f"{value:.{SCORE_DECIMALS}f}"' in py and "SCORE_DECIMALS = 4" in py
    assert "toFixed(4)" in js, "JS 侧分数也要固定四位小数"


# --------------------------------------------------------------------- 2FA


def test_two_factor_gate_is_on_every_fund_moving_path():
    """授权 / 停用 / 取消绑定都过一次 6 位码；码走请求头，撤销走 body。"""
    js = API_JS.read_text(encoding="utf-8")
    assert "Karma2FA" in js and "gate.guard" in js
    for what in ("授权额度", "停用钥匙", "取消绑定"):
        assert '"%s"' % what in js, f"闸门少了「{what}」这条路径的标签"
    assert "X-Karma-2FA-Code" in js, "额度这条把码放请求头"
    assert "twofa_code" in js, "撤销 / 解绑这条把码放 body"

    capacity = (ROOT / "api" / "routes" / "capacity.py").read_text(encoding="utf-8")
    assert "console_2fa" in capacity and "require_code" in capacity, "服务端额度入口要复核"
    gateway = (ROOT / "api" / "routes" / "runtime_gateway.py").read_text(encoding="utf-8")
    assert "require_code" in gateway and "twofa_code" in gateway, "服务端停用 / 解绑要复核"


def test_two_factor_module_exports_the_card_and_the_prompt():
    js = TWOFA_JS.read_text(encoding="utf-8")
    for needle in (
        "guard:",
        "ask:",
        "render:",
        "refresh:",
        "k2fa-modal",
        "k2fa-card",
        "enrollTwoFactor",
        "activateTwoFactor",
        "rotateTwoFactorRecovery",
        "disableTwoFactor",
    ):
        assert needle in js, f"2FA 模块缺 {needle}"
    # 恢复码只在换发那一次显示；密钥从不回吐给页面。
    assert "recovery_codes" in js
    assert "已抄好，收起来" in js


def test_two_factor_service_is_a_real_totp():
    svc = (ROOT / "services" / "console_2fa.py").read_text(encoding="utf-8")
    for needle in ("sha1", "hmac", "30", "provisioning_uri", "recovery", "TwoFactorError"):
        assert needle in svc, f"TOTP 服务缺 {needle}"
    route = (ROOT / "api" / "routes" / "console_2fa.py").read_text(encoding="utf-8")
    assert '@router.post("/enroll"' in route, "路由按相对路径挂（前缀在 app.py 里给）"
    app = (ROOT / "api" / "app.py").read_text(encoding="utf-8")
    assert "/v1/console/2fa" in app, "2FA 路由要挂进受保护依赖里"


def test_face_routes_and_migration_exist():
    ver = (ROOT / "api" / "routes" / "identity_verification.py").read_text(encoding="utf-8")
    assert "face-activate" in ver and "face-template" in ver
    role = (ROOT / "api" / "routes" / "identity_role_profiles.py").read_text(encoding="utf-8")
    assert "face-consistency" in role
    mig = ROOT / "db" / "migrations" / "versions" / "0057_console_2fa_and_face.py"
    assert mig.exists(), "两张新表要有迁移"
    text = mig.read_text(encoding="utf-8")
    assert "console_two_factors" in text and "identity_face_templates" in text
    revision = re.search(r'revision\s*=\s*"([^"]+)"', text)
    assert revision and len(revision.group(1)) <= 32, "revision id 要放得进 version 字段"


# --------------------------------------------------------------- 语言 / 样式


def test_every_language_pack_carries_the_face_and_2fa_copy():
    """六种语言都要有这一段，否则切语言立刻掉回中文。"""
    samples = (
        "② 刷脸激活",
        "开始刷脸激活 →",
        "刷一次脸就激活：活体 + 5 个角度在这台设备上采集，脸型模板加密后才上传（Karma 只拿密文与摘要），判定通过当场激活，不用排队等人工。",
        "激活只看刷脸",
        "证件核验 · 需要更高等级时再补",
        "建立子身份",
        "① 选择身份类型",
        "去完成认证",
        "安全验证",
        "安全验证 · {0}",
        "输入验证器里的 6 位验证码。手机丢了就输入一张恢复码（形如 A1B2-C3D4），用掉即焚。",
        "绑定验证器（2FA）",
        "已绑定 · 剩余恢复码 {0} 张",
        "已绑定 · 剩余恢复码 {0} 张 · 暂时锁定",
        "未绑定 · 这台节点要求先绑定，才能动额度",
        "未绑定 · 现在只有钱包签名一道锁",
        "恢复码只显示这一次，抄下来收好：",
        "已抄好，收起来",
        "这个操作要过 2FA：请先在设置页绑定验证器。",
        "授权额度与取消授权都要过一次 6 位验证码；验证码由你手机上的验证器 App 生成 —— 钥匙被偷了也花不动钱。",
        "停用钥匙",
        "取消绑定",
    )
    for lang in SHIPPED_LANGS:
        pack = (PACK_DIR / f"{lang}.js").read_text(encoding="utf-8")
        missing = [s for s in samples if f'"{s}":' not in pack]
        assert not missing, f"{lang} 缺译文：{missing}"


def test_css_carries_the_two_new_blocks():
    css = CSS.read_text(encoding="utf-8")
    for cls in (
        ".k2fa-modal",
        ".k2fa-box",
        ".k2fa-box input",
        ".k2fa-err.on",
        ".k2fa-actions",
        ".k2fa-secret",
        ".k2fa-inline",
        ".k2fa-codes",
    ):
        assert cls in css, f"样式缺 {cls}"


def test_gate_runs_the_face_and_2fa_checks():
    gate = (ROOT / "scripts" / "acceptance" / "console_last_mile_gate.sh").read_text(encoding="utf-8")
    assert "test_console_face_add_identity.py" in gate, "闸门要跑这支"
    for js in ("cyber-face-vault.js", "cyber-console-2fa.js"):
        assert js in gate, f"闸门要 node --check {js}"
    assert "console_2fa_face_live.cjs" in gate, "闸门要跑真机那一支"


# --------------------------------------------------------------------- 参考脸


def test_master_verification_package_route_is_owner_only():
    """主体认证留下的密文包只回本人：加子身份时在本机解开当参考脸。"""
    ver = (ROOT / "api" / "routes" / "identity_verification.py").read_text(encoding="utf-8")
    assert '"/{identity_id}/verification/package"' in ver, "缺「取回留底包」这条路由"
    block = ver[ver.index('"/{identity_id}/verification/package"') :]
    block = block[: block.index("@router.get", 10)]
    assert "_require_owner" in block, "留底包只回本人"
    assert "package_cipher" in block and "face_digest" in block


def test_same_person_falls_back_to_the_master_verification_face():
    """没有刷脸模板时，参考脸用主体认证留底的那份 —— 已经留过底的人不用再刷一次。"""
    svc = (ROOT / "services" / "face_activation.py").read_text(encoding="utf-8")
    assert "reference_source" in svc, "判定里要写清参考脸哪来的"
    assert '"identity_verification"' in svc and '"face_template"' in svc
    body = svc[svc.index("async def assert_same_person(") :]
    body = body[: body.index("\n__all__")]
    assert "IdentityVerificationModel" in body, "要真的去读主体认证那行记录"
    assert 'verification.status != "verified"' in body, "没核验完的留底不能当参考脸"
    route = (ROOT / "api" / "routes" / "identity_role_profiles.py").read_text(encoding="utf-8")
    assert '"reference_source": verdict.get("reference_source")' in route, (
        "结论里要把参考脸的出处一起记档"
    )


def test_console_opens_the_master_package_locally():
    """操作台：本机解开留底包 → 建模板 → 当参考脸；解不开就如实说。"""
    api_js = API_JS.read_text(encoding="utf-8")
    assert "getVerificationPackage" in api_js, "客户端要有取留底包的接口"
    assert "/verification/package" in api_js
    js = FACE_JS.read_text(encoding="utf-8")
    for needle in (
        "referenceFromVerificationPackage",
        "openVerificationPackage",
        "packageKeyMessage",
        "derivePackageKey",
        "key_wrap",
        "identity_verification",
    ):
        assert needle in js, f"刷脸保险柜缺 {needle}"
    # 密钥原文必须跟提交那一侧逐字一致，否则永远解不开。
    verify_js = (SCRIPTS / "cyber-identity-verify.js").read_text(encoding="utf-8")
    assert '"Karma Identity Doc Key v1"' in verify_js and '"Karma Identity Doc Key v1"' in js
    for line in ("karma_identity_id:", "salt:"):
        assert line in js, f"密钥原文缺 {line}"


def test_the_package_key_convention_matches_on_both_sides():
    """留底包的密钥约定：提交与解开必须逐字一致，差一个字就永远解不开。"""
    js = FACE_JS.read_text(encoding="utf-8")
    verify_js = (SCRIPTS / "cyber-identity-verify.js").read_text(encoding="utf-8")
    for line in ("Karma Identity Doc Key v1", "karma_identity_id:", "salt:"):
        assert f'"{line}"' in js, f"保险柜缺密钥原文 {line}"
        assert f'"{line}"' in verify_js, f"提交那一侧缺密钥原文 {line}"
    # 盐按「salt hex 那串文本」参与 PBKDF2（两边的写法必须一样），迭代次数按包上写的来。
    for src in (js, verify_js):
        assert "PBKDF2" in src and "SHA-256" in src and "AES-GCM" in src
    assert 'salt: te.encode(saltHex)' in js or "salt: te.encode(saltHex)" in js
    part = js[js.index("async function derivePackageKey(") :]
    part = part[: part.index("function resetKey()")]
    assert 'te.encode(String(signature || ""))' in part, "签名原样参与派生（不剥 0x）"
    assert "Number(enc.iterations)" in js, "迭代次数按包上写的来"
    gate = (ROOT / "scripts" / "acceptance" / "console_last_mile_gate.sh").read_text(encoding="utf-8")
    assert "test_console_face_package.cjs" in gate, "闸门要跑留底包那一支"


#: 解不开留底包时要说的话，按原因分两句；五个语言包都要有。
UNOPENABLE_COPY = (
    "这份留底是早期记录（那时还不用钱包密钥封包），本机解不开。",
    "留底包的钥匙对不上（例如换过钱包），本机解不开。",
    "这张卡不用重建：去主身份页刷一次脸激活（只需一次），回来再点「刷脸确认」，同一个人就当场开通。",
    "去主身份页刷脸激活 →",
)

#: 保险柜抛错时带的码 —— 操作台据此分流，不靠猜文案。
FACE_ROUTE_CODES = ("face_on_file_missing", "face_package_legacy", "face_package_unopenable")


def test_the_unopenable_package_copy_is_translated():
    """早期记录 / 钥匙对不上要分开说，五个语言包都得有；旧的一句式文案要退场。"""
    for lang in SHIPPED_LANGS:
        pack = (PACK_DIR / f"{lang}.js").read_text(encoding="utf-8")
        for src in UNOPENABLE_COPY:
            assert f'"{src}":' in pack, f"{lang} 缺译文：{src}"
        assert '"主体认证留底的脸解不开：请先在主身份页刷一次脸激活，再来加身份。":' not in pack, (
            f"{lang} 还留着旧的一句式文案"
        )


def test_the_vault_codes_why_the_package_cannot_be_opened():
    """解不开不能只丢一句报错：错误要带 code，操作台才能决定「下一步点哪」。"""
    js = FACE_JS.read_text(encoding="utf-8")
    assert "function faceRouteError(" in js and "err.code = code" in js, "错误要带上 code"
    for code in FACE_ROUTE_CODES:
        assert f'"{code}"' in js, f"保险柜缺分流码 {code}"


def test_the_console_offers_a_way_out_when_the_package_cannot_be_opened():
    """分流提示：原样说出原因 + 一个「去主身份页刷脸激活」的跳转，卡不用重建。"""
    js = (SCRIPTS / "cyber-identity-verify.js").read_text(encoding="utf-8")
    assert "function faceRouteHint(" in js, "缺分流提示"
    for code in FACE_ROUTE_CODES:
        assert f'"{code}"' in js, f"分流没覆盖 {code}"
    assert 'window.cyberSwitchPage("identity", "master")' in js, "要能跳到主身份页"
    assert "mst-step-activate" in js, "跳过去要落在「② 刷脸激活」那一步"
    assert 'className = "idv-face-route"' in js, "分流块要有自己的样式钩子"
    css = CSS.read_text(encoding="utf-8")
    assert ".idv-face-route" in css, "分流块要有样式"
