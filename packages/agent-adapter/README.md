# Agent adapters (examples)

Thin adapters (`openmanus`, `openclaw`, …) that:

- emit **public** evidence bundles,
- never embed private risk logic,
- call only **public** APIs or on-chain contracts.

**Installable bridges**

- **`packages/karma-openmanus`** — HMAC client for Karma BFF (`/v1/integration/*`).
- **`packages/karma-openclaw`** — stdio MCP server for OpenClaw → Karma public HTTP.

See `docs/AGENT_INTEGRATION.md`.
