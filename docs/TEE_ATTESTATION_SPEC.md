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
  its `imageHash` (PCR-derived measurement) and verifies per-settlement
  signatures with a single `ecrecover`.
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

1. Enclave boots and produces a Nitro attestation quote containing the PCR0 /
   image measurement (`imageHash`) and its secp256k1 public address.
2. The operator (attester) verifies the quote against the vendor root of trust
   using the reference verifier (see below) or an audited equivalent.
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
