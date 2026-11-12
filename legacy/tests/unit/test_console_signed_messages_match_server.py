"""操作台那几个「签名串」函数，行的标签与顺序必须跟服务端同源。

钱包签名串两端各拼一遍（服务端 Python、操作台 JS）：少一行、换个
顺序，用户点下去就只吃 400。服务端是唯一真源 —— 这里把服务端拼出来的
行标签抓出来，逐个比对操作台的 6 个 builder（铸钥匙 ×3、确认绑定、
拒绝绑定、取消绑定）。新增字段时先改服务端，让本文件告诉你操作台
还差哪几份没跟上。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from services import runtime_wallet

ROOT = Path(__file__).resolve().parents[2]

AUTHORIZE = "apps/console/scripts/cyber-authorize.js"
ACTIONS = "apps/console/scripts/cyber-actions.js"
HANDOFF = "apps/console/scripts/cyber-handoff.js"

CREATE_KEY_KW = {
    "karma_identity_id": "kid_probe",
    "wallet_address": "0x" + "0" * 40,
    "permissions": ["trade:place-order"],
    "single_limit": 1.0,
    "daily_limit": 2.0,
    "expire_time": None,
    "agent_name": "console-agent",
    "agent_binding": "agent-probe",
    "agent_public_key_fingerprint": "a1b2c3d4e5f60718",
}
BIND_KW = {
    "key_id": "KRM_RT_kid_probe_secret",
    "karma_identity_id": "kid_probe",
    "wallet_address": "0x" + "0" * 40,
    "client_nonce": "0f9a1b2c3d4e5f60",
}
CONFIRM_KW = {**BIND_KW, "activation_code": "K7Q2-M4XP"}

PAIRS = [
    (AUTHORIZE, "buildCreateKeyMsg", "build_create_key_message", CREATE_KEY_KW),
    (ACTIONS, "buildCreateKeyMsg", "build_create_key_message", CREATE_KEY_KW),
    (HANDOFF, "buildCreateKeyMsg", "build_create_key_message", CREATE_KEY_KW),
    (HANDOFF, "buildConfirmBindMsg", "build_confirm_bind_message", CONFIRM_KW),
    (HANDOFF, "buildRejectBindMsg", "build_reject_bind_message", BIND_KW),
    (HANDOFF, "buildUnbindKeyMsg", "build_unbind_key_message", BIND_KW),
]


def _server_lines(server_fn: str, kw: dict) -> list[str]:
    """服务端拼出来那串的行（真源）。"""
    message = getattr(runtime_wallet, server_fn)(**kw)
    lines = message.splitlines()
    assert lines and lines[0].startswith("Karma "), lines
    return lines


def _js_labels(rel: str, fn: str, labels: list[str]) -> tuple[str, list[str]]:
    text = (ROOT / rel).read_text(encoding="utf-8")
    start = text.index("function " + fn + "(")
    end = text.index("].join(", start)
    region = text[start:end]
    alt = "|".join(sorted({re.escape(x) for x in labels}, key=len, reverse=True))
    found = re.compile(r"\b(" + alt + r"):").findall(region)
    return region, found


@pytest.mark.parametrize("rel,fn,server_fn,kw", PAIRS, ids=[p[1] + "@" + p[2] for p in PAIRS])
def test_console_signed_message_matches_the_server(rel, fn, server_fn, kw):
    lines = _server_lines(server_fn, kw)
    labels = [line.split(":", 1)[0] for line in lines[1:]]
    region, found = _js_labels(rel, fn, labels)
    assert lines[0] in region, f"{rel} 的 {fn} 标题行不对"
    assert found == labels, (
        f"{rel} 的 {fn} 行序与服务端 {server_fn} 不一致"
    )
