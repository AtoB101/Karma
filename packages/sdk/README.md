# @karma-network/sdk

TypeScript **HTTP** client for Karma public API (`KarmaPublicSdk`).

Covers capacity lock/release, vouchers, settlement transitions, disputes, receipts,
and typed execution-receipt extension helpers. Targets `openapi/` public surfaces.

**On-chain Bilateral** (lock/bind/settle/finalizeSettle) lives in
[`packages/karma-sdk`](../karma-sdk/) — use that for Sepolia pilot bill tokens.

**Wallet connect / EIP-712 browser signing** is not bundled here yet; console Trade
still accepts operator-supplied signatures (real MetaMask path is a P0 follow-up).

## Usage

```ts
import { KarmaPublicSdk } from "@karma-network/sdk";

const sdk = new KarmaPublicSdk({
  runtimeUrl: "http://127.0.0.1:8000",
  apiKey: process.env.KARMA_API_KEY,
});

await sdk.lockUsdc("buyer-1", 100);
```

Pilot overview: [`docs/PILOT_E2E_PATH.md`](../../docs/PILOT_E2E_PATH.md).
