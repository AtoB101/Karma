"""单笔订单状态图（操作台）。

用户原话：「订单号下方就是一个状态图……到哪一步了那一步就亮起蓝灯……
不同的服务的状态图不一样，所以每个生意都应该有一个状态图」。

这一组钉住三件事：
1. 一个生意一张图 —— 阶段表按服务类型（scene）选，且和后端交付验证标准一一对应，
   标准里加了新场景而前端忘了配，这里必须红。
2. 亮灯只看真实数据 —— 后端状态机 / 流转历史 / 交付验证事件；没上报的里程碑要如实
   标成「未上报」，不许为了好看而点亮。
3. 后端把图上要用的两样东西交出来：这一单的服务类型 + 交付验证会话。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from httptest import post_minimal_contract

from db.models.orm import SettlementModel, SettlementTransitionAuditModel
from services import delivery_verification as dv
from services.delivery_verification import create_verification_session, seller_ship

ROOT = Path(__file__).resolve().parents[2]
CONSOLE = ROOT / "apps/console"
HTML = CONSOLE / "pages/cyber/index.html"
FLOW_JS = CONSOLE / "scripts/cyber-order-flow.js"
ORDERS_JS = CONSOLE / "scripts/cyber-orders.js"
CSS = CONSOLE / "styles/cyber-console.css"
GATE_SH = ROOT / "scripts/acceptance/console_last_mile_gate.sh"
LEDGER_SERVICE = ROOT / "services/payment_ledger.py"
LEDGER_ROUTE = ROOT / "api/routes/payment_ledger.py"
STANDARD = ROOT / "packages/evidence-schema/delivery-verification.v1.json"

BUYER = "kid_flow_buyer"
SELLER = "kid_flow_seller"

SCENE_LINE = re.compile(
    r'^\s{4}(\w+): \{ label: "([^"]*)", mode: "([^"]*)", events: \[(.*)\] \},$'
)


def _js() -> str:
    return FLOW_JS.read_text(encoding="utf-8")


def _scenes_in_js() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for line in _js().splitlines():
        m = SCENE_LINE.match(line)
        if m:
            out[m.group(1)] = re.findall(r'"([^"]+)"', m.group(4))
    return out


# --------------------------------------------------------------- 一个生意一张图


def test_every_service_type_in_the_standard_has_its_own_stage_diagram():
    """交付验证标准里的每个 scene 都要有中文名和阶段表 —— 少一个就是漏了一种生意。"""
    catalog = json.loads(STANDARD.read_text(encoding="utf-8"))
    standard_scenes = catalog["scenes"]
    in_js = _scenes_in_js()
    assert set(in_js) == set(standard_scenes), (
        "前端服务类型表和后端标准对不上：" + str(set(standard_scenes) ^ set(in_js))
    )
    for scene_id, body in standard_scenes.items():
        assert in_js[scene_id] == list(body["required_events"]), (
            f"{scene_id} 的里程碑和后端标准不一致"
        )


def test_every_milestone_event_has_a_chinese_stage_label():
    """标准里的 required_events 每个都要有中文阶段名，别把英文事件名暴露给用户。"""
    js = _js()
    catalog = json.loads(STANDARD.read_text(encoding="utf-8"))
    events = {e for body in catalog["scenes"].values() for e in body["required_events"]}
    block = js[js.index("var EVENT_STAGE = {") : js.index("/* 服务类型（scene）")]
    for ev in sorted(events):
        assert re.search(rf'"?{re.escape(ev)}"?\s*:', block), f"{ev} 没有中文阶段名"
    assert "_default:" in block, "认不出的新事件要有兜底文案"


def test_the_diagram_is_chosen_by_service_type_not_by_kind():
    """选模板靠 scene，不靠 kind —— 否则外卖和软件开发会长得一模一样。"""
    js = _js()
    assert "function sceneOf(entry)" in js
    assert "d.scene_id || d.task_type" in js, "服务类型优先取后端给的 scene_id"
    assert 'var GENERIC = { key: "generic"' in js, "认不出要退回通用图，别硬套"


# --------------------------------------------------------------- 亮灯只认真实数据


def test_steps_light_up_only_from_real_backend_evidence():
    js = _js()
    assert "function makeTracker(entry, history)" in js, "阶段完成度要挂在流转历史上"
    assert "h.to_status" in js, "用的是 settlement_transition_audits 的真实状态流转"
    assert "ver.events" in js, "交付里程碑用的是交付验证会话里真实记录的事件"
    assert "done: true" not in js, "不许硬编码一个阶段为已完成"
    # 主线阶段可以从「后面走过了」反推；里程碑不行 —— 没上报就是没上报。
    assert "if (!s.done && s.spine && !s.terminal && !s.strict && i < lastDone) s.done = true;" in js
    assert "milestone: true" in js
    assert "missing: at === undefined" in js
    assert "未上报" in js, "没上报的里程碑要如实写出来"


def test_the_current_step_is_the_one_that_lights_up_and_it_animates():
    js = _js()
    css = CSS.read_text(encoding="utf-8")
    assert 's.state = s.done ? (i === lastDone ? "live" : "done")' in js, "最远的已完成步才是当前步"
    assert '"of-step is-" + s.state' in js, "亮灯状态是算出来的，不是写死的"
    assert ".of-step.is-live .of-dot" in css
    for key in ("@keyframes ofPulse", "@keyframes ofRing", "@keyframes ofFlow"):
        assert key in css, f"{key} 不见了，动图就不动了"
    assert "prefers-reduced-motion" in css, "要对晕动症用户关掉动画"


def test_finished_and_disputed_orders_end_differently():
    """正常收场落到「已结算」；争议 / 退款 / 取消接在最后并标成要人看一眼。"""
    js = _js()
    assert 'step("settled", "已结算"' in js
    assert "{ strict: true }" in js, "「已结算」只能由真实 settled 点亮，别被后面的负面终局带亮"
    for word in ("争议中", "已仲裁", "已退款", "已取消"):
        assert word in js
    assert "warn: true" in js


# --------------------------------------------------------------- 排版与接线


def test_card_click_opens_the_order_diagram_in_place():
    html = HTML.read_text(encoding="utf-8")
    assert 'id="order-flow"' in html, "要有一个位置放这一单的状态图"
    board_at = html.index('id="order-board-card"')
    flow_at = html.index('id="order-flow"')
    assert flow_at > board_at, "状态图挂在订单图下面"
    assert 'id="order-flow" hidden' in html, "没点单的时候它是收起的"
    assert "cyber-order-flow.js" in html, "页面必须加载状态图脚本"
    assert "cyber-order-flow.js" in GATE_SH.read_text(encoding="utf-8")

    orders = ORDERS_JS.read_text(encoding="utf-8")
    assert "KarmaOrderFlow.open(entry)" in orders, "点卡片要就地展开这一单的状态图"
    assert "function entryById(entryId)" in orders
    assert "flow.close()" in orders, "这一单退场了，状态图也要收起来"


def test_the_panel_shows_what_the_owner_asked_for():
    """订单号 / 卖家 / 卖家信息 / 创建时间 / 合同详情（点击查看）+ 下方状态图。"""
    js = _js()
    for needle in ("订单号", "创建时间", "合同详情", "点击查看", "data-of-contract", "data-of-party"):
        assert needle in js, f"订单头部缺少「{needle}」"
    assert 'var role = entry.direction === "out" ? "卖家" : "买家";' in js, (
        "卖方视角看的是买家，不能把对方一律写成卖家"
    )
    assert '"/v1/identity/" + encodeURIComponent(id) + "/card?scope=basic"' in js, (
        "对方信息只读身份卡 basic 视图，不碰隐私字段"
    )
    assert "a.getContract(entry.task_id)" in js, "合同详情读的是真合同接口"
    assert "of-rail" in js, "下方就是这一单的状态图"


def test_the_diagram_needs_no_signature_and_touches_no_keys():
    js = _js()
    for banned in ("personal_sign", "privateKey", "mnemonic", "seed", "eth_sign"):
        assert banned not in js, f"状态图不该碰 {banned}"


# --------------------------------------------------------------- 后端把数据交出来


@pytest.fixture(autouse=True)
def _clean_sessions():
    dv.reset_delivery_sessions()
    yield
    dv.reset_delivery_sessions()


async def _settlement(db, task_id: str, *, scene_id: str | None, status: str = "in_progress"):
    db.add(
        SettlementModel(
            task_id=task_id,
            escrow_amount=12.0,
            currency="USDC",
            status=status,
            client_agent_id=BUYER,
            worker_agent_id=SELLER,
            progress_rule_spec={"scene_id": scene_id} if scene_id else None,
        )
    )
    await db.flush()
    return task_id


@pytest.mark.asyncio
async def test_entry_detail_hands_over_scene_and_history(client, db_session):
    await _settlement(db_session, "task-flow-1", scene_id="logistics_delivery")
    db_session.add(
        SettlementTransitionAuditModel(
            task_id="task-flow-1",
            from_status="draft",
            to_status="accepted",
            transition_allowed=True,
            guard_stage="route",
        )
    )
    await db_session.flush()

    r = await client.get(
        "/v1/payments/entries/settlement/task-flow-1",
        headers={"X-Karma-Identity-Id": BUYER},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["entry"]["detail"]["scene_id"] == "logistics_delivery", "图上要知道这是哪种生意"
    assert [h["to_status"] for h in body["history"]] == ["accepted"], "每步的时刻来自真实流转"


@pytest.mark.asyncio
async def test_entry_detail_hands_over_the_delivery_verification_only_when_it_exists(client, db_session):
    await _settlement(db_session, "task-flow-2", scene_id="logistics_delivery")

    r = await client.get(
        "/v1/payments/entries/settlement/task-flow-2",
        headers={"X-Karma-Identity-Id": BUYER},
    )
    assert r.status_code == 200, r.text
    assert r.json()["verification"] is None, "没开过交付验证就是 null，不能编一个出来"

    sess = create_verification_session(
        task_id="task-flow-2",
        scene_id="logistics_delivery",
        seller_agent_id=SELLER,
        buyer_agent_id=BUYER,
        logistics_agent_id="kid_flow_logistics",
    )
    seller_ship(sess["verification_id"], actor_agent_id=SELLER, ship_proof_hash="shiphash1234567890")

    r2 = await client.get(
        "/v1/payments/entries/settlement/task-flow-2",
        headers={"X-Karma-Identity-Id": BUYER},
    )
    assert r2.status_code == 200, r2.text
    ver = r2.json()["verification"]
    assert ver["scene_id"] == "logistics_delivery"
    kinds = {e["kind"] for e in ver["events"]}
    assert "seller_shipped" in kinds, "真实发生过的事件才能在图上点亮「卖家已发货」"


def test_the_ledger_never_invents_a_scene():
    service = LEDGER_SERVICE.read_text(encoding="utf-8")
    assert "def scene_id_of(spec: Any)" in service
    assert "认不出来就返回 None" in service, "认不出服务类型要如实返回 None"
    route = LEDGER_ROUTE.read_text(encoding="utf-8")
    assert '"verification": _task_verification(entry)' in route
    assert "def _task_verification(entry: dict)" in route

# --------------------------------------------------- 操作台要能标出这是哪种生意


def test_the_console_can_tag_an_order_with_its_service_type():
    """不选服务类型 -> 永远只有通用图。所以下单的地方必须能选，而且选项只有一份来源。"""
    html = HTML.read_text(encoding="utf-8")
    assert 'id="pc-scene" data-scene-select' in html, "发起收付要能选服务类型"
    assert 'id="st-scene" data-scene-select' in html, "任务执行建单也要能选服务类型"
    js = _js()
    assert "function fillSceneSelects()" in js
    assert 'document.querySelectorAll("[data-scene-select]")' in js, "下拉选项从 SCENES 表生成"
    assert "fillSceneSelects();" in js, "进页面就把下拉填好"

    actions = (CONSOLE / "scripts/cyber-actions.js").read_text(encoding="utf-8")
    assert "progress_rule_spec: sceneId ? { scene_id: sceneId } : undefined" in actions, (
        "付款码要把服务类型一起提交，否则这一单的图就退化成通用图"
    )
    assert "progress_rule_spec: scene ? { scene_id: scene } : undefined" in actions, (
        "任务执行建结算单也要带上服务类型"
    )


@pytest.mark.asyncio
async def test_create_settlement_keeps_the_service_scene(client):
    """建单时给的服务类型要落到这一单上，状态图才挑得对阶段表。"""
    await post_minimal_contract(client, task_id="task-scene-1", client_agent_id=BUYER, escrow_amount=20.0)
    r = await client.post(
        "/v1/settlement/create",
        json={
            "task_id": "task-scene-1",
            "client_agent_id": BUYER,
            "escrow_amount": 20.0,
            "currency": "USDC",
            "progress_rule_spec": {"scene_id": "food_delivery"},
        },
    )
    assert r.status_code == 201, r.text

    d = await client.get(
        "/v1/payments/entries/settlement/task-scene-1",
        headers={"X-Karma-Identity-Id": BUYER},
    )
    assert d.status_code == 200, d.text
    assert d.json()["entry"]["detail"]["scene_id"] == "food_delivery"


@pytest.mark.asyncio
async def test_create_settlement_rejects_an_blank_scene(client):
    await post_minimal_contract(client, task_id="task-scene-2", client_agent_id=BUYER, escrow_amount=20.0)
    r = await client.post(
        "/v1/settlement/create",
        json={
            "task_id": "task-scene-2",
            "client_agent_id": BUYER,
            "escrow_amount": 20.0,
            "currency": "USDC",
            "progress_rule_spec": {"scene_id": "   "},
        },
    )
    assert r.status_code == 422, r.text