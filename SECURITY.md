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
