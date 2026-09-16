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


def test_capture_is_automatic_instead_of_button_driven():
    """用户明确要求「像 Face ID 那样自动采集」：照提示转头，系统自己拍。

    这条门禁挡住「又退回成按快门」—— 主循环必须自己调用 shoot()，
    而且正常流程里不许出现「拍下这一张」这种要用户按的按钮。
    """
    js = FACE_JS.read_text(encoding="utf-8")
    assert re.search(r"function onSteady\(", js), "必须有自动判定"
    steady = js[js.index("function onSteady(") :]
    steady = steady[: steady.index("function hintFace(")]
    assert "shoot()" in steady, "自动判定通过后必须自己拍，不能等用户按键"

    live = js[js.index("function renderLiveActions()") :]
    live = live[: live.index("function switchCamera(")]
    assert "stuckShown" in live, "只有「一直没进展」的兜底情况才给按钮"
    assert "拍下这一张" not in js, "自动流程里不许再有「拍下这一张」这种手动快门"


def test_capture_waits_until_the_user_really_holds_still():
    """慢慢转头不能被当成「停住了」，否则拍出来是一张糊的。"""
    js = FACE_JS.read_text(encoding="utf-8")
    assert "function frameAgo(" in js, "必须拿「STILL_MS 之前那一帧」比，而不是相邻两帧"
    assert "frameAgo(STILL_MS)" in js, "判定停稳要用那个时间窗"
    assert re.search(r"var STILL_MS = \d+", js), "停稳窗口必须是个明确的常量"
    assert re.search(r"var ANGLE_MIN_DIFF = ", js), "「算不算一个新角度」必须有阈值"


def test_capture_tells_the_user_what_to_do_at_every_step():
    """大字引导是这套自动流程唯一的输入方式：每一步都得说清做什么动作。"""
    js = FACE_JS.read_text(encoding="utf-8")
    assert "function renderGuide(" in js, "必须有引导渲染"
    for text in ("请正对镜头", "请向左转头", "请向右转头", "请把头抬高一点", "请把头低一点"):
        assert text in js, "缺引导文案：%s" % text
    assert "kfc-guide" in js, "引导得真的画到页面上"


def test_capture_gives_the_user_time_to_get_ready_before_shooting():
    """别让人还没站好就被拍下第一张。"""
    js = FACE_JS.read_text(encoding="utf-8")
    assert re.search(r"var GRACE_FIRST_MS = \d+", js), "第一步要有宽限时间"
    assert re.search(r"var GRACE_STEP_MS = \d+", js), "后续角度也要有一点准备时间"
    assert "state.readyAt" in js, "宽限时间必须真的参与判定"


def test_capture_has_a_way_out_when_nothing_happens():
    """自动判定万一卡住，用户不能被困死在里面。"""
    js = FACE_JS.read_text(encoding="utf-8")
    assert re.search(r"var AUTO_STUCK_MS = \d+", js), "必须有「多久没进展」的阈值"
    live = js[js.index("function renderLiveActions()") :]
    live = live[: live.index("function switchCamera(")]
    assert "手动拍这一张" in live, "卡住时要给得出手动兜底"
    assert "本角度改用照片" in live, "卡住时也要给得出照片兜底"

    # 看门狗必须挂在主循环上：画面一直在动、或者摄像头压根没出帧，
    # 这两种情况下 onSteady 根本判不到「停稳」，只放在那儿等于没有兜底。
    tick = js[js.index("function tick()") :]
    tick = tick[: tick.index("function pushHistory(")]
    assert "AUTO_STUCK_MS" in tick, "「多久没进展」的看门狗必须挂主循环，不能只挂在判定分支里"

def test_stillness_check_ignores_brightness_drift():
    """自动曝光 / 自动白平衡会让整帧明暗一直漂移。

    2026-09-16 线上实测：拿**原始灰度**直接相减，整帧变亮 6% 就会被当成「画面在动」，
    用户转完头屏住呼吸，屏幕一直不出结果 —— 就是那句「太卡了、没反应」。
    这条门禁挡住「退回成原始灰度直接比」：比较之前必须先做亮度归一化。
    """
    js = FACE_JS.read_text(encoding="utf-8")
    assert re.search(r"function grayNorm\(", js), "必须有亮度归一化"
    diff = js[js.index("function grayDiff(") :]
    diff = diff[: diff.index("function grayMean(")]
    assert "grayNorm(" in diff, "比形状之前必须先归一化掉整帧的明暗漂移"
    assert "Math.abs" in diff, "归一化之后仍然要比两个向量差多少"


def test_stillness_covers_every_frame_in_the_window_not_just_the_ends():
    """只比「窗口头尾两帧」会被随机抖动骗过去：头尾偶尔刚好撞上，就被当成停稳。

    当前帧必须和窗口里**每一帧**都比一遍，取最大的那个差。
    """
    js = FACE_JS.read_text(encoding="utf-8")
    assert re.search(r"function stillWorstDiff\(", js), "必须有「窗口内每一帧」的最大差判定"
    steady = js[js.index("function onSteady(") :]
    steady = steady[: steady.index("function hintFace(")]
    assert "stillWorstDiff(" in steady, "停稳判定必须真的用上它"
    assert "worst < STILL_DIFF" in steady, "判定必须落在阈值上"

def test_stillness_only_counts_the_face_not_the_background():
    """人站住了，但背景里有人走动 / 树影在晃 —— 判定不能因此说「画面还在动」。

    2026-09-16 线上实测（1280x720 真机模型）：16x16 全帧平均差在背景有动静时是
    0.076，而停稳阈值是 0.05 —— 永远判不出停稳，用户看到的就是「卡住、没反应」。
    中心加权之后背景只算 0.02~0.10，人真转头是 0.4~1.2，才分得开。
    这条门禁挡住「退回成全帧一视同仁地比」。
    """
    js = FACE_JS.read_text(encoding="utf-8")
    assert re.search(r"var WEIGHT_FLOOR = 0\.\d+", js), "必须有「四角权重只剩多少」的常量"
    assert re.search(r"function diffKernel\(", js), "必须有中心加权的权重窗"
    diff = js[js.index("function grayDiff(") :]
    diff = diff[: diff.index("function grayMean(")]
    assert "diffKernel(" in diff, "比对必须真的用上权重窗"
    assert "wsum" in diff, "加权平均要按权重和归一，不能拿 256 当分母"
    still = re.search(r"var STILL_DIFF = ([0-9.]+)", js)
    assert still, "停稳阈值必须是明确常量"
    assert float(still.group(1)) >= 0.1, (
        "停稳阈值必须高于「背景在动」那一档（实测 0.076），否则背景一动就永远判不出停稳"
    )


def test_capture_loop_runs_every_frame_and_analysis_is_throttled():
    """进度圈是用户全部的手感来源：它必须逐帧画；取样判定很贵，必须按需跑。

    2026-09-16 实测：主循环原来是 130ms 一跳（约 7.7 次/秒），进度圈一跳一跳；
    而「取样 + 判定」在真机上可能吃掉几十毫秒。两件事必须分开跑。
    """
    js = FACE_JS.read_text(encoding="utf-8")
    assert "window.requestAnimationFrame(" in js, "主循环必须逐帧驱动"
    assert re.search(r"function scheduleTick\(", js), "必须有逐帧调度"
    assert re.search(r"function paintProgress\(", js), "进度圈必须有独立的逐帧绘制"
    assert re.search(r"function analyzeFrame\(", js), "取样判定必须单独成函数"
    assert re.search(r"var SAMPLE_DUTY = \d+", js), "分析频率必须按「占多少帧预算」自适应"
    assert "state.sampleCost" in js, "自适应必须真的量出分析耗时"
    tick = js[js.index("function tick()") :]
    tick = tick[: tick.index("function pushHistory(")]
    assert "paintProgress()" in tick, "主循环每一帧都要画圈"
    assert "gap" in tick and "analyzeFrame(" in tick, "分析要按自适应的间隔跑，不能每帧都跑"
    assert "video.currentTime" in tick, "同一个视频帧不重复分析：摄像头 30fps、屏幕可能 60fps"


def test_overlay_does_not_blur_the_whole_screen():
    """整屏 backdrop-filter 会把页面压到二十几帧 —— 这是「不丝滑」的第二个元凶。

    2026-09-16 实测：`.kfc-overlay{backdrop-filter:blur(6px)}` 让同一次打开的页面从
    69 帧/秒掉到 28 帧/秒（视频预览在下面每帧都在变，模糊就得每帧重算一遍）。
    """
    js = FACE_JS.read_text(encoding="utf-8")
    overlay = js[js.index(".kfc-overlay{") :]
    overlay = overlay[: overlay.index('"')]
    assert "backdrop-filter" not in overlay, "遮罩层不许整屏模糊：它会把每一帧都拖慢"
    stage = js[js.index(".kfc-stage{") :]
    stage = stage[: stage.index(".kfc-ring")]
    assert "will-change" in stage or "translateZ" in stage, "预览画面要单独成层，别每帧重画整个弹窗"


def test_capture_says_why_it_is_not_shooting_when_something_keeps_moving():
    """判不到「停稳」时不能闷着 —— 得把量到的原因说出来，用户才知道该做什么。"""
    js = FACE_JS.read_text(encoding="utf-8")
    assert re.search(r"var BUSY_HINT_MS = \d+", js), "必须有「多久没进展就说原因」的阈值"
    assert "busyHinted" in js, "同一步里只提示一次，不能反复刷屏"
    assert "画面里一直有动静" in js, "必须有一句人话解释「为什么还没拍」"


def test_capture_gives_a_haptic_tick_on_every_shot():
    """拍下那一刻要有反馈：手机上是震一下（不支持就静默跳过，不能报错）。"""
    js = FACE_JS.read_text(encoding="utf-8")
    flash = js[js.index("function flash()") :]
    flash = flash[: flash.index("function renderGuide(")]
    assert "navigator.vibrate" in flash, "拍下这一张时要给一次触感反馈"
    assert "try {" in flash, "震动可能不被支持，必须包起来，绝不能因此报错"


def test_first_angle_grace_starts_when_the_camera_actually_delivers_frames():
    """摄像头从点开到出画要几百毫秒到一秒多，这段时间不能算进「给你时间站好」。"""
    js = FACE_JS.read_text(encoding="utf-8")
    analyze = js[js.index("function analyzeFrame(") :]
    analyze = analyze[: analyze.index("function paintProgress(")]
    assert "state.startedAt" in analyze, "必须记住「摄像头真的出画了」的那一刻"
    assert "GRACE_FIRST_MS" in analyze, "第一张的准备时间要从那一刻重新起算"


# ---------------------------------------------------------------------------
# 官方实名核验（第三方服务商）：apps/console/scripts/cyber-identity-provider.js
# ---------------------------------------------------------------------------

PROVIDER_JS = CONSOLE / "scripts" / "cyber-identity-provider.js"
API_JS = CONSOLE / "scripts" / "karma-public-api.js"


def test_provider_module_is_loaded_after_the_page_it_decorates():
    html = _page_html()
    assert "cyber-identity-provider.js" in html, "服务商核验模块必须被加载"
    assert html.index("cyber-identity-verify.js") < html.index("cyber-identity-provider.js"), (
        "它要在身份页模块之后加载（那个模块负责刷新页面状态）"
    )
    js = PROVIDER_JS.read_text(encoding="utf-8")
    assert re.search(r"window\.KarmaIdentityProvider\s*=\s*\{", js), "必须挂到 window"


def test_provider_card_exists_and_the_button_really_calls_the_api():
    html = _page_html()
    for ident in ("idv-provider-open", "idv-provider-sync", "idv-provider-status", "idv-provider-badge"):
        assert 'id="%s"' % ident in html, "页面上缺少 #%s" % ident
    js = PROVIDER_JS.read_text(encoding="utf-8")
    assert "openIdentityProviderSession" in js, "按钮必须真的去开一次服务商会话"
    assert "syncIdentityProviderSession" in js, "必须能回查结论"
    api_js = API_JS.read_text(encoding="utf-8")
    for fn in ("getIdentityProvider", "openIdentityProviderSession", "syncIdentityProviderSession"):
        assert re.search(r"function %s\(" % fn, api_js), "API 层缺少 %s" % fn
        assert fn in api_js[api_js.index("global.cyberKarmaApi = {") :], (
            "%s 必须导出到 window.cyberKarmaApi" % fn
        )


def test_provider_page_never_claims_a_pass_without_the_server():
    """「已通过」只能由服务端返回的 applied 决定 —— 页面自己不许下结论。"""
    js = PROVIDER_JS.read_text(encoding="utf-8")
    body = js[js.index("function renderResult(") :]
    body = body[: body.index("\n  /* ")]
    assert "result.applied" in body, "通过与否必须看服务端返回的 applied"
    assert '"verified"' in body, "还要看服务端的状态位"
    # 打「已通过」这个角标的地方只能有一处，而且就在 renderResult 里
    assert js.count('badge("已通过"') == body.count('badge("已通过"') >= 1, (
        "「已通过」只允许在 renderResult 里、跟着服务端结论一起出现"
    )
    assert js.index('badge("已通过"') > js.index("result.applied")


def test_provider_page_is_honest_when_nothing_is_connected():
    js = PROVIDER_JS.read_text(encoding="utf-8")
    assert "未接入" in js, "没接服务商时必须直说"
    assert "人工核验" in js, "并且要告诉用户还能走复核台那条路"
    assert "missing" in js, "密钥没配齐时要说清缺什么，不能装作可用"
    assert re.search(r"function usable\(", js), "可不可用要有明确的判定"
    html = _page_html()
    assert "idv-provider-open" in html and "disabled" in html[
        html.index('id="idv-provider-open"') - 200 : html.index('id="idv-provider-open"') + 100
    ], "默认态必须是禁用，等服务端说可用才放开"

