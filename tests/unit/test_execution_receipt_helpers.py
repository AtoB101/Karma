"""Tests for P1 execution receipt helper digests."""
from __future__ import annotations

from sdk.execution_receipt_helpers import (
    agent_extension_from_payloads,
    api_extension_from_roundtrip,
    mcp_extension_from_payloads,
)
from core.hooks.hook_layer import sha256_of


def test_api_extension_hashes_match_sha256_of():
    ext = api_extension_from_roundtrip(
        request_body={"x": 1},
        response_body={"ok": True},
        http_status_code=201,
        latency_ms=33,
        error_code=None,
    )
    assert ext.request_hash == sha256_of({"x": 1})
    assert ext.response_hash == sha256_of({"ok": True})
    assert ext.http_status_code == 201


def test_mcp_and_agent_extensions_hex_length():
    m = mcp_extension_from_payloads(
        mcp_server_id="srv",
        mcp_tool_name="read",
        tool_call_trace={"steps": [1, 2]},
        normalized_result={"out": "z"},
    )
    assert len(m.trace_hash) == 64
    assert len(m.result_hash) == 64
    a = agent_extension_from_payloads(
        model_used="m",
        tool_calls_summary=[1],
        step_log={"s": 1},
        runtime_trace_envelope={"t": 2},
    )
    assert len(a.tool_calls_hash) == 64
    assert len(a.step_log_hash) == 64
    assert len(a.runtime_trace_hash) == 64
