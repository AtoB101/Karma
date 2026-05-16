"""Buyer requirement → structured task spec (rule-based agent decomposition MVP)."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta
from typing import Any


def decompose_buyer_requirement(
    *,
    requirement_text: str,
    seller_identity_id: str,
    buyer_identity_id: str,
    amount: float | None = None,
    task_precision: float | None = None,
    task_type: str | None = None,
    currency: str = "USDC",
) -> dict[str, Any]:
    """
    Produce a task spec from natural language + optional structured overrides.

    Future: plug LLM agent here; output shape remains stable for the pipeline.
    """
    text = (requirement_text or "").strip()
    if not text:
        raise ValueError("requirement_text is required")

    parsed_amount = amount
    if parsed_amount is None:
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:USDC|u|元|美元)?", text, re.I)
        parsed_amount = float(m.group(1)) if m else 10.0

    parsed_precision = task_precision
    if parsed_precision is None:
        m = re.search(r"(?:精度|precision)[^\d]*(\d+(?:\.\d+)?)", text, re.I)
        parsed_precision = float(m.group(1)) if m else 1.0

    parsed_type = (task_type or "").strip()
    if not parsed_type:
        if re.search(r"caption|字幕|视频", text, re.I):
            parsed_type = "api.caption"
        elif re.search(r"translat|翻译", text, re.I):
            parsed_type = "api.translate"
        elif re.search(r"label|标注", text, re.I):
            parsed_type = "api.labeling"
        else:
            parsed_type = "api.generic"

    steps = _extract_steps(text)
    title = text.split("\n")[0][:120] if text else "Karma trade order"
    task_id = str(uuid.uuid4())

    spec = {
        "task_id": task_id,
        "buyer_identity_id": buyer_identity_id,
        "seller_identity_id": seller_identity_id,
        "title": title,
        "description": text[:8000],
        "amount": float(parsed_amount),
        "bill_credit_amount": float(parsed_amount),
        "currency": currency,
        "task_type": parsed_type,
        "task_precision": float(parsed_precision),
        "expected_step_count": max(len(steps), 1),
        "agent_steps": steps,
        "deadline_at": (datetime.utcnow() + timedelta(days=7)).isoformat() + "Z",
        "expected_output_schema": {
            "type": "object",
            "properties": {
                "deliverable_hash": {"type": "string"},
                "summary": {"type": "string"},
            },
            "required": ["deliverable_hash"],
        },
        "decomposition_version": "rule_v1",
        "requirement_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }
    return spec


def _extract_steps(text: str) -> list[dict[str, Any]]:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    steps: list[dict[str, Any]] = []
    for i, ln in enumerate(lines):
        if re.match(r"^(\d+[\.\)、]|[-*])\s*", ln):
            steps.append({"index": len(steps), "action": re.sub(r"^(\d+[\.\)、]|[-*])\s*", "", ln)})
    if not steps:
        steps = [
            {"index": 0, "action": "parse_requirement", "detail": lines[0] if lines else "execute"},
            {"index": 1, "action": "deliver", "detail": "submit evidence and progress"},
        ]
    return steps
