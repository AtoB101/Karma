# OpenManus ↔ Karma (integration)

Use the **`karma-openmanus`** installable package for HMAC-authenticated calls to **Karma BFF** (`/v1/integration/...`):

```bash
pip install -e ../../packages/karma-openmanus
```

See **`packages/karma-openmanus/README.md`** and **`docs/KARMA_BFF_OPENMANUS_INTEGRATION.md`**.

For **in-process tool instrumentation** (signed `ExecutionReceipt` per tool call), use the repo **`KarmaOpenManusAgent`** + `KarmaHookLayer` (`agents/openmanus/adapter.py`, `sdk.KarmaClient`) — that path does not go through BFF.
