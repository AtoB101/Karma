# Karma EIP-712 Signing Payload Spec (V1)

This document defines the minimal payload backend/off-chain agents must sign
for the focused MVP flow:

> off-chain authorization signature -> on-chain settlement execution

## 1) Domain

`AuthTokenManager` computes:

- `name`: `KarmaAuth`
- `version`: `1`
- `chainId`: runtime chain id
- `verifyingContract`: deployed `AuthTokenManager` address

Equivalent Solidity constant:

```solidity
keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)")
```

## 2) Typed Struct

Type name: `Auth`

```text
Auth(
  bytes32 tokenId,
  address agent,
  uint8 opType,
  uint256 amount,
  uint256 nonce,
  uint256 deadline
)
```

Type hash in code:

```solidity
keccak256("Auth(bytes32 tokenId,address agent,uint8 opType,uint256 amount,uint256 nonce,uint256 deadline)")
```

## 3) Operation Codes (`opType`)

From `Types.OperationType`:

- `0` = `CreateBill`
- `1` = `ConfirmBill`
- `2` = `CancelBill`
- `3` = `SetThreshold`

MVP core flow uses only:

- `CreateBill`
- `ConfirmBill`
- (optional failure path) `CancelBill`

## 4) Signing and Submission Flow

1. Owner/agent issues auth token on-chain via `issueAuthToken(...)`.
2. Backend obtains digest via `getAuthDigest(tokenId, agent, opType, amount, deadline)`.
3. Sign digest with owner private key (`secp256k1`).
4. Submit `(v, r, s)` and payload fields into `BillManager` action.
5. Contract verifies:
   - token ownership and op binding,
   - amount bound,
   - deadline validity,
   - signature correctness,
   - replay/used token prevention.

## 5) Backend Requirements

- `deadline` MUST be:
  - greater than current block timestamp at execution time,
  - less than or equal to token `validUntil`.
- `amount` MUST be `> 0` and `<= maxAmount` bound in token.
- Use each token/signature once; replay is rejected.
- Never sign for a different `agent` than the token binds.

## 6) Reference (test helper parity)

Current reference implementation flow:

- `contracts/test/helpers/AuthTestHelper.sol`
- `contracts/test/ScenarioFlow.t.sol`

These tests are the canonical MVP examples for end-to-end sign-and-settle.
