#!/usr/bin/env python3
"""Reference EIP-712 settlement attestation (off-chain side of TEESettlementVerifier).

This is the canonical, language-independent description of the exact digest the
enclave must sign. It mirrors `TEESettlementVerifier.verifySettlement` byte-for-
byte in hashing order, so an enclave operator can sign settlements that the
on-chain verifier accepts without running any Solidity.

Trust flow (see docs/TEE_ATTESTATION_SPEC.md):
  - An enclave (AWS Nitro) holds a secp256k1 key whose address is registered on
    TEESettlementVerifier after the hardware quote is verified off-chain.
  - For each settlement, the enclave signs this digest; the on-chain verifier
    recovers the signer and checks it is a registered, active enclave.

Run:
  python scripts/tee_attestation/eip712_settlement.py [0x<verifier-address>]
The optional positional arg is the TEESettlementVerifier contract address used as
the EIP-712 `verifyingContract`; it defaults to the zero address, which is only
valid for the pinned golden vector. Pass the real deployed verifier address to
validate a live deployment. The script emits a golden test vector
(settlement_vector.json) and self-checks that the recovered signer equals the
enclave address.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from eth_utils import keccak
from eth_keys import keys

# Must match TEESettlementVerifier.sol exactly.
DOMAIN_NAME = "KarmaTEESettlementVerifier"
DOMAIN_VERSION = "1"
DOMAIN_TYPEHASH = keccak(text="EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)")
TEE_TYPEHASH = keccak(text="TeeSettlement(uint256 bindingId,bytes32 proofHash,bytes32 imageHash)")

ADDRESS_BYTES = 32


def _bytes32(value: int) -> bytes:
    return value.to_bytes(32, "big")


def compute_domain_separator(chain_id: int, verifying_contract: str) -> bytes:
    """domainSeparator = keccak256(DOMAIN_TYPEHASH, keccak(name), keccak(version), chainId, verifyingContract)."""
    verifying = int(verifying_contract, 16).to_bytes(20, "big")
    return keccak(
        DOMAIN_TYPEHASH
        + keccak(text=DOMAIN_NAME)
        + keccak(text=DOMAIN_VERSION)
        + _bytes32(chain_id)
        + b"\x00" * 12 + verifying
    )


def settlement_digest(domain_separator: bytes, binding_id: int, proof_hash: bytes, image_hash: bytes) -> bytes:
    """digest = keccak256(0x19 0x01 || domainSeparator || keccak256(TEE_TYPEHASH, bindingId, proofHash, imageHash))."""
    struct_hash = keccak(TEE_TYPEHASH + _bytes32(binding_id) + proof_hash + image_hash)
    return keccak(b"\x19\x01" + domain_separator + struct_hash)


def sign_settlement(
    private_key_hex: str,
    domain_separator: bytes,
    binding_id: int,
    proof_hash: bytes,
    image_hash: bytes,
) -> dict:
    digest = settlement_digest(domain_separator, binding_id, proof_hash, image_hash)
    sig = keys.PrivateKey(bytes.fromhex(private_key_hex.replace("0x", ""))).sign_msg_hash(digest)
    # eth_keys v is 0/1; Solidity/Foundry use 27/28.
    v = sig.v + 27
    return {
        "digest": "0x" + digest.hex(),
        "v": v,
        "r": "0x" + sig.r.to_bytes(32, "big").hex(),
        "s": "0x" + sig.s.to_bytes(32, "big").hex(),
        # ABI-encoded attestation passed to KarmaBilateral.settleWithTEE:
        "teeAttestation": "0x" + (image_hash + _bytes32(v) + sig.r.to_bytes(32, "big") + sig.s.to_bytes(32, "big")).hex(),
    }


def main() -> int:
    # Fixed, reproducible golden vector.
    enclave_pk = "0x" + "11" * 32
    enclave_addr = keys.PrivateKey(bytes.fromhex("11" * 32)).public_key.to_address()
    chain_id = 84532
    # This MUST be the TEESettlementVerifier contract address (`address(this)`
    # in the on-chain DOMAIN_SEPARATOR), not the KarmaBilateral core address.
    # Override with the real verifier address when validating a live deployment:
    #   python scripts/tee_attestation/eip712_settlement.py 0x<verifier>
    verifying_contract = sys.argv[1] if len(sys.argv) > 1 else "0x0000000000000000000000000000000000000000"
    binding_id = 1
    proof_hash = keccak(text="execution-proof")
    image_hash = keccak(text="nitro-image-pcr0")

    domain_separator = compute_domain_separator(chain_id, verifying_contract)
    out = sign_settlement("0x" + "11" * 32, domain_separator, binding_id, proof_hash, image_hash)

    # Self-check: recover the signer from the produced signature.
    sig = keys.Signature(
        vrs=(out["v"] - 27, int(out["r"], 16), int(out["s"], 16))
    )
    recovered = sig.recover_public_key_from_msg_hash(bytes.fromhex(out["digest"][2:])).to_address()

    vector = {
        "domain": {"name": DOMAIN_NAME, "version": DOMAIN_VERSION, "chainId": chain_id, "verifyingContract": verifying_contract},
        "domainSeparator": "0x" + domain_separator.hex(),
        "teeTypehash": "0x" + TEE_TYPEHASH.hex(),
        "bindingId": binding_id,
        "proofHash": "0x" + proof_hash.hex(),
        "imageHash": "0x" + image_hash.hex(),
        "enclaveAddress": enclave_addr,
        **out,
    }
    out_path = Path(__file__).with_name("settlement_vector.json")
    out_path.write_text(json.dumps(vector, indent=2) + "\n", encoding="utf-8")

    assert recovered == enclave_addr, f"recovery mismatch: {recovered} != {enclave_addr}"
    print("enclave address :", enclave_addr)
    print("digest          :", out["digest"])
    print("attestation     :", out["teeAttestation"])
    print("recover check   : OK")
    print("wrote", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
