"""Unit tests for DID → IdentityProfile / AgentCard projection SSOT."""
from services.identity_projection import (
    identity_id_from_did_agent,
    is_did_projection_identity_id,
    project_from_on_chain_did,
    assert_profile_matches_did_ssot,
)
import pytest


def test_project_from_on_chain_did():
    p = project_from_on_chain_did(
        did_agent_address="0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        on_chain_did="0x" + "11" * 32,
    )
    assert p.identity_id == "did:karma:0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    assert p.agent_card_id() == p.identity_id
    assert p.projection_readonly is True
    assert p.source == "kya_did"


def test_assert_profile_matches():
    assert_profile_matches_did_ssot(
        identity_id="did:karma:0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        did_agent_address="0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        on_chain_did="0x" + "11" * 32,
    )
    with pytest.raises(ValueError):
        assert_profile_matches_did_ssot(
            identity_id="random-id",
            did_agent_address="0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            on_chain_did="0x" + "11" * 32,
        )


def test_is_did_projection_identity_id():
    assert is_did_projection_identity_id(identity_id_from_did_agent("0x" + "ab" * 20))
    assert not is_did_projection_identity_id("karma_bridge_001")
