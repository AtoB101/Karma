# v0.1 Client Template (Quote -> Sign -> Settle)

This guide shows the minimum client path for the focused v0.1 flow.

## 1) Prerequisites

- SettlementEngine already deployed
- token allowlist configured in engine
- payer has token balance and has approved engine for transfer

## 2) Install client dependencies

```bash
npm install ethers dotenv tsx
```

## 3) Prepare env

Create `.env`:

```bash
RPC_URL=<your_rpc_url>
ENGINE_ADDRESS=<deployed_settlement_engine>
TOKEN_ADDRESS=<allowed_token_address>
PAYER_PRIVATE_KEY=<payer_private_key_hex>
PAYEE_ADDRESS=<payee_address>
```

## 4) Run the template

```bash
npx tsx examples/v01-quote-settlement.ts
```

## 5) Expected behavior

- script reads payer nonce from `SettlementEngine`
- script builds EIP-712 `Quote`
- payer signs typed data
- script calls `submitSettlement(quote, v, r, s)`
- tx receipt hash is printed

## 6) Common failures

- `TokenNotAllowed`: token not allowlisted in engine
- `InvalidNonce`: quote nonce does not match current payer nonce
- `DeadlineExpired`: quote deadline already expired
- `InvalidSignature`: wrong domain/types/signer/data
- `TokenTransferFailed`: missing balance/approval for payer
