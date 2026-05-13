# OpenManus ↔ Karma tools

See `tools.json` for HTTP paths. Implement your OpenManus tool wrappers to:

1. Read `KARMA_BFF_URL` and `BFF_INTEGRATION_SECRET` from the **OpenManus server environment** (never from end-user chat).
2. For each POST, compute HMAC per `docs/KARMA_BFF_OPENMANUS_INTEGRATION.md`.
3. Call chain indexer separately; indexer POSTs `LOCK_CONFIRMED` to `/v1/webhooks/chain` before OpenManus runs heavy execution.

Reference BFF: `apps/karma_bff/`.

**Python package:** install **`karma-openmanus`** from `packages/karma-openmanus/` — it provides `KarmaBffClient` with the same HMAC rules so tool handlers do not duplicate signing code.
