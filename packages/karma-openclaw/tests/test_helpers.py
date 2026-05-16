import json

from karma_openclaw.helpers import (
    build_execution_receipt_skeleton,
    build_mcp_execution_extension,
    new_client_nonce,
    stable_sha256_hex,
)


def test_new_client_nonce_unique():
    a = new_client_nonce()
    b = new_client_nonce()
    assert a != b
    assert a.startswith("oc-")


def test_stable_sha256_deterministic():
    assert stable_sha256_hex({"b": 1, "a": 2}) == stable_sha256_hex({"a": 2, "b": 1})


def test_mcp_extension_hashes():
    ext = build_mcp_execution_extension(
        mcp_server_id="karma-openclaw",
        mcp_tool_name="karma_get_capacity",
        tool_call_trace={"id": 1},
        normalized_result={"ok": True},
    )
    assert ext["kind"] == "mcp"
    assert len(ext["trace_hash"]) == 64


def test_execution_receipt_skeleton_step_index():
    body = build_execution_receipt_skeleton(
        task_id="task-1",
        agent_id="seller-b",
        step_index=2,
        tool_name="demo",
        input_hash="a" * 64,
        output_hash="b" * 64,
    )
    assert body["step_index"] == 2
    assert body["signature"] is None
    json.dumps(body)
