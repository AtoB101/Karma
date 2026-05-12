# PRIVATE — Karma Runtime Operations SOP

CONFIDENTIAL. Internal use only.

---

## Runtime Architecture

```
Public API (karma-public, port 8000)
    ↓ HTTP (internal)
Private Runtime (karma-private, port 8001, 127.0.0.1 only)
    ↓
PostgreSQL (shared DB)
```

The private runtime **never** receives traffic from the public internet.
All calls come from the public API via `X-Runtime-Key` authentication.

Policy/Audit controls:
- `POLICY_VERSION` (`config/settings.py`) tags every verification note.
- Decision audit trail is append-only JSONL at `AUDIT_LOG_PATH`.
- Internal audit query endpoint: `GET /v1/audit/{task_id}?limit=50`.

---

## Decision Logic Summary

### Verification Engine (`core/verification/engine.py`)

Runs 18 checks split into 4 severity tiers:

| Tier | Checks | Failure outcome |
|------|--------|----------------|
| Critical (weight 1.0) | receipt_completeness, hash_integrity, task_id_consistency, chronological_order, contract_hash, agent_signature | → REFUND |
| High (weight 0.85–0.9) | success_rate, anti_cheat, human_timing, duplicate/missing steps | → DISPUTE |
| Medium (weight 0.65–0.7) | output_count, empty_outputs, output_diversity, ai_spam | → HOLD |
| Low (weight 0.4–0.5) | wash_trade, self_dealing, behavior_consistency | → advisory |

Weighted score thresholds (see `config/settings.py`):
- ≥ 0.80 → RELEASE
- 0.65–0.79 → HOLD
- 0.40–0.64 → DISPUTE
- Critical failure → REFUND

### Settlement (`core/settlement/state_machine.py`)

Partial split formula:
```
worker_fraction = step_ratio × (0.5 + 0.5 × confidence_weight)
```

### Arbitration (`core/arbitration/engine.py`)

Weighted composite (verification 35%, fraud 30%, behavior 15%, reputations 20%):
- ≥ 0.72 → SELLER_WINS
- < 0.35 → BUYER_WINS
- Middle → PARTIAL

### Reputation (`core/reputation/system.py`)

Key deltas (full table in `SCORE_DELTAS`):
- Success: +10 base, up to +10 bonuses
- Failure: -15 to -27
- Arbitration win: +20
- Wash trade: score zeroed

---

## Admin Override

For ops escalations where auto-arbitration fails:

```python
# Access via internal admin tool only — never via public API
from core.settlement.state_machine import PrivateSettlementStateMachine
machine = PrivateSettlementStateMachine(store)
await machine._transition(task_id, TaskStatus.RELEASED,
    arbitration_notes="Manual override by ops: [reason]")
```

**Requires:** two-person approval + audit log entry.

---

## Threshold Tuning

All thresholds live in `config/settings.py` (private) and `core/verification/engine.py`.

To adjust verification sensitivity:
1. Update `THRESHOLDS` dict in `engine.py`
2. Run private test suite: `pytest tests/ -v`
3. Deploy to staging, monitor dispute rate
4. Deploy to production

**Never** change thresholds directly in production without staging validation.

---

## Incident Response

**Spike in REFUND decisions:**
1. Check `karma_verification_decisions` Prometheus metric
2. Look for `anti_cheat_execution_time` or `hash_integrity` failures in logs
3. If false positive: raise `suspicious_speed_ms` threshold temporarily
4. File issue, schedule threshold review

**Stuck settlements (VERIFYING > 30min):**
```bash
# Find stuck tasks
SELECT task_id, status, updated_at FROM settlements
WHERE status = 'verifying' AND updated_at < NOW() - INTERVAL '30 minutes';

# Re-trigger verification via Celery
from worker.tasks import run_verification
run_verification.delay(task_id, bundle_dict, contract_dict)
```

**Private runtime unreachable:**
- Public API returns 503 to clients
- Celery verification tasks will retry 3× with 10s backoff
- Check `docker compose ps` and runtime logs
- Restart: `docker compose -f deploy/docker-compose.private.yml restart private-runtime`
