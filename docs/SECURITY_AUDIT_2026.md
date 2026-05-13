# Karma Public Runtime — Security Audit (2026)

This document summarizes a focused security review of the **public** repository (FastAPI runtime, SDK surfaces, Redis-backed rate limits, settlement/progress rules) and the **controls implemented in code** in response.

## Threat model highlights

| Area | Risk | Mitigation shipped |
|------|------|-------------------|
| **Rule abuse / cross-tenant** | Any valid API key could drive **another party’s** settlement (partial, regret, dispute, worker transitions). | When `AUTH_ENFORCE_PROTECTED_ROUTES` and `SETTLEMENT_REQUIRE_PARTY_ACTOR` are both **true**, settlement mutations require the authenticated actor to match **buyer** (`client_agent_id`) or **worker** (`worker_agent_id`) per operation (`services/settlement_party_access.py`, `api/routes/settlement.py`). Progress **submit** binds actor to `seller_identity_id`; **timeout-confirm** and **confirm** bind to buyer when party binding is active (`api/routes/progress.py`). |
| **Dev API-key bypass** | `karma_{agent}_{secret}` accepted without config map when auth was not enforced, enabling mistaken “open” deployments. | **Opt-in** only: `AUTH_ALLOW_DEV_KEY_FALLBACK` (default **false**). Old behavior requires an explicit env flag (`api/middleware/auth.py`). |
| **Rate limit + Redis** | Raw API keys in Redis key names / logs; fail-open on Redis outage enables **unbounded** sensitive writes. | Keys use **SHA-256 digests** of API keys / `X-Forwarded-For` (`api/middleware/rate_limit.py`). `RATE_LIMIT_REDIS_FAIL_CLOSED` (required **true** in `production` via settings validator) returns **503** when Redis is unavailable instead of skipping limits. |
| **HTTP cache** | Shared caches storing authenticated JSON. | `Cache-Control: private, no-store` on all `/v1/*` responses (`api/app.py`). |
| **Path / cache poisoning** | Odd `task_id` / `receipt_id` segments; route shadowing (`…/task/…` vs dynamic ids). | `validate_public_url_segment` on high-risk paths (`services/path_param_safety.py`). **More-specific routes registered first** for receipts and bundles. |
| **Capacity / voucher rule abuse** | Any API key could **lock/release another identity’s** credits or **create vouchers** as another buyer / **verify/accept** as another seller. | When `AUTH_ENFORCE_PROTECTED_ROUTES` and `LEDGER_REQUIRE_PARTY_ACTOR` (default **true**) are both **true**, `POST /v1/capacity/{id}/lock|release` requires actor == `identity_id`; voucher **create** requires actor == `buyer_identity_id`; **verify** and **accept** require actor == `seller_identity_id` in the request body (`services/ledger_party_access.py`, `api/routes/capacity.py`, `api/routes/vouchers.py`). Path segments validated with `validate_public_url_segment`. |
| **Redis settlement index** | Stale `settlements_by_status:{status}` members after status changes. | `save()` removes the task from the **previous** status set before sadd to the new one (`db/stores/redis_settlement_store.py`). |
| **Sensitive write rate limit gaps** | POST `/v1/receipts`, `/v1/bundles`, admin, security, etc. not classified as sensitive writes. | Expanded `SENSITIVE_WRITE_PREFIXES` in `api/app.py`. |

## Configuration checklist (production)

- `APP_ENV=production`
- `APP_SECRET_KEY` — strong, non-default
- `AUTH_ENFORCE_PROTECTED_ROUTES=true`
- `AUTH_API_KEYS` — at least one mapped agent key
- `AUTH_ALLOW_DEV_KEY_FALLBACK=false`
- `RATE_LIMIT_REDIS_FAIL_CLOSED=true`
- `SETTLEMENT_REQUIRE_PARTY_ACTOR=true` (default) — keep enabled whenever auth enforcement is on
- `LEDGER_REQUIRE_PARTY_ACTOR=true` (default) — capacity + voucher party binding alongside auth enforcement
- `CORS_ALLOW_ORIGINS` — explicit origins (never `*` in production; enforced via empty default outside dev)

## Residual / out-of-scope

- **Private verification engine** and chain custody remain outside this repo; trust boundaries are documented in `docs/SYNC_PRIVATE_RUNTIME.md`.
- **Penetration testing** and **WAF / edge rate limits** are operational layers not replaced by app-level controls.

## References

- `config/settings.py` — production validator additions
- `services/settlement_party_access.py` — settlement / progress party binding helpers
- `services/ledger_party_access.py` — capacity + voucher party binding helpers
- `api/middleware/rate_limit.py` — hashed client id + fail-closed option
- `docs/SYNC_PRIVATE_RUNTIME.md` — cross-repo trust boundary
