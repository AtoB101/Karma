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
ADD_JS = SCRIPTS / "cyber-add-identity.js"
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
    for name in ("cyber-face-vault.js", "cyber-console-2fa.js", "cyber-add-identity.js"):
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


def test_add_identity_card_is_wired():
    """第二张卡：① 建卡 ② 再刷一次脸，比对通过就开通。"""
    html = CYBER.read_text(encoding="utf-8")
    assert 'id="idv-add-identity"' in html, "身份页要有「追加身份」这张卡"
    assert "cyber-add-identity.js" in html
    assert html.index('src="../../scripts/cyber-face-vault.js"') < html.index(
        'src="../../scripts/cyber-add-identity.js"'
    ), "追加身份要用 KarmaFaceVault，得排在它后面"

    js = ADD_JS.read_text(encoding="utf-8")
    for needle in ("createRoleProfile", "confirmSamePerson", "aid-create", "aid-face", "CLASSES"):
        assert needle in js, f"追加身份模块缺 {needle}"


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
        "追加身份 · 再刷一次脸就开通",
        "① 先建这张卡",
        "② 再刷脸一次 · 自动核对同一个人",
        "待核对的卡：{0} · {1} · kyc_status={2}",
        "同一个人：相似度 {0}（阈值 {1}）。这张卡已经开通。",
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
        ".aid-grid",
        ".aid-actions",
        ".aid-note.aid-bad",
        ".aid-hint",
    ):
        assert cls in css, f"样式缺 {cls}"


def test_gate_runs_the_face_and_2fa_checks():
    gate = (ROOT / "scripts" / "acceptance" / "console_last_mile_gate.sh").read_text(encoding="utf-8")
    assert "test_console_face_add_identity.py" in gate, "闸门要跑这支"
    for js in ("cyber-face-vault.js", "cyber-console-2fa.js", "cyber-add-identity.js"):
        assert js in gate, f"闸门要 node --check {js}"
    assert "console_2fa_face_live.cjs" in gate, "闸门要跑真机那一支"
