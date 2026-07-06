import time
import hashlib
from models import A2ATaskRequest


def _make_id(prefix: str = "a2a") -> str:
    raw = f"{prefix}_{time.time_ns()}"
    return f"{prefix}_{hashlib.sha256(raw.encode()).hexdigest()[:12]}"


def a2a_task_to_voucher(
    task: A2ATaskRequest,
    seller_id: str,
    amount: float,
    currency: str = "USDC",
    buyer_id: str = "",
) -> dict:
    voucher_id = _make_id("a2a")
    return {
        "voucher_id": voucher_id,
        "buyer_id": buyer_id or task.requester_id or "unknown",
        "seller_id": seller_id,
        "amount": amount,
        "currency": currency,
        "skill": task.skill,
        "params": task.params,
        "metadata": {
            "source": "a2a_bridge",
            "task_id": task.task_id,
            "created_at": int(time.time()),
        },
    }


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
        "created_at": int(time.time()),
    }


def evidence_chain(task_ids: list[str]) -> dict:
    return {
        "chain_id": _make_id("evc"),
        "task_ids": task_ids,
        "agent_count": len(task_ids),
        "status": "pending",
    }
