"""
Local structural stress harness for Trusted Agent Runtime (Phase 4).

No testnet RPC, no private risk scoring. Deterministic given (agents, seed, malicious_rate).
"""

from __future__ import annotations

import json
import math
import random
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from trusted_agent_runtime.evidence_adapter import EvidenceAdapter, receipt_record_hash, task_contract_hash
from trusted_agent_runtime.hashing import canonical_json_bytes, sha256_hex
from trusted_agent_runtime.receipt_store import InMemoryReceiptStore
from trusted_agent_runtime.schemas import ExecutionReceipt, TaskContract
from trusted_agent_runtime.settlement_adapter import SettlementAdapter
from trusted_agent_runtime.verification import verify_evidence_bundle_structural

BASE_UTC = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
AttackKind = Literal["none", "duplicate_id", "replay", "timeout", "malformed", "forged_chain"]


@dataclass(frozen=True)
class StressConfig:
    agents: int
    seed: int
    malicious_rate: float
    steps_min: int = 2
    steps_max: int = 5


def _iso(agent: int, step: int, sec_offset: int = 0) -> str:
    dt = BASE_UTC + timedelta(minutes=agent * 17 + step * 3, seconds=sec_offset)
    return dt.isoformat().replace("+00:00", "Z")


def _parse_iso(s: str) -> datetime:
    s2 = s[:-1] + "+00:00" if s.endswith("Z") else s
    return datetime.fromisoformat(s2)


def _percentile_95(samples: list[float]) -> float:
    if not samples:
        return 0.0
    s = sorted(samples)
    idx = min(len(s) - 1, max(0, int(math.ceil(0.95 * len(s))) - 1))
    return float(s[idx])


def _receipt_schema_errors(r: ExecutionReceipt) -> list[str]:
    errs: list[str] = []
    if r.schema_version != "karma.execution_receipt.v1":
        errs.append("bad_receipt_schema_version")
    if r.status not in ("ok", "error", "skipped"):
        errs.append("malformed_status")
    if not r.receipt_id:
        errs.append("missing_receipt_id")
    if not r.tool_name:
        errs.append("missing_tool_name")
    if r.step_index < 0:
        errs.append("negative_step_index")
    if not r.task_id or not r.agent_id or not r.runtime_id:
        errs.append("missing_identity_field")
    try:
        ts = _parse_iso(r.started_at)
        te = _parse_iso(r.ended_at)
        if te < ts:
            errs.append("timeout_order")
    except Exception:
        errs.append("malformed_timestamp")
    if r.duration_ms < 0:
        errs.append("negative_duration_ms")
    return errs


def _duplicate_extra_count(receipts: list[ExecutionReceipt]) -> int:
    """How many receipts are redundant beyond the first per receipt_id."""
    from collections import Counter

    c = Counter(r.receipt_id for r in receipts)
    return sum(max(0, n - 1) for n in c.values())


def _structural_body_hash(r: ExecutionReceipt) -> str:
    d = r.to_canonical_dict()
    del d["receipt_id"]
    return sha256_hex(canonical_json_bytes(d))


def _replay_event_count(receipts: list[ExecutionReceipt]) -> int:
    """Same execution body (excluding receipt_id), multiple receipt_ids."""
    by_h: dict[str, set[str]] = {}
    for r in receipts:
        by_h.setdefault(_structural_body_hash(r), set()).add(r.receipt_id)
    return sum(1 for ids in by_h.values() if len(ids) > 1)


def _chain_link_errors(sorted_rs: list[ExecutionReceipt]) -> list[str]:
    """Expect sorted_rs ordered by (step_index, receipt_id)."""
    errs: list[str] = []
    for i, r in enumerate(sorted_rs):
        if i == 0:
            if r.step_index == 0 and r.prev_receipt_hash not in ("",):
                errs.append("unexpected_prev_on_first_step")
            continue
        prev = sorted_rs[i - 1]
        exp = receipt_record_hash(prev)
        if r.prev_receipt_hash != exp:
            errs.append("forged_prev_hash")
    return errs


def _pick_attack(rng: random.Random) -> AttackKind:
    return rng.choice(("duplicate_id", "replay", "timeout", "malformed", "forged_chain"))


def _build_honest_receipts(agent_idx: int, seed: int, steps: int) -> tuple[TaskContract, list[ExecutionReceipt]]:
    tid = f"trace-stress-{seed}-a{agent_idx}"
    task = TaskContract(
        task_id=f"stress-{seed}-a{agent_idx}",
        agent_id=f"agent-{agent_idx}",
        runtime_id="stress-runtime",
        description="stress",
        trace_id=tid,
    )
    receipts: list[ExecutionReceipt] = []
    prev_hash = ""
    for step in range(steps):
        rid = f"r-{seed}-a{agent_idx}-s{step}"
        st = _iso(agent_idx, step)
        en = _iso(agent_idx, step, sec_offset=5 + step)
        r = ExecutionReceipt(
            receipt_id=rid,
            task_id=task.task_id,
            agent_id=task.agent_id,
            runtime_id=task.runtime_id,
            trace_id=tid,
            step_index=step,
            tool_name=f"tool_{step}",
            input_hash=sha256_hex(f"in-{seed}-{agent_idx}-{step}".encode()),
            output_hash=sha256_hex(f"out-{seed}-{agent_idx}-{step}".encode()),
            started_at=st,
            ended_at=en,
            duration_ms=100 + step * 7,
            status="ok",
            error_code="",
            evidence_refs=[],
            prev_receipt_hash=prev_hash,
        )
        receipts.append(r)
        prev_hash = receipt_record_hash(r)
    return task, receipts


def _apply_attack(receipts: list[ExecutionReceipt], attack: AttackKind, rng: random.Random) -> None:
    if attack == "none" or not receipts:
        return
    if attack == "duplicate_id":
        clone = ExecutionReceipt(**receipts[0].__dict__)
        receipts.append(clone)
    elif attack == "replay":
        r0 = receipts[0]
        replay = ExecutionReceipt(
            receipt_id=f"{r0.receipt_id}-replayclone-{rng.randrange(1 << 20)}",
            task_id=r0.task_id,
            agent_id=r0.agent_id,
            runtime_id=r0.runtime_id,
            trace_id=r0.trace_id,
            step_index=r0.step_index,
            tool_name=r0.tool_name,
            input_hash=r0.input_hash,
            output_hash=r0.output_hash,
            started_at=r0.started_at,
            ended_at=r0.ended_at,
            duration_ms=r0.duration_ms,
            status=r0.status,
            error_code=r0.error_code,
            evidence_refs=list(r0.evidence_refs),
            signer=r0.signer,
            signature=r0.signature,
            schema_version=r0.schema_version,
            prev_receipt_hash=r0.prev_receipt_hash,
        )
        receipts.append(replay)
    elif attack == "timeout":
        r = receipts[-1]
        r.started_at, r.ended_at = r.ended_at, r.started_at
    elif attack == "malformed":
        receipts[-1].status = "BAD"  # type: ignore[assignment]
    elif attack == "forged_chain" and len(receipts) > 1:
        receipts[1].prev_receipt_hash = "0x" + "de" * 32


def _sync_store(store: InMemoryReceiptStore, receipts: list[ExecutionReceipt]) -> None:
    for r in receipts:
        store.save_receipt(r)


def run_stress(cfg: StressConfig) -> dict[str, Any]:
    settlement = SettlementAdapter()
    verify_ms: list[float] = []
    failed_cases: list[dict[str, Any]] = []

    totals: dict[str, Any] = {
        "receipts_count": 0,
        "evidence_bundles_count": 0,
        "valid_receipts": 0,
        "invalid_receipts": 0,
        "replay_detected": 0,
        "duplicate_detected": 0,
        "timeout_detected": 0,
        "malformed_detected": 0,
        "forged_hash_detected": 0,
        "settlement_plan_count": 0,
    }

    proof_hashes: list[str] = []
    bundle_digests: list[str] = []
    consistency_failures = 0

    for agent_idx in range(cfg.agents):
        rng = random.Random((cfg.seed * 1_000_003 + agent_idx * 17_711) % (2**31 - 1))
        steps = rng.randint(cfg.steps_min, cfg.steps_max)
        malicious = rng.random() < cfg.malicious_rate
        attack: AttackKind = _pick_attack(rng) if malicious else "none"

        task, receipts = _build_honest_receipts(agent_idx, cfg.seed, steps)
        if attack != "none":
            _apply_attack(receipts, attack, rng)

        dup_ex = _duplicate_extra_count(receipts)
        rep_ev = _replay_event_count(receipts)
        totals["duplicate_detected"] += dup_ex
        totals["replay_detected"] += rep_ev
        if dup_ex:
            failed_cases.append({"agent_index": agent_idx, "issue": "duplicate_receipt_id", "detail": {"extra_rows": dup_ex}})
        if rep_ev:
            failed_cases.append({"agent_index": agent_idx, "issue": "replayed_receipt_hash", "detail": {"clusters": rep_ev}})

        per_receipt_schema: list[list[str]] = []
        for r in receipts:
            per_receipt_schema.append(_receipt_schema_errors(r))

        sorted_rs = sorted(receipts, key=lambda x: (x.step_index, x.receipt_id))
        link_errs = _chain_link_errors(sorted_rs)
        forged = sum(1 for e in link_errs if e == "forged_prev_hash")
        totals["forged_hash_detected"] += forged
        if link_errs:
            failed_cases.append({"agent_index": agent_idx, "issue": "chain_link", "detail": {"errors": link_errs}})

        totals["receipts_count"] += len(receipts)

        # Receipt-level valid: no schema errors, unique id (not duplicate extra row), not replay clone, chain ok for that receipt
        id_counts: dict[str, int] = {}
        for r in receipts:
            id_counts[r.receipt_id] = id_counts.get(r.receipt_id, 0) + 1
        h_counts: dict[str, set[str]] = {}
        for r in receipts:
            h_counts.setdefault(_structural_body_hash(r), set()).add(r.receipt_id)

        for errs in per_receipt_schema:
            for e in errs:
                if e == "timeout_order":
                    totals["timeout_detected"] += 1
                else:
                    totals["malformed_detected"] += 1

        for i, r in enumerate(receipts):
            errs = list(per_receipt_schema[i])
            if id_counts[r.receipt_id] > 1:
                errs.append("duplicate_id")
            if len(h_counts[_structural_body_hash(r)]) > 1:
                errs.append("replay_hash")
            pos = next(j for j, x in enumerate(sorted_rs) if x is r)
            if pos == 0:
                if r.step_index == 0 and r.prev_receipt_hash not in ("",):
                    errs.append("bad_first_prev")
            else:
                prev = sorted_rs[pos - 1]
                if r.prev_receipt_hash != receipt_record_hash(prev):
                    errs.append("forged_prev")
            if errs:
                totals["invalid_receipts"] += 1
            else:
                totals["valid_receipts"] += 1

        agent_ok = dup_ex == 0 and rep_ev == 0 and forged == 0 and all(len(x) == 0 for x in per_receipt_schema) and not link_errs

        if agent_ok:
            store = InMemoryReceiptStore()
            _sync_store(store, sorted_rs)
            adapter = EvidenceAdapter(store)
            ids = [r.receipt_id for r in sorted_rs]
            bundle = adapter.build_evidence_bundle(
                task,
                ids,
                bundle_id=f"b-{cfg.seed}-a{agent_idx}",
                created_at=_iso(agent_idx, 99),
            )
            ph1 = adapter.map_to_karma_proof_hash(bundle)
            ph2 = adapter.map_to_karma_proof_hash(bundle)
            d1 = adapter.hash_evidence_bundle(bundle)
            d2 = adapter.hash_evidence_bundle(bundle)
            if ph1 != ph2 or d1 != d2:
                consistency_failures += 1
                failed_cases.append(
                    {"agent_index": agent_idx, "issue": "hash_consistency", "detail": {"proof_mismatch": ph1 != ph2, "digest_mismatch": d1 != d2}}
                )
            else:
                proof_hashes.append(ph1)
                bundle_digests.append(d1)

            t0 = time.perf_counter()
            verify = verify_evidence_bundle_structural(task, bundle, store)
            verify_ms.append((time.perf_counter() - t0) * 1000.0)

            if verify.decision != "STRUCT_OK":
                failed_cases.append({"agent_index": agent_idx, "issue": "verify_fail", "detail": dict(verify.__dict__)})
            else:
                totals["evidence_bundles_count"] += 1
                scope_hex = "0x" + task_contract_hash(task)
                plan = settlement.build_offchain_plan(
                    task,
                    bundle,
                    ph1,
                    scope_hex,
                    seller="0x000000000000000000000000000000000000dEaD",
                    token="0x000000000000000000000000000000000000c0ffee",
                    amount_wei=1_000_000,
                    deadline_unix=2_000_000_000,
                    verify=verify,
                )
                dumped = json.dumps(plan, sort_keys=True)
                fp1 = sha256_hex(dumped.encode())
                fp2 = sha256_hex(json.dumps(json.loads(dumped), sort_keys=True).encode())
                if fp1 != fp2:
                    consistency_failures += 1
                    failed_cases.append({"agent_index": agent_idx, "issue": "settlement_plan_inconsistent", "detail": {}})
                else:
                    totals["settlement_plan_count"] += 1

    avg_ms = sum(verify_ms) / len(verify_ms) if verify_ms else 0.0
    p95_ms = _percentile_95(verify_ms)

    fingerprint_material = "|".join(sorted(proof_hashes) + sorted(bundle_digests))
    global_fingerprint = sha256_hex(fingerprint_material.encode())

    return {
        "config": {"agents": cfg.agents, "seed": cfg.seed, "malicious_rate": cfg.malicious_rate},
        "receipts_count": totals["receipts_count"],
        "evidence_bundles_count": totals["evidence_bundles_count"],
        "valid_receipts": totals["valid_receipts"],
        "invalid_receipts": totals["invalid_receipts"],
        "replay_detected": totals["replay_detected"],
        "duplicate_detected": totals["duplicate_detected"],
        "timeout_detected": totals["timeout_detected"],
        "malformed_detected": totals["malformed_detected"],
        "forged_hash_detected": totals["forged_hash_detected"],
        "settlement_plan_count": totals["settlement_plan_count"],
        "average_verification_ms": round(avg_ms, 6),
        "p95_verification_ms": round(p95_ms, 6),
        "failed_cases": failed_cases,
        "structural_consistency_failures": consistency_failures,
        "global_receipt_chain_fingerprint": global_fingerprint,
    }

