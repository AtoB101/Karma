# Security Policy and Verification Status

## Supported Scope

This repository is intended to contain public-safe source code and documentation only.
Do not commit private business files, customer leads, investor decks, or secrets.

## Reporting a Vulnerability

If you believe you found a security issue, report it privately:

- Email: **security@karma-protocol.example**
- Subject: **[Karma Security Report] <short title>**

Please include:

1. Affected file/module and branch/commit
2. Reproduction steps
3. Impact assessment
4. Suggested mitigation (if available)

Target response windows:

- Acknowledge within 72 hours
- Initial triage decision within 7 days

## Sensitive Data Rules

- Never commit real private keys, API tokens, or production credentials.
- `.env.example` must use placeholders only.
- Internal operations material should stay in a private repository.

## Verification Baseline

Karma uses layered verification combining tests, fuzzing, static analysis, and formal verification.

Summary reference:
- `docs/SECURITY_SUMMARY_CN_EN.md`

Current baseline matrix:

| Layer | Tool | Type | Status |
|---|---|---|---|
| 1 | Forge Unit Tests | Functional correctness | 55/55 passing |
| 2 | Forge Invariant Tests | Fuzzed safety invariants | 256 rounds, 0 revert |
| 3 | Slither | Static analysis | Findings reviewed, no fund-loss critical accepted |
| 4 | Echidna | Stateful fuzz attack simulation | 100,000 rounds, 0 violation |
| 5 | Certora Prover | Formal methods proof | 6/6 rules verified |

## Bug tracking sync (non-security)

Use the repository **Issues** tab for product bugs, CI failures, and documentation fixes so they stay visible next to code and PRs.

Use the **private email channel above** only for vulnerabilities that should not be disclosed publicly before a fix ships. Do not paste production keys, customer PII, or private scoring rules into public issues.

## Agent Studio: CORS and API surface

- Default Studio HTML uses **same-origin** API calls (`connect-src 'self'` in CSP). If you point `KARMAPAY_STUDIO_API_BASE` at another host, you must also relax CSP and set `KARMAPAY_STUDIO_API_ORIGIN_ALLOWLIST` to that API origin; otherwise the client refuses cross-origin calls.
- Production JSON APIs should enforce **rate limits** at the edge (see `infra/nginx/agent-guard-rate-limit.example.conf`).

## Docker builds and secrets

- Never bake passwords or API keys into `Dockerfile` `ARG`/`ENV` literals; use runtime env or BuildKit secrets.
- `.dockerignore` excludes `.env*` and common artifacts so they are not copied into build context.

## Public tool surface (whitelist)

Reserved high-trust engine routes documented for Agent Guard are limited to: `POST /risk/check`, `POST /dispute/recommend-resolution`, `POST /score/seller` (see `apps/agent-service-guard/api/README.md`). Public adapters must not add parallel “shadow” settlement or evidence engines.

## DateTime policy (Python)

Use **timezone-aware** UTC (`datetime.now(timezone.utc)` or `datetime(..., tzinfo=timezone.utc)`). Do not use `datetime.utcnow()` in new code; it is naive and deprecated for correctness-sensitive paths.
