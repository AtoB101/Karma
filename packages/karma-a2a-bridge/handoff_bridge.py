import hashlib
import os
import time
import uuid
from datetime import datetime, timedelta

import httpx

from models import A2ATaskRequest
import config


def _make_id(prefix: str = "a2a") -> str:
    raw = f"{prefix}_{time.time_ns()}"
    return f"{prefix}_{hashlib.sha256(raw.encode()).hexdigest()[:12]}"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def a2a_task_to_voucher(
    task: A2ATaskRequest,
    seller_id: str,
    amount: float,
    currency: str = "USDC",
    buyer_id: str = "",
    *,
    publish_to_karma: bool | None = None,
) -> dict:
    """
    Build voucher payload from A2A negotiation.

    When KARMA_API_BASE + KARMA_API_KEY are set (or publish_to_karma=True), attempt
    POST /v1/vouchers so discovery→negotiate hands off into real Karma settlement.
    Falls back to a local stub voucher if the API is unavailable or rejects (e.g. EIP-712).
    """
    buyer = buyer_id or task.requester_id or "unknown"
    local = {
        "voucher_id": _make_id("a2a"),
        "buyer_id": buyer,
        "seller_id": seller_id,
        "amount": amount,
        "currency": currency,
        "skill": task.skill,
        "params": task.params,
        "metadata": {
            "source": "a2a_bridge",
            "task_id": task.task_id,
            "created_at": int(time.time()),
            "published": False,
        },
    }

    should_publish = publish_to_karma
    if should_publish is None:
        should_publish = bool(config.KARMA_API_KEY) and os.getenv("A2A_PUBLISH_VOUCHER", "1") not in {
            "0",
            "false",
            "no",
        }

    if not should_publish or amount <= 0:
        return local

    published = _try_publish_voucher(
        buyer_id=buyer,
        seller_id=seller_id,
        amount=amount,
        currency=currency,
        task=task,
    )
    if published:
        local["voucher_id"] = published.get("voucher_id") or local["voucher_id"]
        local["metadata"]["published"] = True
        local["metadata"]["karma_voucher"] = published
    else:
        local["metadata"]["publish_attempted"] = True
        local["metadata"]["publish_fallback"] = "local_stub"
    return local


def _try_publish_voucher(
    *,
    buyer_id: str,
    seller_id: str,
    amount: float,
    currency: str,
    task: A2ATaskRequest,
) -> dict | None:
    desc = f"{task.skill}:{task.task_id}:{task.params}"
    body = {
        "buyer_identity_id": buyer_id,
        "seller_identity_id": seller_id,
        "amount": float(amount),
        "currency": currency,
        "bill_credit_amount": float(amount),
        "task_type": f"a2a.{task.skill}",
        "task_description_hash": _sha256_text(desc),
        "progress_rule_hash": _sha256_text("a2a_progress_v1"),
        "evidence_requirement_hash": _sha256_text("a2a_evidence_v1"),
        "expiry_time": (datetime.utcnow() + timedelta(days=7)).isoformat() + "Z",
        "nonce": f"a2a-{task.task_id}-{uuid.uuid4().hex[:8]}",
        # Dev/test signature placeholder — production enforces real EIP-712 via VOUCHER_REQUIRE_EIP712
        "buyer_signature": os.getenv("A2A_VOUCHER_BUYER_SIGNATURE", "0xa2a_bridge_negotiated"),
    }
    headers = {"Content-Type": "application/json"}
    if config.KARMA_API_KEY:
        headers["Authorization"] = f"Bearer {config.KARMA_API_KEY}"
        headers["X-API-Key"] = config.KARMA_API_KEY

    try:
        resp = httpx.post(
            f"{config.KARMA_API_BASE.rstrip('/')}/v1/vouchers",
            json=body,
            headers=headers,
            timeout=15,
        )
        if resp.is_success:
            data = resp.json()
            return data if isinstance(data, dict) else {"raw": data}
        return None
    except httpx.HTTPError:
        return None


def a2a_task_to_handoff(
    task: A2ATaskRequest,
    buyer_id: str,
    seller_id: str,
) -> dict:
    return {
        "trace_id": task.task_id,
        "task_id": task.task_id,
        "buyer_identity_id": buyer_id,
        "seller_identity_id": seller_id,
        "voucher_id": _make_id("vcr"),
        "skill": task.skill,
        "params": task.params,
        "authorization": {
            "manual_console_steps_completed": True,
            "a2a_negotiated": True,
        },
        "settlement_hint": {
            "karma_api_base": config.KARMA_API_BASE,
            "next": ["accept_voucher", "submit_evidence", "settle"],
        },
        "created_at": int(time.time()),
    }


def evidence_chain(task_ids: list[str]) -> dict:
    return {
        "chain_id": _make_id("evc"),
        "task_ids": task_ids,
        "agent_count": len(task_ids),
        "status": "pending",
    }
