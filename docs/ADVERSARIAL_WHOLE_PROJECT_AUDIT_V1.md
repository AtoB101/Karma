# Adversarial Whole-Project Audit V1

Generated: `2026-08-02T20:51:26Z`

## Verdict

**HARD PASS** — whole-project static + WP adversarial + platform security packs green.

## Scope (entire repo, not only P1–P8)

Surfaces covered:

- Auth / JWT / API keys / admin whitelist / security always-auth
- Receipts, settlement cycle guards, capacity release, runtime keys/spend
- x402 URL SSRF + budget, AP2 adapter surface, OpenClaw webhook signing
- Path traversal, NUL/RLO injection, CORS default, production secret validator
- Router mount integrity (security/admin/settlement/receipts/x402/trade/runtime/…)
- Commerce plates P1–P8 adversarial pack (included as a subset)
- Public security baseline / proof gates / reverse-rule audit
- Trusted-agent structural stress

## Suite results

| Suite | OK | Seconds |
|-------|----|---------|
| A1 security-baseline-guard | PASS | 0.06 |
| A2 ci-proof-gates | PASS | 0.11 |
| A4 reverse_rule_audit | PASS | 0.03 |
| B1 adversarial_whole_project (WP-*) | PASS | 2.3 |
| B2 platform KSA/KSA2/TL/X402/AP2/runtime packs | PASS | 2.93 |
| C1 adversarial_p1_p8 (commerce plates) | PASS | 1.98 |
| D1 stress_evidence_runtime --agents 30 | PASS | 0.07 |
| E1 full_chain_audit_gate (off-chain) | PASS | 26.71 |

## How to re-run

```bash
python3 scripts/acceptance/adversarial_whole_project_suite.py
# faster: KARMA_WHOLE_PROJECT_SKIP_FULL_GATE=1 python3 scripts/acceptance/adversarial_whole_project_suite.py
# live:   KARMA_LIVE_ADVERSARIAL=1 KARMA_RUNTIME_URL=http://127.0.0.1:8000 \
#         python3 scripts/acceptance/adversarial_whole_project_suite.py
```

## Residual risk (honest)

- Live `attack_simulation.py` / `attack_lv2.py` / high-concurrency HTTP stress require a running API (optional here).
- On-chain Sepolia / forge formal proofs are covered by separate CI (`security-ci`, `forge-ci`), not this offline suite.
- Multi-instance Redis/DB races and DNS-rebinding SSRF need staging soak.
- Demo env soft-paths (`auto_complete`, auth enforce off) remain for local loops.

## Fail detail

_none_

## Machine summary

```json
{
  "generated_at": "2026-08-02T20:51:26Z",
  "hard_pass": true,
  "scope": "whole_project",
  "suites": [
    {
      "label": "A1 security-baseline-guard",
      "ok": true,
      "elapsed_s": 0.06,
      "returncode": 0
    },
    {
      "label": "A2 ci-proof-gates",
      "ok": true,
      "elapsed_s": 0.11,
      "returncode": 0
    },
    {
      "label": "A4 reverse_rule_audit",
      "ok": true,
      "elapsed_s": 0.03,
      "returncode": 0
    },
    {
      "label": "B1 adversarial_whole_project (WP-*)",
      "ok": true,
      "elapsed_s": 2.3,
      "returncode": 0
    },
    {
      "label": "B2 platform KSA/KSA2/TL/X402/AP2/runtime packs",
      "ok": true,
      "elapsed_s": 2.93,
      "returncode": 0
    },
    {
      "label": "C1 adversarial_p1_p8 (commerce plates)",
      "ok": true,
      "elapsed_s": 1.98,
      "returncode": 0
    },
    {
      "label": "D1 stress_evidence_runtime --agents 30",
      "ok": true,
      "elapsed_s": 0.07,
      "returncode": 0
    },
    {
      "label": "E1 full_chain_audit_gate (off-chain)",
      "ok": true,
      "elapsed_s": 26.71,
      "returncode": 0
    }
  ]
}
```

