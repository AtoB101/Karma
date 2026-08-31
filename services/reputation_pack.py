"""Off-chain reputation eligibility: pack on-chain after clean history or 90-day rehab."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from config.settings import settings

KIND_DISPUTE = "dispute"
KIND_DEFAULT = "default"
KIND_FRAUD = "fraud"
KIND_WASH = "wash"


def _now() -> datetime:
    return datetime.utcnow()


def score_to_e2(score: float) -> int:
    return int(round(float(score) * 100))


def evidence_hash(
    *,
    agent_id: str,
    score: float,
    successful_tasks: int,
    disputed_tasks: int,
    last_incident_at: datetime | None,
    last_incident_kind: str | None,
) -> str:
    payload = {
        "agent_id": agent_id,
        "score": round(float(score), 6),
        "successful_tasks": int(successful_tasks),
        "disputed_tasks": int(disputed_tasks),
        "last_incident_at": last_incident_at.isoformat() if last_incident_at else None,
        "last_incident_kind": last_incident_kind,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "0x" + hashlib.sha256(raw).hexdigest()


@dataclass
class PackEligibility:
    eligible: bool
    path: str | None
    reasons: list[str]
    score: float
    min_score: float
    min_successes: int
    rehab_days: int
    dividend_eligible_offchain: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "eligible": self.eligible,
            "path": self.path,
            "reasons": self.reasons,
            "score": self.score,
            "min_score": self.min_score,
            "min_successes": self.min_successes,
            "rehab_days": self.rehab_days,
            "dividend_eligible_offchain": self.dividend_eligible_offchain,
            "note_zh": (
                "上链是信誉资产锚定，不减免 Bilateral 手续费；"
                "达标后可获平台分红权重与其它非手续费奖励。"
            ),
        }


def evaluate_pack_eligibility(
    *,
    score: float,
    successful_tasks: int,
    disputed_tasks: int,
    last_incident_at: datetime | None,
    last_incident_kind: str | None = None,
    wash_trade_flags: int = 0,
    now: datetime | None = None,
) -> PackEligibility:
    min_score = float(settings.reputation_pack_min_score)
    min_ok = int(settings.reputation_pack_min_successes)
    rehab_days = int(settings.reputation_rehab_days)
    div_min = float(settings.reputation_dividend_min_score)
    wash_block_at = int(settings.reputation_wash_flag_pack_block)
    now = now or _now()
    reasons: list[str] = []
    path: str | None = None

    if score < min_score:
        reasons.append(f"score_below_{min_score}")
    if successful_tasks < min_ok:
        reasons.append(f"successes_below_{min_ok}")

    incident = last_incident_at
    if incident is not None and incident.tzinfo is not None:
        incident = incident.replace(tzinfo=None)

    clean_rehab = False
    if incident is None:
        clean_rehab = True
    else:
        elapsed = now - incident
        if elapsed >= timedelta(days=rehab_days):
            clean_rehab = True
        else:
            reasons.append(
                f"incident_{last_incident_kind or 'open'}_within_{rehab_days}d"
            )

    flags = int(wash_trade_flags or 0)
    wash_ok = True
    if flags >= wash_block_at:
        if clean_rehab and incident is not None:
            wash_ok = True
        else:
            wash_ok = False
            reasons.append(f"wash_flags_{flags}")

    eligible = score >= min_score and successful_tasks >= min_ok and clean_rehab and wash_ok
    if eligible:
        if incident is None and disputed_tasks == 0:
            path = "undisputed"
        elif incident is None:
            path = "clean_history"
        else:
            path = "rehab_90d"

    dividend = eligible and score >= div_min
    return PackEligibility(
        eligible=eligible,
        path=path,
        reasons=reasons,
        score=float(score),
        min_score=min_score,
        min_successes=min_ok,
        rehab_days=rehab_days,
        dividend_eligible_offchain=dividend,
    )


def dividend_points_for_pack(score: float) -> float:
    if score < float(settings.reputation_dividend_min_score):
        return 0.0
    return round(float(score), 4)
