# Security Policy and Verification Status

## Supported Scope

This repository is intended to contain public-safe source code and documentation only.
Do not commit private business files, customer leads, investor decks, or secrets.

## Reporting a Vulnerability

If you believe you found a security issue, report it **privately** so it can be fixed before public disclosure.

**Preferred channel:** use [GitHub private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing/privately-reporting-a-security-vulnerability) for this repository (open the **Security** tab, then **Report a vulnerability**). That keeps the report scoped to maintainers and coordinates disclosure with a fix.

If that workflow is unavailable for your account, contact the repository maintainers through a channel they publish for security (for example a `security.txt` or organization security page). **Do not** open a public issue for unfixed vulnerabilities that affect funds, authentication, or the private verification runtime.

Please include:

1. Affected file/module and branch/commit
2. Reproduction steps
3. Impact assessment
4. Suggested mitigation (if available)

Target response windows (best effort, not a legal commitment):

- Acknowledge within 72 hours
- Initial triage decision within 7 days

### Bug bounty

There is **no** formal paid bug bounty program in this repository today. Responsible disclosure is still welcome; recognition is at maintainer discretion.

## Verify proxy and evidence bundles (DoS surface)

`POST /v1/verify` forwards JSON to the **private runtime** for fraud and risk checks. That boundary is a natural DoS target (oversized payloads, huge receipt lists). The public API applies configurable limits before persistence and forwarding:

| Setting (environment) | Role |
| --- | --- |
| `EVIDENCE_BUNDLE_MAX_JSON_BYTES` | Max serialized JSON size for `POST /v1/bundles` |
| `VERIFY_MAX_COMBINED_JSON_BYTES` | Max serialized JSON for the `{bundle, contract}` body on `POST /v1/verify` |
| `EVIDENCE_BUNDLE_MAX_RECEIPT_ENTRIES` | Max length of `receipt_ids` / `receipt_hashes` (must match) |

Defaults are conservative (on the order of a few MiB and a few thousand receipts). Tune them for your deployment, and still enforce **rate limits** and resource quotas at the edge and on the private runtime (see `infra/nginx/` examples and your orchestrator limits).

Further review notes: `docs/SECURITY_SUMMARY_CN_EN.md` and historical audit notes under `docs/`.

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

Use the **private reporting channel above** only for vulnerabilities that should not be disclosed publicly before a fix ships. Do not paste production keys, customer PII, or private scoring rules into public issues.

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
