"""
Karma Decentralized Verification — EIP-712 Attestation Signer
==============================================================
Produces and verifies EIP-712 typed structured data signatures for
VerifierAttestation objects.

EIP-712 domain:
  name:    "KarmaAttestation"
  version: "1"
  chainId: attestation.chain_id
  verifyingContract: attestation.contract_address

EIP-712 type:
  Attestation(
    bytes32 evidenceHash,
    string  cid,
    string  decision,
    string  verifierId,
    uint256 chainId
  )

Uses eth_account for EIP-712 encoding and signing when available,
with a pure-Python fallback using pycryptodome's keccak + ecdsa.
"""
from __future__ import annotations

import logging
from typing import Any

from decentralized_verifier import VerifierAttestation

logger = logging.getLogger(__name__)

# ── EIP-712 Domain Constants ───────────────────────────────────────────
DOMAIN_NAME = "KarmaAttestation"
DOMAIN_VERSION = "1"


def build_attestation_eip712_payload(
    attestation: VerifierAttestation,
) -> dict[str, Any]:
    """
    Build the complete EIP-712 typed structured data payload for an attestation.

    The payload is ready to be passed to eth_account.messages.encode_typed_data
    or any compatible EIP-712 encoder.

    Args:
        attestation: VerifierAttestation with populated fields.

    Returns:
        EIP-712 typed data dict with domain, primaryType, types, and message.
    """
    # Use zero-address when contract_address is empty (pre-deployment mode)
    contract_addr = attestation.contract_address or "0x0000000000000000000000000000000000000000"
    return {
        "domain": {
            "name": DOMAIN_NAME,
            "version": DOMAIN_VERSION,
            "chainId": attestation.chain_id,
            "verifyingContract": contract_addr,
        },
        "primaryType": "Attestation",
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "Attestation": [
                {"name": "evidenceHash", "type": "bytes32"},
                {"name": "cid", "type": "string"},
                {"name": "decision", "type": "string"},
                {"name": "verifierId", "type": "string"},
                {"name": "chainId", "type": "uint256"},
            ],
        },
        "message": {
            "evidenceHash": _to_bytes32(attestation.evidence_hash),
            "cid": attestation.cid,
            "decision": attestation.decision,
            "verifierId": attestation.verifier_id,
            "chainId": attestation.chain_id,
        },
    }


def sign_attestation(
    attestation: VerifierAttestation,
    private_key_hex: str,
) -> str:
    """
    Sign a VerifierAttestation using EIP-712 typed structured data.

    Uses eth_account.messages.encode_typed_data + Account.sign_message
    for standards-compliant EIP-712 signing, with a pure-Python fallback.

    Args:
        attestation:     Populated VerifierAttestation (signature field ignored).
        private_key_hex: 32-byte secp256k1 private key as 0x-prefixed hex.

    Returns:
        EIP-712 signature as 0x-prefixed hex string (65 bytes: r + s + v).
    """
    payload = build_attestation_eip712_payload(attestation)

    # ── Preferred: eth_account EIP-712 ──────────────────────────────
    try:
        from eth_account.messages import encode_typed_data
        from eth_account import Account

        encoded = encode_typed_data(
            full_message=payload,
        )
        signed = Account.sign_message(encoded, private_key=private_key_hex)
        raw_hex = signed.signature.hex()  # type: ignore[union-attr]
        return "0x" + raw_hex if not raw_hex.startswith("0x") else raw_hex

    except ImportError:
        logger.debug("eth_account not available, using pure-Python EIP-712 fallback")
    except Exception as exc:
        logger.warning("eth_account signing failed: %s, falling back", exc)

    # ── Fallback: pure-Python EIP-712 hash + ecdsa ──────────────────
    return _sign_attestation_pure_python(attestation, private_key_hex, payload)


def verify_attestation(attestation: VerifierAttestation) -> bool:
    """
    Verify the EIP-712 signature on a VerifierAttestation.

    Recovers the signer's public key from the signature and compares
    the derived Ethereum address to attestation.verifier_wallet.

    Args:
        attestation: VerifierAttestation with .signature populated.

    Returns:
        True if the signature is valid and the recovered address matches
        attestation.verifier_wallet.
    """
    if not attestation.signature or not attestation.signature.startswith("0x"):
        return False

    payload = build_attestation_eip712_payload(attestation)

    # ── Preferred: eth_account ──────────────────────────────────────
    try:
        from eth_account.messages import encode_typed_data
        from eth_account import Account

        # Recover directly using encode_typed_data
        encoded = encode_typed_data(full_message=payload)

        # Account.recover_message expects an encodable message
        recovered = Account.recover_message(
            encoded,
            signature=attestation.signature,
        )
        return recovered.lower() == attestation.verifier_wallet.lower()

    except ImportError:
        logger.debug("eth_account not available, using pure-Python recovery fallback")
    except Exception as exc:
        logger.warning("eth_account recovery failed: %s", exc)

    # ── Fallback: pure-Python EIP-712 recovery ──────────────────────
    return _verify_attestation_pure_python(attestation, payload)


# ═══════════════════════════════════════════════════════════════════════
# Pure-Python EIP-712 Fallback (ecdsa + keccak)
# ═══════════════════════════════════════════════════════════════════════

def _eip712_struct_hash(payload: dict[str, Any]) -> bytes:
    """
    Compute the EIP-712 typed structured data hash (domainSeparator ∥ hashStruct).
    Pure Python implementation using pycryptodome's keccak.
    """
    from Crypto.Hash import keccak

    def keccak256(data: bytes) -> bytes:
        k = keccak.new(digest_bits=256)
        k.update(data)
        return k.digest()

    def encode_type(primary_type: str, types: dict) -> str:
        """Encode types per EIP-712 spec."""
        type_names = [primary_type]
        for t in types[primary_type]:
            if t["type"] not in ("string", "bytes32", "uint256", "address"):
                type_names.append(t["type"])
        type_names = sorted(set(type_names))

        result = primary_type + "("
        result += ",".join(
            f"{f['type']} {f['name']}" for f in types[primary_type]
        )
        result += ")"
        for tn in type_names:
            if tn != primary_type and tn != "EIP712Domain":
                result += tn + "("
                result += ",".join(
                    f"{f['type']} {f['name']}" for f in types[tn]
                )
                result += ")"
        return result

    def type_hash(primary_type: str, types: dict) -> bytes:
        return keccak256(encode_type(primary_type, types).encode("utf-8"))

    def encode_data(primary_type: str, types: dict, data: dict) -> bytes:
        """Encode a single value per EIP-712."""
        result = type_hash(primary_type, types)

        for field in types[primary_type]:
            name, ftype = field["name"], field["type"]
            value = data[name]

            if ftype == "string":
                result += keccak256(str(value).encode("utf-8"))
            elif ftype == "bytes32":
                if isinstance(value, bytes):
                    result += value.ljust(32, b"\x00")[:32]
                else:
                    result += bytes.fromhex(value.replace("0x", "")).rjust(32, b"\x00")
            elif ftype == "uint256":
                result += int(value).to_bytes(32, "big")
            elif ftype == "address":
                addr = value.lower().replace("0x", "")
                result += bytes.fromhex(addr).rjust(32, b"\x00")

        return result

    # ── Compute domain separator ─────────────────────────────────────
    domain_data = payload["domain"]
    domain_types = {"EIP712Domain": payload["types"]["EIP712Domain"]}
    DOMAIN_SEPARATOR = keccak256(encode_data("EIP712Domain", domain_types, domain_data))

    # ── Compute message hash ─────────────────────────────────────────
    primary_type = payload["primaryType"]
    types = payload["types"]
    message = payload["message"]
    MESSAGE_HASH = keccak256(encode_data(primary_type, types, message))

    # ── EIP-712 final hash = keccak256("\x19\x01" ∥ domainSeparator ∥ hashStruct) ──
    return keccak256(b"\x19\x01" + DOMAIN_SEPARATOR + MESSAGE_HASH)


def _sign_attestation_pure_python(
    attestation: VerifierAttestation,
    private_key_hex: str,
    payload: dict[str, Any],
) -> str:
    """Pure Python EIP-712 signing with ecdsa + keccak."""
    from ecdsa import SigningKey, SECP256k1
    from Crypto.Hash import keccak

    digest = _eip712_struct_hash(payload)

    # Remove 0x prefix if present
    pk_hex = private_key_hex.replace("0x", "")
    sk = SigningKey.from_string(bytes.fromhex(pk_hex), curve=SECP256k1)

    # Sign the EIP-712 digest
    sig_raw = sk.sign_digest(digest)

    # Convert raw (r || s) signature to (r, s, v) format
    r, s = _decode_raw_signature(sig_raw)

    # Compute recovery id v (27 or 28)
    v = _compute_recovery_id(
        digest, r, s, attestation.verifier_wallet, sk
    )

    # Encode as r(32) + s(32) + v(1) = 65 bytes
    sig_bytes = (
        r.to_bytes(32, "big")
        + s.to_bytes(32, "big")
        + bytes([v])
    )
    return "0x" + sig_bytes.hex()


def _verify_attestation_pure_python(
    attestation: VerifierAttestation,
    payload: dict[str, Any],
) -> bool:
    """Pure Python EIP-712 signature verification with keccak + ecdsa."""
    from ecdsa import VerifyingKey, SECP256k1
    from Crypto.Hash import keccak

    try:
        digest = _eip712_struct_hash(payload)

        # Parse signature
        sig_hex = attestation.signature.replace("0x", "")
        sig_bytes = bytes.fromhex(sig_hex)

        if len(sig_bytes) != 65:
            return False

        r = int.from_bytes(sig_bytes[0:32], "big")
        s = int.from_bytes(sig_bytes[32:64], "big")
        v = sig_bytes[64]

        # Recover public key from (r, s, v)
        recovered_address = _recover_address_from_signature(digest, r, s, v)
        return recovered_address.lower() == attestation.verifier_wallet.lower()

    except Exception:
        return False


def _decode_raw_signature(sig_raw: bytes) -> tuple[int, int]:
    """Decode a raw 64-byte (r || s) ECDSA signature to (r, s) integers."""
    from ecdsa import SECP256k1
    from ecdsa.util import sigdecode_string
    return sigdecode_string(sig_raw, SECP256k1.order)  # type: ignore[return-value]


def _compute_recovery_id(
    digest: bytes,
    r: int,
    s: int,
    expected_wallet: str,
    signing_key: Any,
) -> int:
    """Compute the EIP-155 recovery id v (27 or 28)."""
    from ecdsa import VerifyingKey, SECP256k1
    from Crypto.Hash import keccak

    vk = signing_key.get_verifying_key()

    # Try v=27 (0) and v=28 (1)
    for v_base in (0, 1):
        try:
            recovered_address = _recover_address_from_signature(
                digest, r, s, v_base + 27
            )
            if recovered_address.lower() == expected_wallet.lower():
                return v_base + 27
        except Exception:
            continue

    # Fallback: use ecdsa default verification to determine
    try:
        # Build DER from (r, s) for verification
        from ecdsa.util import sigencode_der
        sig_der = sigencode_der(r, s, len(vk.pubkey.point.curve().order()))
        if vk.verify_digest(sig_der, digest):
            return 27
    except Exception:
        pass

    return 27  # Default


def _recover_address_from_signature(
    digest: bytes,
    r: int,
    s: int,
    v: int,
) -> str:
    """
    Recover Ethereum address from ECDSA signature components.

    Pure Python implementation — does not require eth_account/coincurve.
    Uses the public key recovery formula from SEC1.
    """
    from ecdsa import ellipticcurve, numbertheory
    from Crypto.Hash import keccak

    curve = ellipticcurve.CurveFp(
        SECP256k1_curve_p(),
        SECP256k1_curve_a(),
        SECP256k1_curve_b(),
    )
    generator = ellipticcurve.Point(
        curve,
        SECP256k1_generator_x(),
        SECP256k1_generator_y(),
        SECP256k1_curve_order(),
    )
    n = SECP256k1_curve_order()

    # Recovery: find the point R from (r, v)
    x = r
    # Compute y² = x³ + 7 (mod p)
    p = SECP256k1_curve_p()
    y_sq = (pow(x, 3, p) + 7) % p
    y = pow(y_sq, (p + 1) // 4, p)  # p ≡ 3 mod 4

    # Choose y parity based on v
    if v % 2 != y % 2:
        y = p - y

    R = ellipticcurve.Point(curve, x, y, n)

    # Recover public key: Q = r⁻¹(s·R − z·G)
    r_inv = numbertheory.inverse_mod(r, n)
    z = int.from_bytes(digest, "big") % n

    # sR - zG
    sR = R * s
    zG = generator * z
    Q = (sR + (-zG)) * r_inv

    # Serialize public key (uncompressed)
    pubkey_bytes = (
        b"\x04"
        + Q.x().to_bytes(32, "big")
        + Q.y().to_bytes(32, "big")
    )

    # Ethereum address = last 20 bytes of keccak256(pubkey[1:])
    k = keccak.new(digest_bits=256)
    k.update(pubkey_bytes[1:])  # Skip 0x04 prefix
    addr = k.digest()[-20:]

    return "0x" + addr.hex()


# ── secp256k1 Constants ────────────────────────────────────────────────

def SECP256k1_curve_p() -> int:
    return 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F


def SECP256k1_curve_a() -> int:
    return 0


def SECP256k1_curve_b() -> int:
    return 7


def SECP256k1_curve_order() -> int:
    return 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141


def SECP256k1_generator_x() -> int:
    return 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16CF81798


def SECP256k1_generator_y() -> int:
    return 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8


# ── Helpers ────────────────────────────────────────────────────────────

def _to_bytes32(hex_str: str) -> bytes:
    """Convert a hex string to a 32-byte value for EIP-712 bytes32."""
    if not hex_str:
        return b"\x00" * 32
    clean = hex_str.replace("0x", "")
    return bytes.fromhex(clean).rjust(32, b"\x00")
