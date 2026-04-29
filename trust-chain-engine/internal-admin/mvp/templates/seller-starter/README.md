# Trust-Chain Seller Starter (Private)

This starter helps API/tool authors monetize agent calls quickly.

## Quick start

```bash
cp .env.example .env
npm install
npm run seller:doctor
npm run seller:first-sale
```

## What this starter does

1. Wraps your tool with `wrapTool(...)`
2. Charges per invocation via `POST /api/price-paid`
3. Produces proof artifacts for first paid call

