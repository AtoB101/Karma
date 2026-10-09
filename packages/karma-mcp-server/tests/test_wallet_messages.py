from karma_mcp_server.wallet_messages import (
    build_create_key_message,
    build_revoke_key_message,
)


def test_create_key_message_matches_server_format():
    """与 services/runtime_wallet.build_create_key_message 逐字对齐。"""
    got = build_create_key_message(
        karma_identity_id="ident-1",
        wallet_address="0xAbC0000000000000000000000000000000000001",
        permissions=["request_voucher", "place_order"],
        single_limit=5.0,
        daily_limit=20.0,
        expire_time=None,
        agent_name="claw-1",
        agent_binding="agent-9",
    )
    assert got == (
        "Karma Runtime Key Create\n"
        "karma_identity_id:ident-1\n"
        "wallet_address:0xAbC0000000000000000000000000000000000001\n"
        "permissions:place_order,request_voucher\n"
        "single_limit:5.0\n"
        "daily_limit:20.0\n"
        "expire_time:never\n"
        "agent_name:claw-1\n"
        "agent_binding:agent-9"
    )


def test_create_key_message_blank_expire_is_never():
    got = build_create_key_message(
        karma_identity_id="i",
        wallet_address="0x1",
        permissions=[],
        single_limit=1.0,
        daily_limit=1.0,
        expire_time="   ",
        agent_name="a",
        agent_binding=None,
    )
    assert "expire_time:never" in got
    assert got.endswith("agent_binding:")


def test_revoke_key_message_matches_server_format():
    got = build_revoke_key_message(
        key_id="kid", karma_identity_id="ident-1", wallet_address="0xabc"
    )
    assert got == (
        "Karma Runtime Key Revoke\nkey_id:kid\nkarma_identity_id:ident-1\nwallet_address:0xabc"
    )
