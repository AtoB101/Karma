"""On-chain DID is the single source of truth for agent identity.

IdentityProfile and AgentCard.agent_id are read-only projections of the DID:

  identity_id / agent_id := did:karma:{agent_address_lowercase}
  on_chain_did           := KYARegistry bytes32 DID (hex)
  did_agent_address      := agent address bound in KYARegistry

Off-chain profiles may rotate display_id and bind metadata, but must not invent
a divergent primary identity key.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_HEX_ADDR = re.compile(r"^0x[0-9a-fA-F]{40}$")
_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")

DID_PREFIX = "did:karma:"


def normalize_agent_address(address: str) -> str:
    a = (address or "").strip().lower()
    if not a.startswith("0x"):
        a = "0x" + a
    if not _HEX_ADDR.match(a):
        raise ValueError("agent address must be a 20-byte hex address")
    return a


def normalize_on_chain_did(did: str) -> str:
    d = (did or "").strip().lower()
    if d.startswith("0x"):
        d = d[2:]
    if not _HEX64.fullmatch(d):
        raise ValueError("on_chain_did must be 32-byte hex")
    return "0x" + d


def identity_id_from_did_agent(agent_address: str) -> str:
    return f"{DID_PREFIX}{normalize_agent_address(agent_address)}"


def agent_address_from_identity_id(identity_id: str) -> str | None:
    if not identity_id or not identity_id.startswith(DID_PREFIX):
        return None
    addr = identity_id[len(DID_PREFIX) :].strip().lower()
    return addr if _HEX_ADDR.match(addr) else None


def is_did_projection_identity_id(identity_id: str) -> bool:
    return agent_address_from_identity_id(identity_id) is not None


@dataclass(frozen=True)
class DidProjection:
    identity_id: str
    did_agent_address: str
    on_chain_did: str
    projection_readonly: bool = True
    source: str = "kya_did"

    def agent_card_id(self) -> str:
        """AgentCard.agent_id is the same projection string."""
        return self.identity_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity_id": self.identity_id,
            "did_agent_address": self.did_agent_address,
            "on_chain_did": self.on_chain_did,
            "projection_readonly": self.projection_readonly,
            "source": self.source,
            "agent_card_agent_id": self.agent_card_id(),
        }


def project_from_on_chain_did(
    *,
    did_agent_address: str,
    on_chain_did: str,
) -> DidProjection:
    addr = normalize_agent_address(did_agent_address)
    did = normalize_on_chain_did(on_chain_did)
    return DidProjection(
        identity_id=identity_id_from_did_agent(addr),
        did_agent_address=addr,
        on_chain_did=did,
    )


def assert_profile_matches_did_ssot(
    *,
    identity_id: str,
    did_agent_address: str | None,
    on_chain_did: str | None,
) -> None:
    """Reject profiles that claim DID linkage but diverge from the projection rule."""
    if not did_agent_address and not on_chain_did:
        return
    if not did_agent_address or not on_chain_did:
        raise ValueError("both did_agent_address and on_chain_did are required for DID projection")
    expected = project_from_on_chain_did(
        did_agent_address=did_agent_address,
        on_chain_did=on_chain_did,
    )
    if identity_id != expected.identity_id:
        raise ValueError(
            f"identity_id must be read-only projection of on-chain DID: "
            f"expected {expected.identity_id}, got {identity_id}"
        )
