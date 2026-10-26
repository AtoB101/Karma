"""Proof object identity — the four-part definition must be one object.

Pin the canonical chain that makes a "proof" independently verifiable:

    evidence bundle -> canonical JSON -> SHA256 -> proofHash (bytes32)
        -> EIP-712 digest -> secp256k1 signature -> teeAttestation

Each link is a deterministic pure function; any independent reimplementation
must reproduce the same bytes. These tests assert the two reference
implementations in the repo agree byte-for-byte, and that the pinned golden
vector is exactly the output of that chain.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "tee_attestation"))

from decentralized_verifier.rules.hashing import (  # noqa: E402
    canonical_json_bytes,
    proof_hash_bytes32,
)
import eip712_settlement as ref  # noqa: E402
from eth_keys import keys  # noqa: E402

GOLDEN = json.loads((ROOT / "scripts" / "tee_attestation" / "settlement_vector.json").read_text(encoding="utf-8"))


def test_proof_hash_matches_across_implementations():
    bundle = GOLDEN["proofHashSource"]["bundle"]
    assert ref.proof_hash_from_bundle(bundle) == proof_hash_bytes32(bundle)


def test_golden_vector_proof_hash_is_sha256_of_canonical_bundle():
    bundle = GOLDEN["proofHashSource"]["bundle"]
    expect = hashlib.sha256(canonical_json_bytes(bundle)).digest()
    assert GOLDEN["proofHash"] == "0x" + expect.hex()
    assert proof_hash_bytes32(bundle).hex() == expect.hex()


def test_canonical_json_is_stable():
    bundle = GOLDEN["proofHashSource"]["bundle"]
    # reorder a copy of the dict; canonical form must be identical
    import collections
    reordered = collections.OrderedDict(reversed(list(bundle.items())))
    assert canonical_json_bytes(bundle) == canonical_json_bytes(dict(reordered))
    # no whitespace, sorted keys
    raw = canonical_json_bytes(bundle)
    assert b" " not in raw and b"\n" not in raw


def test_proof_hash_is_sensitive_to_bundle():
    bundle = dict(GOLDEN["proofHashSource"]["bundle"])
    a = proof_hash_bytes32(bundle)
    bundle["price"] = "2000000"
    b = proof_hash_bytes32(bundle)
    assert a != b


def test_golden_vector_attestation_recovers_enclave():
    # digest + v/r/s must recover the pinned enclave address
    sig = keys.Signature(vrs=(GOLDEN["v"] - 27, int(GOLDEN["r"], 16), int(GOLDEN["s"], 16)))
    recovered = sig.recover_public_key_from_msg_hash(bytes.fromhex(GOLDEN["digest"][2:])).to_address()
    assert recovered == GOLDEN["enclaveAddress"]


def test_golden_vector_digest_is_eip712():
    # recompute the digest from first principles and compare to the pinned value
    domain_separator = bytes.fromhex(GOLDEN["domainSeparator"][2:])
    digest = ref.settlement_digest(
        domain_separator,
        GOLDEN["bindingId"],
        bytes.fromhex(GOLDEN["proofHash"][2:]),
        bytes.fromhex(GOLDEN["imageHash"][2:]),
    )
    assert "0x" + digest.hex() == GOLDEN["digest"]


def test_tee_attestation_layout():
    # teeAttestation = abi.encode(imageHash, v, r, s) = 128 bytes
    att = bytes.fromhex(GOLDEN["teeAttestation"][2:])
    assert len(att) == 128
    assert att[:32] == bytes.fromhex(GOLDEN["imageHash"][2:])
    assert int.from_bytes(att[32:64], "big") == GOLDEN["v"]
