"""操作台「给 agent 授权」向导：页面接线 + 与后端真实对接的系统顺序。

用户在操作台里走的是这四个动作，一个不能少、顺序也不能乱：

    1 选/建子身份   POST /v1/identity/role-profiles
    2 授权额度      PUT  /v1/capacity/{id}/allocations
    3 定类型        PUT  /v1/identity/role-profiles/{pid}
    4 划边界        PUT  /v1/identities/{id}/automation-policy
    → 生成 SDK      POST /runtime/create-key（钱包签名一次）

前半段是静态接线检查（别下次改版把某一步删了），
后半段真的跑一遍 HTTP，证明这条路在服务端是通的。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from httpx import AsyncClient

from config.settings import settings
from services.runtime_wallet import build_create_key_message

ROOT = Path(__file__).resolve().parents[2]
CONSOLE = ROOT / "apps/console"
HTML = CONSOLE / "pages/cyber/index.html"
JS = CONSOLE / "scripts/cyber-authorize.js"
GATE = ROOT / "scripts/acceptance/console_last_mile_gate.sh"

WIZARD_NODES = (
    'id="ag-wizard"',
    'id="agw-identity"',
    'id="agw-agent"',
    'id="agw-new"',
    'id="agw-new-name"',
    'id="agw-amount"',
    'id="agw-types"',
    'id="agw-single"',
    'id="agw-daily"',
    'id="agw-human"',
    'id="agw-perms"',
    'id="agw-ack"',
    'id="agw-generate"',
    'id="agw-result"',
)


def test_the_page_carries_the_four_step_wizard():
    html = HTML.read_text(encoding="utf-8")
    for node in WIZARD_NODES:
        assert node in html, f"授权向导缺少 {node}"
    for step in ("1 · 选身份", "2 · 授权额度", "3 · 定类型", "4 · 划边界"):
        assert step in html, f"向导缺少步骤说明 {step}"
    assert "生成接入包" in html, "最后那一下要说清楚生成的是「接入包」"
    assert "../../scripts/cyber-authorize.js" in html, "向导脚本必须被页面加载"
    # 向导要排在「我的 Agent」之前：先授权，再管理。
    assert html.index('id="ag-wizard"') < html.index('id="ag-list"')
    # 老的「接入一个 Agent」收进高级折叠，不删功能也不抢视线。
    assert 'class="card section ag-advanced"' in html
    assert 'id="ag-connect"' in html and 'id="ag-handoff-card"' in html


def test_the_three_assistant_types_map_to_role_profile_classes():
    js = JS.read_text(encoding="utf-8")
    assert "生活助理" in js and "工作助理" in js and "企业商业助理" in js
    # enterprise 是默认保密的那一类，业务助理走 individual。
    assert 'company: { label: "企业商业助理", klass: "enterprise" }' in js
    assert 'life: { label: "生活助理", klass: "individual" }' in js
    assert 'CLASS_TO_TYPE' in js


def test_the_wizard_calls_the_real_endpoints_in_order():
    js = JS.read_text(encoding="utf-8")
    for call in (
        "listRoleProfiles",
        "createRoleProfile",
        "setAllocations",
        "putAutomationPolicy",
        "runtimeCreateKey",
    ):
        assert call in js, f"向导没有调用 {call}"
    assert "/v1/identity/role-profiles/" in js, "定类型要 PUT 到角色档案"
    # 顺序：先策略（服务端拿它卡 Runtime Key 的权限与限额），再额度，最后签名铸造。
    order = [
        js.index("putAutomationPolicy"),
        js.index("setAllocations(id, next)"),
        js.index("runtimeCreateKey"),
    ]
    assert order == sorted(order), "保存策略 → 划额度 → 铸造，这个顺序不能反"
    # 限额是「覆盖式」写整张表，别的子身份的原值必须一起带上，否则会被清成 0。
    assert "state.allocations.forEach" in js
    assert "next[p.profile_id] = amount" in js


def test_the_sdk_step_is_an_eip191_signature_and_never_touches_a_private_key():
    js = JS.read_text(encoding="utf-8")
    assert "personal_sign" in js, "生成凭据要钱包签一次"
    assert "Karma Runtime Key Create" in js, "签名串要和 services/runtime_wallet.py 对齐"
    assert "pyFloatStr" in js and "pyUtcIso" in js
    for banned in ("privateKey", "private_key", "mnemonic", "seedPhrase", "seed_phrase"):
        assert banned not in js, f"向导里不该出现 {banned}"
    # 边界要显式确认，服务端 auto_enabled=true 时也这么要求。
    assert "responsibility_acknowledged: true" in js
    assert "auto_enabled: true" in js


def test_the_gate_checks_the_new_script():
    gate = GATE.read_text(encoding="utf-8")
    assert "scripts/cyber-authorize.js" in gate, "门禁要确认文件存在"
    loop = [ln for ln in gate.splitlines() if ln.strip().startswith("for js in")]
    assert loop, "门禁要保留 node --check 那一段"
    assert "cyber-authorize.js" in loop[0], "门禁要 node --check 它"


def test_the_wizard_names_the_agent_before_it_mints():
    """向导必须先把「agent 叫什么」收下来，再拿去铸钥匙。

    真机第一次跑就撞在这上面：钥匙必须指名 agent（生产口径不指名直接 400），
    而向导当时发的是 ``agent_binding: ""`` —— 用户按 1→4 填完、钱包也签了，
    点「生成」只会吃一句 HTTP 400。单测那边闸门是放开的（tests/conftest.py），
    所以只有真机 / 这条静态断言拦得住。
    """
    js = JS.read_text(encoding="utf-8")
    html = HTML.read_text(encoding="utf-8")
    assert 'id="agw-agent"' in html, "第 1 步要有「agent 叫什么」这一栏"
    assert "你的 agent 叫什么" in html
    assert "agent_binding: agentName" in js, "签名串要写 agent_binding"
    assert "agent_id: fields.agent_binding" in js, "请求体要带 agent_id 做交叉校验"
    assert 'agent_binding: ""' not in js, "空绑定铸不出来，这条老写法必须删干净"
    assert '"KARMA_AGENT_ID=" + agentId' in js, "接入包要带 KARMA_AGENT_ID"
    assert "renderSdk(res, p, fields, perms, amount, type, effectiveName, agentName)" in js
    assert "给你的 agent 起个名字" in js, "没填名字要当场说人话"
    assert "/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(agentName)" in js
    gate = GATE.read_text(encoding="utf-8")
    assert "agent_binding: agentName" in gate, "门禁也要钉住这条"


@pytest.mark.asyncio
async def test_the_wizard_payload_survives_the_production_binding_gate(
    client: AsyncClient, db_session, monkeypatch
):
    """把闸门按生产口径打开，向导现在发的那套载荷要能铸出钥匙。

    载荷形状 = cyber-authorize.js 里那一份：agent_name / agent_binding / agent_id 三处同名。
    """
    monkeypatch.setattr(settings, "runtime_require_agent_binding", True)
    owner = f"console-wizard-named-{uuid.uuid4().hex[:8]}"
    agent_name = "claw-001"
    perms = ["request_voucher", "submit_receipt"]
    acct = Account.create()
    expire = datetime.utcnow() + timedelta(days=7)
    msg = build_create_key_message(
        karma_identity_id=owner,
        wallet_address=acct.address,
        permissions=perms,
        single_limit=5.0,
        daily_limit=10.0,
        expire_time=expire,
        agent_name=agent_name,
        agent_binding=agent_name,
    )
    signed = acct.sign_message(encode_defunct(text=msg))
    resp = await client.post(
        "/runtime/create-key",
        json={
            "wallet_address": acct.address,
            "karma_identity_id": owner,
            "wallet_signature": signed.signature.hex(),
            "permissions": perms,
            "single_limit": 5.0,
            "daily_limit": 10.0,
            "expire_time": expire.isoformat(),
            "agent_name": agent_name,
            "agent_binding": agent_name,
            "agent_id": agent_name,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["agent_binding"] == agent_name
    assert body["key_binding"] == "agent_pending", "指了名就是「未激活」，没输码谁都花不了"
    assert body["activation_required"] is True


def test_changing_the_type_keeps_the_name_the_user_typed():
    """用户给子身份起了名字，第 3 步选类型不该把它改掉。

    只有名字还是类型标签（或空）时才跟着类型改名 —— 真机第一次跑就被这条咬过：
    「差旅助理」选完类型变成了「企业商业助理」。"""
    js = JS.read_text(encoding="utf-8")
    assert "function isTypeLabel(" in js
    assert "if (isTypeLabel(p.display_name)) profileBody.display_name = t.label;" in js
    # SDK 回执要写本次选的类型与名字，不能用内存里可能已经过期的那份档案。
    assert "renderSdk(res, p, fields, perms, amount, type, effectiveName, agentName)" in js
    assert "var effectiveName = isTypeLabel(p.display_name) ? TYPES[type].label : p.display_name;" in js


@pytest.mark.asyncio
async def test_wizard_write_sequence_reaches_a_runtime_key(client: AsyncClient, db_session, monkeypatch):
    """照着向导按钮的顺序打一遍真实 API，最后拿到可用的 Runtime Key。"""
    monkeypatch.setattr(settings, "runtime_require_saved_automation_policy", True)
    owner = "console-wizard-owner"
    auth = {"X-Karma-Identity-Id": owner}
    perms = sorted(
        [
            "request_voucher",
            "submit_receipt",
            "update_progress",
            "request_settlement",
            "sync_task_status",
        ]
    )

    # 主身份先锁仓（总览页那一步）。
    lock = await client.post(f"/v1/capacity/{owner}/lock", json={"amount": 100.0})
    assert lock.status_code == 200, lock.text

    # 1 · 新建子身份（「工作助理」= individual）。
    created = await client.post(
        "/v1/identity/role-profiles",
        json={"owner_identity_id": owner, "class": "individual", "display_name": "工作助理"},
        headers=auth,
    )
    assert created.status_code == 201, created.text
    profile_id = created.json()["profile_id"]

    # 3 · 定类型（改成企业商业助理 → 明细保密）。
    updated = await client.put(
        f"/v1/identity/role-profiles/{profile_id}",
        json={"class": "enterprise", "display_name": "企业商业助理"},
        headers=auth,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["class"] == "enterprise"

    # 2 · 授权额度。
    alloc = await client.put(
        f"/v1/capacity/{owner}/allocations",
        json={"allocations": {profile_id: 40.0}},
        headers=auth,
    )
    assert alloc.status_code == 200, alloc.text
    rows = {r["profile_id"]: r for r in alloc.json()["allocations"]}
    assert rows[profile_id]["allocated_credits"] == 40.0

    # 4 · 划边界。
    policy = await client.put(
        f"/v1/identities/{owner}/automation-policy",
        headers=auth,
        json={
            "auto_enabled": True,
            "responsibility_acknowledged": True,
            "single_limit": 20.0,
            "daily_limit": 40.0,
            "permissions": perms,
            "high_risk_mode": "above_single",
        },
    )
    assert policy.status_code == 200, policy.text
    assert policy.json()["single_limit"] == 20.0

    # → 生成 SDK：钱包签一次，密钥绑在这个子身份上。
    acct = Account.create()
    expire = datetime.utcnow() + timedelta(days=7)
    msg = build_create_key_message(
        karma_identity_id=owner,
        wallet_address=acct.address,
        permissions=perms,
        single_limit=20.0,
        daily_limit=40.0,
        expire_time=expire,
        agent_name="企业商业助理",
        agent_binding=None,
    )
    signed = acct.sign_message(encode_defunct(text=msg))
    minted = await client.post(
        "/runtime/create-key",
        json={
            "wallet_address": acct.address,
            "karma_identity_id": owner,
            "wallet_signature": signed.signature.hex(),
            "permissions": perms,
            "single_limit": 20.0,
            "daily_limit": 40.0,
            "expire_time": expire.isoformat(),
            "agent_name": "企业商业助理",
            "profile_id": profile_id,
        },
    )
    assert minted.status_code == 201, minted.text
    token = minted.json()["runtime_key"]
    assert token

    # 拿到的凭据真的能用，而且权限就是划的那几条。
    ctx = await client.get("/runtime/permissions", headers={"X-Karma-Runtime-Key": token})
    assert ctx.status_code == 200, ctx.text
    body = ctx.json()
    assert sorted(body["permissions"]) == perms
    assert body["single_limit"] == 20.0
    assert body["daily_limit"] == 40.0


def test_the_handoff_card_keeps_every_boundary_line_translatable():
    """结果卡里「它读到的边界」那一块，必须一行一个文本节点、逐行标 data-i18n-phrase。

    实测（韩语真机）：整块塞进一个 <pre> 里时，PRE 默认不翻 —— 中文页面对齐，
    韩语/英语页面上「身份 / 授权额度 / 单笔最高 …」整片留着中文，正好在用户
    最需要看懂的那一块。改法是把每一行拆成自己的 <span data-i18n-phrase>，
    再把十行原文加进五门语言包（见 test_console_phrase_language_purity.py）。
    """
    js = (CONSOLE / "scripts/cyber-authorize.js").read_text(encoding="utf-8")
    assert 'return \'<span data-i18n-phrase>\' + esc(line) + "</span>";' in js, \
        "边界块要逐行包成 <span data-i18n-phrase>，否则 PRE 里整片翻不了"
    assert "boundary([" in js, "边界块要走 boundary()，别又拼回一整块"
    assert 'esc(\n        "身份' not in js, "别把边界块拼成一个大字符串再 esc 一次"
    for line in ("身份        ", "名字        ", "agent       ", "类型        ",
                 "授权额度    ", "单笔最高    ", "每日上限    ", "人工确认    ",
                 "权限        ", "有效期至    "):
        assert '"' + line in js, "边界块少了这一行：%r" % line
    # 结果卡右上角那个绿标签也得有译文，不然五种语言都显中文。
    assert '>已生成</span>' in js
