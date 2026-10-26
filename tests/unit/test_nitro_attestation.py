"""Off-chain AWS Nitro attestation verifier — unit tests.

Builds a synthetic P-384 certificate chain (root → intermediate → leaf) and a
COSE_Sign1 document signed by the leaf, then exercises the full verification
path in scripts/tee_attestation/nitro_attestation.py. This proves the COSE
Sig_structure reconstruction, ES384 signature check, and chain validation are
internally consistent; real hardware validation still requires a live Nitro
enclave, but every byte-level rule here matches the AWS Nitro spec.
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "tee_attestation"))

import cbor2  # noqa: E402
from cryptography import x509  # noqa: E402
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature  # noqa: E402
from cryptography.x509.oid import NameOID  # noqa: E402

import nitro_attestation as na  # noqa: E402

PCR0 = bytes(range(48))  # fake 48-byte SHA384 measurement


def _make_cert(subject_cn, issuer_cn, subject_key, issuer_key, is_ca, now):
    builder = x509.CertificateBuilder()
    builder = builder.subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject_cn)]))
    builder = builder.issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, issuer_cn)]))
    builder = builder.not_valid_before(now - datetime.timedelta(days=1))
    builder = builder.not_valid_after(now + datetime.timedelta(days=30))
    builder = builder.serial_number(x509.random_serial_number())
    builder = builder.public_key(subject_key.public_key())
    builder = builder.add_extension(x509.BasicConstraints(ca=is_ca, path_length=None), critical=True)
    return builder.sign(issuer_key, hashes.SHA384())


def _der(cert):
    return cert.public_bytes(serialization.Encoding.DER)


def _pem(cert):
    return cert.public_bytes(serialization.Encoding.PEM)


def _build_chain():
    now = datetime.datetime.now(datetime.timezone.utc)
    root_key = ec.generate_private_key(ec.SECP384R1())
    int_key = ec.generate_private_key(ec.SECP384R1())
    leaf_key = ec.generate_private_key(ec.SECP384R1())

    root = _make_cert("nitro-root", "nitro-root", root_key, root_key, is_ca=True, now=now)
    intermediate = _make_cert("nitro-int", "nitro-root", int_key, root_key, is_ca=True, now=now)
    leaf = _make_cert("nitro-leaf", "nitro-int", leaf_key, int_key, is_ca=False, now=now)
    return {
        "root": root,
        "intermediate": intermediate,
        "leaf": leaf,
        "root_pem": _pem(root),
        "leaf_key": leaf_key,
        "leaf_der": _der(leaf),
        "int_der": _der(intermediate),
        "now": now,
    }


def _sign_cose(protected_bytes, payload_bytes, leaf_key):
    sig_structure = cbor2.dumps(["Signature1", protected_bytes, b"", payload_bytes])
    der_sig = leaf_key.sign(sig_structure, ec.ECDSA(hashes.SHA384()))
    # DER -> raw r||s
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    r, s = decode_dss_signature(der_sig)
    return r.to_bytes(48, "big") + s.to_bytes(48, "big"), sig_structure


def _build_document(chain, *, alg=-35, pcr0=PCR0, timestamp=None, user_data=b""):
    protected = cbor2.dumps({1: alg})
    payload = cbor2.dumps({
        na.CLAIM_MODULE_ID: b"i-00000000000000000-enc0000000000000000",
        na.CLAIM_DIGEST: "SHA384",
        na.CLAIM_TIMESTAMP: timestamp if timestamp is not None else int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000),
        na.CLAIM_PCRS: {0: pcr0},
        na.CLAIM_CERTIFICATE: b"",
        na.CLAIM_CABUNDLE: b"",
        na.CLAIM_USER_DATA: user_data,
    })
    raw_sig, _ = _sign_cose(protected, payload, chain["leaf_key"])
    return cbor2.dumps([protected, {na.COSE_X5C: [chain["leaf_der"], chain["int_der"]]}, payload, raw_sig])


@pytest.fixture
def chain():
    return _build_chain()


def test_valid_document_verifies(chain):
    enclave = bytes.fromhex("19e7e376e7c213b7e7e7e46cc70a5dd086daff2a")
    doc = _build_document(chain, user_data=enclave)
    result = na.verify_attestation(doc, chain["root_pem"], max_age_seconds=600)
    assert result.pcr0 == PCR0
    assert result.image_hash == na.keccak256(PCR0)
    assert result.enclave_address == "0x" + enclave.hex()


def test_tampered_payload_fails(chain):
    doc = _build_document(chain)
    cose = cbor2.loads(doc)
    protected, unprotected, payload_bytes, signature = cose
    claims = cbor2.loads(payload_bytes)
    claims[na.CLAIM_PCRS] = {0: bytes([0xFF] * 48)}  # tamper PCR0, keep original signature
    tampered = cbor2.dumps([protected, unprotected, cbor2.dumps(claims), signature])
    with pytest.raises(na.NitroAttestationError, match="signature"):
        na.verify_attestation(tampered, chain["root_pem"], max_age_seconds=600)


def test_wrong_root_fails(chain):
    doc = _build_document(chain)
    other_root_key = ec.generate_private_key(ec.SECP384R1())
    other_root = _make_cert("evil-root", "evil-root", other_root_key, other_root_key, is_ca=True, now=chain["now"])
    with pytest.raises(na.NitroAttestationError):
        na.verify_attestation(doc, _pem(other_root), max_age_seconds=600)


def test_stale_timestamp_fails(chain):
    old = int((datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)).timestamp() * 1000)
    doc = _build_document(chain, timestamp=old)
    with pytest.raises(na.NitroAttestationError, match="too old"):
        na.verify_attestation(doc, chain["root_pem"], max_age_seconds=300)


def test_pcr0_whitelist_mismatch_fails(chain):
    doc = _build_document(chain)
    with pytest.raises(na.NitroAttestationError, match="PCR0"):
        na.verify_attestation(doc, chain["root_pem"], expected_pcr0=bytes([1] * 48), max_age_seconds=600)


def test_wrong_alg_fails(chain):
    doc = _build_document(chain, alg=-7)  # ES256
    with pytest.raises(na.NitroAttestationError, match="algorithm"):
        na.verify_attestation(doc, chain["root_pem"], max_age_seconds=600)


def test_missing_x5c_fails(chain):
    protected = cbor2.dumps({1: -35})
    payload = cbor2.dumps({na.CLAIM_PCRS: {0: PCR0}, na.CLAIM_TIMESTAMP: 1, na.CLAIM_DIGEST: "SHA384"})
    doc = cbor2.dumps([protected, {}, payload, b"\x00" * 96])
    with pytest.raises(na.NitroAttestationError, match="x5c"):
        na.verify_attestation(doc, chain["root_pem"])


def test_sig_structure_encoding(chain):
    """Sig_structure must be exactly: ["Signature1", protected, b"", payload]."""
    protected = cbor2.dumps({1: -35})
    payload = cbor2.dumps({na.CLAIM_PCRS: {0: PCR0}})
    raw_sig, sig_structure = _sign_cose(protected, payload, chain["leaf_key"])
    assert sig_structure == na.sig_structure(protected, payload)
    # decode and check shape
    decoded = cbor2.loads(sig_structure)
    assert decoded[0] == "Signature1"
    assert decoded[1] == protected
    assert decoded[2] == b""
    assert decoded[3] == payload


def test_user_data_must_be_20_bytes(chain):
    with pytest.raises(na.NitroAttestationError, match="20-byte"):
        na.enclave_address_from_user_data(b"short")
