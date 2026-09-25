"""MCP 真的把自助配接工具挂上了 —— 光有函数没注册，agent 一样调不到。"""

import asyncio


def _tools() -> dict:
    from karma_openclaw.server import build_app

    return {t.name: t for t in asyncio.run(build_app().list_tools())}


def test_build_app_registers_the_pairing_tools():
    names = set(_tools())
    assert {
        "karma_pairing_start",
        "karma_pairing_status",
        "karma_pairing_claim",
        "karma_pairing_local_status",
    } <= names


def test_pairing_claim_description_names_the_handoff_code():
    """描述里必须点出 handoff_code —— agent 靠它才知道要问主人要那串码。"""
    claim = _tools()["karma_pairing_claim"]
    desc = (claim.description or "") + " " + str(getattr(claim, "parameters", ""))
    assert "handoff_code" in desc


def test_pairing_start_description_tells_the_agent_to_hand_the_user_code_over():
    start = _tools()["karma_pairing_start"]
    desc = start.description or ""
    assert "user_code" in desc
