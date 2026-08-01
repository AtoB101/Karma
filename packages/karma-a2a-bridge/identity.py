"""Identity projection helpers for A2A Bridge.

Canonical rule:
  On-chain DID (KYARegistry agent address / did bytes32) is the single source of truth.
  IdentityProfile.identity_id and AgentCard.agent_id are read-only projections of that DID.
"""
from __future__ import annotations

import os
import re

_HEX_ADDR = re.compile(r"^0x[0-9a-fA-F]{40}$")
_HEX64 = re.compile(r"^(0x)?[0-9a-fA-F]{64}$")


def normalize_agent_address(address: str) -> str:
    a = (address or "").strip().lower()
    if not a.startswith("0x"):
        a = "0x" + a
    if not _HEX_ADDR.match(a):
        raise ValueError("did_agent_address must be a 20-byte hex address")
    return a


def identity_id_from_agent_address(agent_address: str) -> str:
    """Projection: AgentCard.agent_id / IdentityProfile.identity_id."""
    return f"did:karma:{normalize_agent_address(agent_address)}"


def agent_address_from_identity_id(identity_id: str) -> str | None:
    prefix = "did:karma:"
    if not identity_id or not identity_id.startswith(prefix):
        return None
    addr = identity_id[len(prefix) :].strip().lower()
    if not _HEX_ADDR.match(addr):
        return None
    return addr


def normalize_on_chain_did(did: str) -> str:
    d = (did or "").strip().lower()
    if d.startswith("0x"):
        d = d[2:]
    if not _HEX64.fullmatch(d) and not _HEX64.fullmatch("0x" + d):
        # allow either 64 hex or 0x+64
        if len(d) != 64 or any(c not in "0123456789abcdef" for c in d):
            raise ValueError("on_chain_did must be 32-byte hex")
    return "0x" + d if not did.strip().lower().startswith("0x") else "0x" + d


def resolve_bridge_agent_id() -> str:
    """
    Bridge agent_id MUST be a DID projection when A2A_DID_AGENT_ADDRESS is set.
    Falls back to legacy A2A_AGENT_ID only when DID is unset (dev).
    """
    did_addr = os.getenv("A2A_DID_AGENT_ADDRESS", "").strip()
    if did_addr:
        return identity_id_from_agent_address(did_addr)
    legacy = os.getenv("A2A_AGENT_ID", "karma_bridge_001").strip()
    # If legacy already looks like a DID projection, keep it
    if agent_address_from_identity_id(legacy):
        return legacy
    return legacy


def assert_agent_id_is_did_projection(agent_id: str, *, strict: bool | None = None) -> None:
    """When strict, reject non-DID agent ids."""
    if strict is None:
        strict = os.getenv("A2A_REQUIRE_DID_AGENT_ID", "0").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
    if not strict:
        return
    if agent_address_from_identity_id(agent_id) is None:
        raise ValueError(
            "AgentCard.agent_id must be a read-only projection of on-chain DID "
            "(format: did:karma:0x…)"
        )
