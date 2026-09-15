"""身份 · 认证 页面的静态接线门禁。

为什么要有这个文件：线上实测抓到过一个「点『建立子身份』毫无反应」的 bug ——
按钮绑上了监听器，但函数体是空的，页面不报错、控制台干净，用户只会以为坏了。
下面这几条就是冲着这类静默失效去的：
  1. 页面上被绑定的每个 id 都必须真实存在；
  2. 每个监听器都要真的绑上；
  3. 监听器不能是空函数体；
  4. 「建立子身份」必须真的调到 createSub()。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONSOLE = ROOT / "apps" / "console"
PAGE = CONSOLE / "pages" / "cyber" / "index.html"
IDENTITY_JS = CONSOLE / "scripts" / "cyber-identity-verify.js"
FACE_JS = CONSOLE / "scripts" / "cyber-face-capture.js"

# 身份页上「人点了 / 选了就必须有反应」的控件。
CLICK_IDS = [
    "idv-face-open",
    "idv-submit",
    "idv-reset",
    "idsub-new",
    "idsub-cancel",
    "idsub-wallet",
    "idsub-face",
    "idsub-create",
]
CHANGE_IDS = ["idv-doc-front", "idv-doc-back", "idv-face-file"]
WIRED_IDS = CLICK_IDS + CHANGE_IDS

# 只匹配「内联函数」形式的绑定；裸函数名（如 , createSub)）由第 4 条测试兜底。
BINDING = re.compile(
    r'byId\("([a-z0-9-]+)"\)\.addEventListener\("(click|change)",\s*(?:async\s+)?function\s*\([^)]*\)\s*\{'
)
EMPTY_BODY = re.compile(r"\s*\}")


def _page_html() -> str:
    return PAGE.read_text(encoding="utf-8")


def _identity_js() -> str:
    return IDENTITY_JS.read_text(encoding="utf-8")


def test_identity_page_script_is_loaded():
    assert "cyber-identity-verify.js" in _page_html(), "身份页必须加载 cyber-identity-verify.js"


def test_every_wired_id_exists_on_the_page():
    html = _page_html()
    missing = [i for i in WIRED_IDS if f'id="{i}"' not in html]
    assert not missing, f"脚本绑了这些 id，但页面上没有：{missing}"


def test_every_wired_id_has_a_listener():
    js = _identity_js()
    bound = {m.group(1) for m in BINDING.finditer(js)}
    bound |= set(re.findall(r'byId\("([a-z0-9-]+)"\)\.addEventListener\("(?:click|change)",\s*[A-Za-z_$]', js))
    missing = [i for i in WIRED_IDS if i not in bound]
    assert not missing, f"这些控件没有绑定事件：{missing}"


def test_no_listener_is_an_empty_function():
    """空函数体 = 点了没反应，而且不报错 —— 必须当门禁一样挡住。"""
    js = _identity_js()
    for match in BINDING.finditer(js):
        ident = match.group(1)
        after = js[match.end(): match.end() + 400]
        assert not EMPTY_BODY.match(after), (
            f"{ident} 的事件处理是空函数体（点了没反应且不报错）"
        )


def test_the_create_button_actually_calls_create_sub():
    js = _identity_js()
    idx = js.index('byId("idsub-create").addEventListener("click"')
    assert "createSub()" in js[idx: idx + 200], "『建立子身份』必须真的调用 createSub()"

# ---------------------------------------------------------------------------
# 刷脸取景框（cyber-face-capture.js）
#
# 两个刷脸入口都靠它弹窗取景。这个模块一旦没被加载、或者换了名字，表现就是
# 「点了开始刷脸没反应」—— 和之前那个空函数体的 bug 一模一样，所以也当门禁挡住。
# ---------------------------------------------------------------------------


def test_face_capture_module_is_loaded_before_its_users():
    html = _page_html()
    assert "cyber-face-capture.js" in html, "刷脸取景模块必须被加载"
    assert html.index("cyber-face-capture.js") < html.index("cyber-identity-verify.js"), (
        "取景模块必须在 cyber-identity-verify.js 之前加载，否则按钮绑定时它还不在"
    )


def test_face_capture_module_exposes_the_global():
    js = FACE_JS.read_text(encoding="utf-8")
    assert "window.KarmaFaceCapture" in js, "取景模块必须挂到 window.KarmaFaceCapture"
    assert re.search(r"window\.KarmaFaceCapture\s*=\s*\{", js), "导出必须是对象字面量"
    assert "open:" in js, "必须导出 open()"


def test_both_face_buttons_open_the_capture_dialog():
    js = _identity_js()
    for ident in ("idv-face-open", "idsub-face"):
        idx = js.index('byId("%s").addEventListener("click"' % ident)
        body = js[idx : idx + 700]
        assert "KarmaFaceCapture" in body and ".open(" in body, (
            "%s 必须真的弹取景框（调 KarmaFaceCapture.open）" % ident
        )


def test_capture_dialog_asks_for_the_whole_face():
    """取景要求必须写在界面上：只截半张脸是复核打回的头号原因。"""
    js = FACE_JS.read_text(encoding="utf-8")
    assert "头顶" in js and "下巴" in js, "取景框必须明确要求头顶和下巴都进圈"
    assert "确认使用" in js, "拍完必须由本人点「确认使用」才采用"
    assert "重拍" in js, "必须给得出重拍"


def test_capture_dialog_stops_the_camera_when_it_closes():
    """关掉弹窗还占着摄像头（灯一直亮）是不可接受的。"""
    js = FACE_JS.read_text(encoding="utf-8")
    assert re.search(r"function stopStream\(\)", js), "必须有统一的停流函数"
    close_fn = js[js.index("function closeOverlay()") :]
    close_fn = close_fn[: close_fn.index("function settle(")]
    assert "stopStream()" in close_fn, "closeOverlay 必须停流"
    assert re.search(r"if \(!state \|\| state\.stopped\)", js), (
        "授权弹窗期间用户按了取消的话，拿到流之后必须立刻关掉"
    )


def test_capture_dialog_never_pretends_to_detect_a_face():
    """没有 FaceDetector 时必须照实说「画面稳住了」，不能假装检测到人脸。"""
    js = FACE_JS.read_text(encoding="utf-8")
    assert "window.FaceDetector" in js, "有 FaceDetector 就该用真的"
    steady = js[js.index("function onSteady(") :]
    steady = steady[: steady.index("function shoot(")]
    assert "检测到" not in steady, "兜底路径不许写「检测到人脸」"
    assert "稳住" in steady, "兜底路径只能说自己真的量到的东西：画面稳住了"


# ---------------------------------------------------------------------------
# 多角度刷脸 + 灰按钮必须说得出原因
#
# 两条线上真实踩过的坑：
#   1. 刷脸原本只拍一张 —— 拿别人的照片就能顶替，那叫「上传照片」，不叫认证；
#   2. 「提交认证」按钮在资料填满时依然是灰的，而且不告诉用户差哪一项，
#      表现和坏了没区别。两条都当门禁挡住。
# ---------------------------------------------------------------------------


def test_capture_dialog_collects_every_angle_of_the_face():
    """一次认证要覆盖整张脸：正 / 左 / 右 / 抬 / 低，不是拍一张就完事。"""
    js = FACE_JS.read_text(encoding="utf-8")
    assert "ANGLE_STEPS" in js, "必须有角度表"
    for key in ("front", "left", "right", "up", "down"):
        assert 'key: "%s"' % key in js, "缺少角度：%s" % key
    assert re.search(r"function captureResult\(\)", js), "必须把整组帧交给上层"
    assert "frames:" in js, "采集结果里必须带 frames 数组"


def test_capture_dialog_rejects_a_frame_that_repeats_the_previous_one():
    """同一张照片连拍 / 对着屏幕翻拍必须当场拒掉，否则五张角度图等于一张。"""
    js = FACE_JS.read_text(encoding="utf-8")
    assert "IDENTICAL_DIFF" in js, "必须有「这张和上一张几乎一样」的判定阈值"
    assert re.search(r"diff < IDENTICAL_DIFF", js), "阈值必须真的参与判定"
    assert "别拿同一张照片顶替" in js, "拒掉时必须说清原因，不能默默不过"
    shoot = js[js.index("function shoot(") :]
    shoot = shoot[: shoot.index("function acceptFrame(")]
    assert "judgeAngle(" in shoot, "shoot() 必须先过角度判定才收帧"


def test_capture_dialog_keeps_the_camera_open_between_angles():
    """两个角度之间只留转身时间，不该反复开关摄像头（灯闪四次很吓人）。"""
    js = FACE_JS.read_text(encoding="utf-8")
    assert "BETWEEN_MS" in js, "必须有转身间隔"
    between = js[js.index("function betweenAngles(") :]
    between = between[: between.index("function resumeLive(")]
    assert "stopStream()" not in between, "转身期间不许关流"


def test_face_digest_covers_all_angles():
    """摘要只算第一张的话，后面几张被换掉也查不出来 —— 摘要就白做了。"""
    js = IDENTITY_JS.read_text(encoding="utf-8")
    assert "face_frames" in js, "提交包里必须带上全部角度"
    assert re.search(r"function faceDigestInput\(", js), "必须有覆盖全量的摘要输入"
    idx = js.index("function faceDigestInput(")
    body = js[idx : idx + 700]
    assert "join" in body, "摘要输入必须把每一帧都并进去"


def test_submit_button_says_what_is_missing_instead_of_silently_greying_out():
    """按钮静默变灰是线上真实踩过的坑：资料填完了却不知道为什么点不动。"""
    js = IDENTITY_JS.read_text(encoding="utf-8")
    assert re.search(r"function submitMissing\(\)", js), "必须能算出「还差什么」"
    idx = js.index("function refreshSubmitState()")
    body = js[idx : idx + 1600]
    assert "idv-need" in body, "原因必须写到页面上（#idv-need）"
    assert "还差" in body, "文案必须直说还差哪几项"
    assert 'id="idv-need"' in _page_html(), "页面上必须有 #idv-need 这个位置"
