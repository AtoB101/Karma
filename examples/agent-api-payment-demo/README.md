# Agent API Payment Demo (Public Mock)

Public-safe payment flow sketch for API-style services:

1. Create protected service / agent.
2. Share payment / order link.
3. Buyer creates order under capacity limits.
4. Seller submits delivery + evidence hash.
5. Buyer confirms or opens dispute → Bilateral settle path.

UI: `apps/console/`  
Integration: `docs/integration-guide.md`, `docs/SETTLEMENT_FLOW_PUBLIC.md`

Does not expose private scoring / anti-fraud internals.
