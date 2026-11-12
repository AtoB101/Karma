#!/usr/bin/env python3
"""AWS Nitro Enclave attestation document verification (off-chain attester side).

Language-independent reference implementation of the checks an attester MUST run
before calling `TEESettlementVerifier.registerEnclave`. It verifies the raw
hardware attestation against the AWS Nitro root of trust and extracts the two
values the on-chain verifier needs:

  - `enclave`   — secp256k1 address the enclave signs settlements with (user_data)
  - `imageHash` — keccak256(PCR0), bound on-chain via `registerEnclave`

Attestation document layout (RFC 9052 COSE_Sign1, CBOR):

    COSE_Sign1 = [ protected : bstr,            # CBOR header map {1: -35 (ES384)}
                   unprotected : map,           # {33: [leaf DER, intermediate DER, ...]}
                   payload : bstr,              # CBOR attestation claims
                   signature : bstr ]           # ES384 raw r||s (96 bytes)

    Sig_structure (what the leaf certificate signs, RFC 9052 §4.4) =
        CBOR([ "Signature1", protected_bytes, b"", payload_bytes ])

The on-chain verifier does NOT re-verify this hardware quote (RSA+CBOR on-chain
would be gas-prohibitive). This module is the auditable off-chain half of the
trust split described in docs/TEE_ATTESTATION_SPEC.md.

Dependencies: cbor2, cryptography (already repo deps; cbor2 added in this change).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import cbor2
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

# COSE header parameter: x5c certificate chain (RFC 9360), label 33.
COSE_X5C = 33
# COSE algorithm ES384 (RFC 8152 / 9053).
ALG_ES384 = -35

# Attestation document claim keys (AWS Nitro Enclaves spec).
CLAIM_MODULE_ID = 0
CLAIM_DIGEST = 1
CLAIM_TIMESTAMP = 2
CLAIM_PCRS = 3
CLAIM_CERTIFICATE = 4
CLAIM_CABUNDLE = 5
CLAIM_PUBLIC_KEY = 6
CLAIM_USER_DATA = 7
CLAIM_NONCE = 8


class NitroAttestationError(Exception):
    """Raised when an attestation document fails any verification step."""


@dataclass
class VerifiedAttestation:
    """Output of a successful verification — the values registerEnclave needs."""
    module_id: bytes
    pcr0: bytes
    image_hash: bytes          # keccak256(pcr0)
    user_data: bytes           # raw user_data bytes (may be empty)
    timestamp: int             # ms since epoch from the document
    digest: str                # "SHA384"
    leaf_cert_der: bytes
    chain: list                # DER certs in x5c order (leaf first)

    @property
    def enclave_address(self) -> Optional[str]:
        """Enclave secp256k1 address carried in user_data (20 bytes), if present."""
        if len(self.user_data) == 20:
            return "0x" + self.user_data.hex()
        return None


# ─────────────────────────────────────────────────────────────────────────────
# COSE_Sign1
# ─────────────────────────────────────────────────────────────────────────────

def sig_structure(protected_bytes: bytes, payload_bytes: bytes) -> bytes:
    """Rebuild the exact bytes the leaf certificate signed (RFC 9052 §4.4).

    COSE_Sign1 signs: ["Signature1", body_protected, external_aad, payload].
    The signer-protected slot is omitted for Sign1; external_aad is empty here.
    """
    return cbor2.dumps(["Signature1", protected_bytes, b"", payload_bytes])


def _raw_to_der(raw_sig: bytes) -> bytes:
    """COSE ES384 signatures are raw r||s (96 bytes); cryptography wants DER."""
    if len(raw_sig) != 96:
        raise NitroAttestationError(f"expected 96-byte ES384 signature, got {len(raw_sig)}")
    r = int.from_bytes(raw_sig[:48], "big")
    s = int.from_bytes(raw_sig[48:], "big")
    return encode_dss_signature(r, s)


def verify_cose_signature(leaf_der: bytes, protected_bytes: bytes, payload_bytes: bytes, raw_sig: bytes) -> None:
    leaf = x509.load_der_x509_certificate(leaf_der)
    public_key = leaf.public_key()
    if not isinstance(public_key, ec.EllipticCurvePublicKey):
        raise NitroAttestationError("attestation leaf certificate is not an EC key")
    try:
        public_key.verify(_raw_to_der(raw_sig), sig_structure(protected_bytes, payload_bytes), ec.ECDSA(hashes.SHA384()))
    except InvalidSignature as exc:
        raise NitroAttestationError("COSE signature verification failed") from exc


# ─────────────────────────────────────────────────────────────────────────────
# X.509 chain
# ─────────────────────────────────────────────────────────────────────────────

def load_root_ca(root_pem: bytes) -> x509.Certificate:
    try:
        return x509.load_pem_x509_certificate(root_pem)
    except Exception as exc:
        raise NitroAttestationError("could not load root CA PEM") from exc


def verify_certificate_chain(chain_der: list, root_pem: bytes, now: Optional[datetime] = None) -> None:
    """Verify chain_der[0] chains up to the trusted root, with validity checks.

    The x5c array normally ends at the intermediate CA; the root is a trust
    anchor supplied by the verifier, not transmitted in the document. If the
    document happens to include the self-signed root, it must match the anchor.
    """
    if not chain_der:
        raise NitroAttestationError("empty certificate chain")
    now = now or datetime.now(timezone.utc)
    root = load_root_ca(root_pem)
    root_fp = root.fingerprint(hashes.SHA256())

    certs = [x509.load_der_x509_certificate(c) for c in chain_der]

    # If the presented chain ends in a self-signed cert, it must be the anchor.
    if certs[-1].issuer == certs[-1].subject:
        if certs[-1].fingerprint(hashes.SHA256()) != root_fp:
            raise NitroAttestationError("presented self-signed root does not match trusted AWS Nitro root")
        certs = certs[:-1]

    certs.append(root)  # trust anchor as the ultimate parent

    for i in range(len(certs) - 1):
        child, parent = certs[i], certs[i + 1]
        if now < child.not_valid_before_utc or now > child.not_valid_after_utc:
            raise NitroAttestationError(f"certificate {i} outside validity window")
        parent_pub = parent.public_key()
        if not isinstance(parent_pub, ec.EllipticCurvePublicKey):
            raise NitroAttestationError(f"issuer of certificate {i} is not an EC key")
        try:
            parent_pub.verify(child.signature, child.tbs_certificate_bytes, ec.ECDSA(hashes.SHA384()))
        except InvalidSignature as exc:
            raise NitroAttestationError(f"certificate {i} signature invalid") from exc


# ─────────────────────────────────────────────────────────────────────────────
# Document parsing
# ─────────────────────────────────────────────────────────────────────────────

def _extract_x5c(unprotected: dict) -> list:
    chain = unprotected.get(COSE_X5C)
    if not isinstance(chain, (list, tuple)) or not chain:
        raise NitroAttestationError("missing x5c certificate chain in unprotected header")
    return [c for c in chain if isinstance(c, bytes)]


def parse_attestation(document: bytes) -> tuple[VerifiedAttestation, bytes, bytes, bytes]:
    """Decode a COSE_Sign1 document into claims + the raw bytes needed to verify.

    Returns (parsed, protected_bytes, payload_bytes, signature). Decoding only;
    call `verify_attestation` for the full trust-root check.
    """
    try:
        cose = cbor2.loads(document)
    except Exception as exc:
        raise NitroAttestationError(f"not a valid CBOR COSE_Sign1: {exc}") from exc

    if not isinstance(cose, list) or len(cose) != 4:
        raise NitroAttestationError("COSE_Sign1 must be a 4-element CBOR array")

    protected_bytes, unprotected, payload_bytes, signature = cose
    if not isinstance(protected_bytes, bytes):
        raise NitroAttestationError("protected header must be a bstr")
    if not isinstance(unprotected, dict):
        raise NitroAttestationError("unprotected header must be a map")
    if not isinstance(payload_bytes, bytes):
        raise NitroAttestationError("payload must be a bstr")
    if not isinstance(signature, bytes):
        raise NitroAttestationError("signature must be a bstr")

    protected_map = cbor2.loads(protected_bytes)
    if not isinstance(protected_map, dict):
        raise NitroAttestationError("protected header must decode to a map")
    alg = protected_map.get(1)
    if alg != ALG_ES384:
        raise NitroAttestationError(f"unsupported COSE algorithm {alg!r} (expected {ALG_ES384})")

    claims = cbor2.loads(payload_bytes)
    if not isinstance(claims, dict):
        raise NitroAttestationError("payload must decode to a CBOR map")

    pcr0 = claims.get(CLAIM_PCRS, {}).get(0)
    if not isinstance(pcr0, bytes) or len(pcr0) != 48:
        raise NitroAttestationError("PCR0 missing or not a 48-byte SHA384 measurement")

    chain = _extract_x5c(unprotected)

    parsed = VerifiedAttestation(
        module_id=claims.get(CLAIM_MODULE_ID, b""),
        pcr0=pcr0,
        image_hash=keccak256(pcr0),
        user_data=claims.get(CLAIM_USER_DATA, b""),
        timestamp=int(claims.get(CLAIM_TIMESTAMP, 0)),
        digest=claims.get(CLAIM_DIGEST, ""),
        leaf_cert_der=chain[0],
        chain=chain,
    )
    return parsed, protected_bytes, payload_bytes, signature


# ─────────────────────────────────────────────────────────────────────────────
# Full verification
# ─────────────────────────────────────────────────────────────────────────────

def keccak256(data: bytes) -> bytes:
    from eth_utils import keccak
    return keccak(data)


def verify_attestation(
    document: bytes,
    root_pem: bytes,
    *,
    expected_pcr0: Optional[bytes] = None,
    max_age_seconds: Optional[int] = 300,
    now_ms: Optional[int] = None,
) -> VerifiedAttestation:
    """Run the complete verification and return the extracted values.

    Raises NitroAttestationError on any failure; otherwise the caller may treat
    `result.enclave_address` / `result.image_hash` as trusted (under the root CA).

    Steps:
      1. leaf certificate signature over the COSE Sig_structure (ES384)
      2. certificate chain terminates at the trusted AWS Nitro root
      3. timestamp freshness (replay mitigation)
      4. optional PCR0 whitelist
    """
    parsed, protected_bytes, payload_bytes, signature = parse_attestation(document)

    verify_cose_signature(parsed.leaf_cert_der, protected_bytes, payload_bytes, signature)
    verify_certificate_chain(parsed.chain, root_pem)

    if max_age_seconds is not None:
        now = now_ms if now_ms is not None else int(time.time() * 1000)
        if parsed.timestamp <= 0:
            raise NitroAttestationError("document timestamp missing")
        age = abs(now - parsed.timestamp)
        if age > max_age_seconds * 1000:
            raise NitroAttestationError(f"document timestamp too old: {age} ms > {max_age_seconds * 1000} ms")

    if expected_pcr0 is not None and parsed.pcr0 != expected_pcr0:
        raise NitroAttestationError("PCR0 does not match expected image measurement")

    return parsed


def enclave_address_from_user_data(user_data: bytes) -> str:
    if len(user_data) != 20:
        raise NitroAttestationError(f"user_data must be a 20-byte secp256k1 address, got {len(user_data)}")
    return "0x" + user_data.hex()


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("usage: python nitro_attestation.py <attestation-file-or-hex>")
        sys.exit(2)
    arg = sys.argv[1]
    if Path(arg).exists():
        document = Path(arg).read_bytes()
    else:
        document = bytes.fromhex(arg.replace("0x", ""))
    root = Path(__file__).with_name("root.pem").read_bytes()
    result = verify_attestation(document, root)
    print("module_id :", result.module_id.hex())
    print("pcr0      :", result.pcr0.hex())
    print("imageHash :", "0x" + result.image_hash.hex())
    print("enclave   :", result.enclave_address)
    print("timestamp :", result.timestamp)
    print("digest    :", result.digest)
