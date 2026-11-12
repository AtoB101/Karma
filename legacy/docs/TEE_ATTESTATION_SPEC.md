# TEE settlement attestation spec

## Purpose

Machine-verifiable settlement anchor #1. `KarmaBilateral.settleWithTEE` lets a
binding settle immediately (skipping the Layer-1 optimistic dispute window) when
an enclave signs the settlement digest with a key that is bound, at registration
time, to a verified hardware image measurement.

This document is the canonical description of the trust root, the exact digest
the enclave must sign, and how an independent party can reproduce verification
without running Solidity.

## Components

- **Enclave (AWS Nitro).** Holds a secp256k1 private key that never leaves the
  trusted hardware. Its public address is the enclave's identity on-chain.
- **Attester (operator role).** Verifies the raw Nitro attestation quote
  off-chain against the vendor root of trust, then calls `registerEnclave`.
- **`TEESettlementVerifier`.** On-chain registry that binds an enclave address to
  its `imageHash = keccak256(PCR0)` and verifies per-settlement signatures with
  a single `ecrecover`.
- **`KarmaBilateral`.** Entry point `settleWithTEE`; delegates signature
  verification to `TEESettlementVerifier` and then executes the settlement.

## Trust model

The expensive part — verifying the RSA+CBOR hardware quote against the Nitro
root of trust — happens exactly once per enclave, off-chain, at registration.
The `attester` is the only party allowed to call `registerEnclave`, and it must
refuse to register any address whose quote does not match the enclave image.

After registration, each settlement costs a single secp256k1 `ecrecover`. The
on-chain verifier checks three things and reverts on any failure:

1. the signer recovers from the EIP-712 digest with the provided `v, r, s`;
2. the signer is a registered enclave and not revoked (`active`);
3. the `imageHash` signed by the enclave equals the registered `imageHash`.

KarmaBilateral additionally requires the binding to be `ACTIVE`/`PENDING` and
past `settleAfter`, and that `teeVerifier` is non-zero.

## Registration flow (off-chain quote verification)

1. Enclave boots and produces a Nitro attestation document: a COSE_Sign1
   (RFC 9052) whose payload carries PCR0 (the 48-byte SHA384 image measurement),
   a timestamp, and `user_data`. The enclave's secp256k1 address is carried in
   `user_data` as a 20-byte value.
2. The operator (attester) verifies the document against the vendor root of trust
   using the reference verifier (see below) or an audited equivalent, then derives
   `imageHash = keccak256(PCR0)` and `enclaveAddress` from `user_data`.
3. The attester calls `TEESettlementVerifier.registerEnclave(enclaveAddress, imageHash)`.
   This binds `enclaveAddress -> (imageHash, active=true, registeredAt)`.

## Settlement flow

1. The enclave computes the EIP-712 digest below and signs it with its key.
2. A caller submits `settleWithTEE(bindingId, proofHash, teeAttestation)` where
   `teeAttestation = abi.encode(imageHash, v, r, s)`.
3. `TEESettlementVerifier.verifySettlement` recovers the signer and validates
   the three checks above.
4. On success, `KarmaBilateral` executes the settlement and emits
   `TEESettled(bindingId, imageHash)`.

## Proof object identity (canonical)

A "proof" is one object, defined as this deterministic chain:

```
evidence_bundle   -> canonical JSON (sorted keys, no whitespace)
                  -> SHA-256
                  -> proofHash (bytes32, exactly the 32-byte digest)

(bindingId, proofHash, imageHash)
                  -> EIP-712 digest (below)
                  -> secp256k1 signature by the enclave
                  -> teeAttestation = abi.encode(imageHash, v, r, s)
```

`proofHash` is **not** an opaque keccak placeholder. Its canonical value is the
raw 32-byte SHA-256 of the canonical evidence bundle:

```
proofHash = SHA256(canonical_json_bytes(bundle_dict))   # 32 bytes == bytes32
imageHash = keccak256(PCR0)                              # 32 bytes == bytes32
```

SHA-256 is used for the bundle digest (not keccak256) because it is the evidence
layer's zero-dependency digest and its 32-byte output is exactly a bytes32. The
canonical serialization is `json.dumps(obj, sort_keys=True, separators=(",", ":"))`,
shared with `decentralized_verifier/rules/hashing.py`.

Reference implementations of this exact chain:

- `decentralized_verifier/rules/hashing.py::proof_hash_bytes32` — evidence-side.
- `scripts/tee_attestation/eip712_settlement.py::proof_hash_from_bundle` — TEE-side.
- `scripts/tee_attestation/settlement_vector.json` — pinned golden vector covering
  bundle -> proofHash -> digest -> signature -> attestation.

Pin test: `tests/unit/test_proof_identity.py` asserts the two implementations
agree byte-for-byte and that the golden vector is exactly this chain's output.

## EIP-712 digest (exact)

```
DOMAIN_TYPEHASH = keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)")
TEE_TYPEHASH    = keccak256("TeeSettlement(uint256 bindingId,bytes32 proofHash,bytes32 imageHash)")

DOMAIN_SEPARATOR = keccak256(abi.encode(
    DOMAIN_TYPEHASH,
    keccak256("KarmaTEESettlementVerifier"),
    keccak256("1"),
    block.chainid,
    address(this)          // the TEESettlementVerifier contract, NOT KarmaBilateral
))

structHash = keccak256(abi.encode(TEE_TYPEHASH, bindingId, proofHash, imageHash))
digest     = keccak256(abi.encodePacked("\x19\x01", DOMAIN_SEPARATOR, structHash))
```

The signature is secp256k1 over `digest`, with `v` in the Solidity convention
(27/28). The `recoverStrict` path in `SignatureValidator` enforces low-s and
valid `v`, so malleable signatures are rejected.

## Key rotation and revocation

- `revokeEnclave(address)` (admin only) sets `active = false`; settlement
  signatures from that address immediately revert with `EnclaveNotActive`.
- Rotation = register a new address (new key, possibly new image) and revoke
  the old one. Registration is idempotent per address.

## Threat model

Protected:

- A valid enclave signature proves the signer held a key whose address is bound
  to an attester-verified image, and that the proof/image hashes were not
  altered in transit to the chain.
- A revoked or unregistered enclave cannot settle.

Not protected (explicit non-goals):

- The `attester` and `admin` roles are trusted. A malicious attester can
  register an arbitrary address; a malicious admin can revoke valid enclaves.
  Both should be behind multisig / timelock in production.
- `imageHash` is a trust assertion made by the attester; the chain does not
  re-verify the raw Nitro quote (RSA+CBOR on-chain would be gas-prohibitive).
- `proofHash` semantics (what the execution proof actually contains) are defined
  separately by the evidence-bundle standard; this verifier only authenticates
  that an enclave signed over a given hash.

## Attester reference implementation

The off-chain hardware-verification half lives in `scripts/tee_attestation/`:

- `nitro_attestation.py` — decodes the COSE_Sign1 document, rebuilds the exact
  `Sig_structure`, verifies the ES384 signature with the leaf certificate, walks
  the `x5c` chain to the trusted root, checks timestamp freshness, and extracts
  `PCR0` / `imageHash` / `user_data`. Raises `NitroAttestationError` on any
  failure. No network, no chain access — pure and auditable.
- `attester_cli.py` — `verify` (off-chain only, prints JSON) and `register`
  (verifies then broadcasts `registerEnclave`).
- `root.pem` — AWS Nitro Enclaves Root CA G1, fetched from the official
  `AWS_NitroEnclaves_Root-G1.zip`. The verifier trusts this anchor; it is not
  transmitted inside the attestation document.

Reproduce a verification:

```
python scripts/tee_attestation/attester_cli.py verify ./attestation.cose     --root-ca scripts/tee_attestation/root.pem --max-age 300
```

Unit coverage for the byte-level rules (Sig_structure shape, ES384, chain
validation, freshness, PCR whitelist, x5c extraction) is in
`tests/unit/test_nitro_attestation.py`.

## Independent verification

Reference implementation and golden vector:

- `scripts/tee_attestation/eip712_settlement.py` — language-independent
  re-implementation of the digest; self-checks signature recovery.
- `scripts/tee_attestation/settlement_vector.json` — pinned golden vector.

Reproduce:

```
python scripts/tee_attestation/eip712_settlement.py [0x<verifier-address>]
```

The positional argument is the `TEESettlementVerifier` address (`verifyingContract`).
It defaults to the zero address, which is valid only for the pinned golden
vector. To validate a live deployment, pass the real verifier address and
compare the emitted `digest` against the on-chain `DOMAIN_SEPARATOR` recomputation.

## Non-goals

- No on-chain Nitro quote (RSA+CBOR) verification.
- No ZK settlement proofs (Layer 3) — reserved, not implemented here.
