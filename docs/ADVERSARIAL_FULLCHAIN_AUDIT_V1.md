# Adversarial Full-Chain Audit V1

Generated: `2026-08-01T20:08:13Z`

## Verdict

**HARD PASS** — static audit + adversarial + plate units + nonce stress green.

## Scope

Attack posture: overthrow the commerce loop (P1–P8) via crypto splice, collusion,
gate bypass, race/replay, silent-TTL abuse, discovery demote evasion, settlement
privacy scrape, and production soft-path (`auto_complete` / omitted `scene_id`).

## Suite results

| Suite | OK | Seconds |
|-------|----|---------|
| reverse_rule_audit (static P1–P8) | PASS | 0.03 |
| adversarial_p1_p8 (crypto/collusion/bypass/race/privacy) | PASS | 2.0 |
| plate_unit_pack P1–P8 | PASS | 2.88 |
| stress_nonce_races (25×8) | PASS | 0.29 |

## Hardenings applied this pass

1. `buyer-accept` P4 gate uses settlement scene hint — omitting `scene_id` no longer bypasses OWNER_CONFIRM.
2. `auto_complete=true` refused outside development/test (`auto_complete_forbidden`).
3. P8 attestation disk store strips plaintext party ids / amount (ciphertext-only persist).
4. P8 scene reputation ledger keyed by `agent_commitment` (no raw agent_id on disk).
5. Public reputation omits raw `agent_id` by default (`include_agent_id` opt-in).
6. `/settlement-reputation/.../decrypt` and `/attestations/seal` always require auth.
7. Important-fields `session-key` + `encrypt` helpers always require auth.

## Residual risk (honest)

- Demo env still allows `auto_complete` / `auto_lock` (test/local only).
- Agent-id rotation to reset non-confirm ledger is not yet owner-bound inheritance.
- Decrypt auth proves actor identity but does not yet bind role keys to party membership.
- Multi-instance race safety still depends on single-process locks / local JSON ledgers.

## Fail detail

_none_

## Machine summary

```json
{
  "generated_at": "2026-08-01T20:08:13Z",
  "hard_pass": true,
  "suites": [
    {
      "label": "reverse_rule_audit (static P1\u2013P8)",
      "ok": true,
      "elapsed_s": 0.03,
      "returncode": 0
    },
    {
      "label": "adversarial_p1_p8 (crypto/collusion/bypass/race/privacy)",
      "ok": true,
      "elapsed_s": 2.0,
      "returncode": 0
    },
    {
      "label": "plate_unit_pack P1\u2013P8",
      "ok": true,
      "elapsed_s": 2.88,
      "returncode": 0
    },
    {
      "label": "stress_nonce_races (25\u00d78)",
      "ok": true,
      "elapsed_s": 0.29,
      "returncode": 0
    }
  ]
}
```

