import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from identity import (
    agent_address_from_identity_id,
    identity_id_from_agent_address,
    resolve_bridge_agent_id,
)
from card_builder import build_from_karma_agent


def test_identity_id_projection():
    addr = "0xAbcDef0123456789AbcDef0123456789aBcDef01"
    iid = identity_id_from_agent_address(addr)
    assert iid == "did:karma:0xabcdef0123456789abcdef0123456789abcdef01"
    assert agent_address_from_identity_id(iid) == "0xabcdef0123456789abcdef0123456789abcdef01"


def test_build_from_karma_agent_uses_did_projection(monkeypatch):
    monkeypatch.delenv("A2A_REQUIRE_DID_AGENT_ID", raising=False)
    card = build_from_karma_agent({
        "name": "Worker",
        "did_agent_address": "0x1111111111111111111111111111111111111111",
        "on_chain_did": "0x" + "ab" * 32,
        "endpoint_url": "http://localhost:9",
        "capabilities": ["karma_settle"],
    })
    assert card.agent_id == "did:karma:0x1111111111111111111111111111111111111111"
    assert card.karma.did_agent_address == "0x1111111111111111111111111111111111111111"
    assert card.karma.on_chain_did.startswith("0x")


def test_resolve_bridge_agent_id_from_did_env(monkeypatch):
    monkeypatch.setenv("A2A_DID_AGENT_ADDRESS", "0x2222222222222222222222222222222222222222")
    # re-import resolve after env set — function reads env at call time
    assert resolve_bridge_agent_id() == "did:karma:0x2222222222222222222222222222222222222222"
