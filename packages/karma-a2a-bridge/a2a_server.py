from fastapi import APIRouter, HTTPException
from models import (
    AgentCard,
    A2ATaskRequest,
    A2ATaskResponse,
    A2AConfirmRequest,
    A2ASubmitRequest,
    A2ACancelRequest,
    A2AHandoffRequest,
    A2ASignedAuth,
)
from card_builder import build_agent_card
from handoff_bridge import a2a_task_to_voucher, a2a_task_to_handoff
from task_store import get_task_store
from eip712_auth import (
    OP_CANCEL,
    OP_CONFIRM,
    OP_CREATE,
    OP_HANDOFF,
    OP_SUBMIT,
    require_eip712,
    verify_a2a_task_op,
)
import config

router = APIRouter()

_agent_card: AgentCard | None = None


def set_agent_card(card: AgentCard):
    global _agent_card
    _agent_card = card


def get_agent_card() -> AgentCard:
    global _agent_card
    if _agent_card is None:
        _agent_card = build_agent_card(
            agent_id=config.AGENT_ID,
            name=config.AGENT_NAME,
            description=config.AGENT_DESCRIPTION,
            capabilities=config.AGENT_CAPABILITIES,
            endpoint=config.AGENT_ENDPOINT,
            icon_url=config.AGENT_ICON_URL,
        )
    return _agent_card


def _verify_write_auth(
    *,
    task_id: str,
    op_type: str,
    auth: A2ASignedAuth | None,
    default_requester: str = "",
    amount_micro: int | None = None,
) -> str | None:
    """Verify EIP-712 auth for write ops. Returns recovered agent address or None if disabled."""
    if not require_eip712():
        return None
    if auth is None:
        raise HTTPException(status_code=401, detail="A2A write requires EIP-712 auth")
    try:
        recovered = verify_a2a_task_op(
            signature=auth.signature,
            task_id=task_id,
            op_type=op_type,
            agent=auth.agent,
            requester_id=auth.requester_id or default_requester,
            amount_micro=amount_micro if amount_micro is not None else auth.amount_micro,
            nonce=auth.nonce,
            deadline=auth.deadline,
        )
        get_task_store().consume_nonce(recovered, auth.nonce, task_id, op_type)
        return recovered
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.get("/.well-known/agent-card.json")
async def serve_agent_card():
    return get_agent_card().model_dump()


@router.post("/a2a/task")
async def receive_task(req: A2ATaskRequest):
    card = get_agent_card()
    skill_ids = [s.id for s in card.skills]
    if card.skills and req.skill not in skill_ids:
        raise HTTPException(status_code=400, detail=f"Skill '{req.skill}' not supported. Available: {skill_ids}")

    store = get_task_store()
    if store.get(req.task_id):
        raise HTTPException(status_code=409, detail=f"Task {req.task_id} already exists")

    signer = _verify_write_auth(
        task_id=req.task_id,
        op_type=OP_CREATE,
        auth=req.auth,
        default_requester=req.requester_id or "",
    )

    state = store.append_event(
        req.task_id,
        "TaskCreated",
        {
            "task_id": req.task_id,
            "skill": req.skill,
            "params": req.params,
            "requester_id": req.requester_id,
            "status": "negotiating",
            "voucher_id": None,
            "result": None,
            "signer": signer,
        },
    )
    return A2ATaskResponse(
        task_id=req.task_id,
        status=state["status"],
        message=f"Task {req.task_id} for skill '{req.skill}' — awaiting confirmation",
    )


@router.post("/a2a/task/{task_id}/confirm")
async def confirm_task(task_id: str, body: A2AConfirmRequest = A2AConfirmRequest()):
    store = get_task_store()
    task = store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    expected_micro = int(round(float(body.amount) * 1_000_000)) if body.amount else 0
    if body.auth is not None and require_eip712() and expected_micro and body.auth.amount_micro != expected_micro:
        raise HTTPException(
            status_code=400,
            detail="auth.amount_micro must match confirm amount (USDC micro units)",
        )
    signer = _verify_write_auth(
        task_id=task_id,
        op_type=OP_CONFIRM,
        auth=body.auth,
        default_requester=task.get("requester_id") or "",
    )

    payload: dict = {
        "seller_id": body.seller_id or config.AGENT_ID,
        "amount": body.amount,
        "signer": signer,
    }
    if body.amount > 0:
        voucher = a2a_task_to_voucher(
            A2ATaskRequest(task_id=task_id, skill=task["skill"], params=task["params"]),
            seller_id=body.seller_id or config.AGENT_ID,
            amount=body.amount,
        )
        payload["voucher_id"] = voucher["voucher_id"]
        payload["voucher"] = voucher

    state = store.append_event(task_id, "TaskConfirmed", payload)
    return A2ATaskResponse(
        task_id=task_id,
        status=state["status"],
        message=f"Task {task_id} confirmed",
        voucher_id=state.get("voucher_id"),
    )


@router.post("/a2a/task/{task_id}/submit")
async def submit_task(task_id: str, body: A2ASubmitRequest = A2ASubmitRequest()):
    store = get_task_store()
    task = store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    signer = _verify_write_auth(
        task_id=task_id,
        op_type=OP_SUBMIT,
        auth=body.auth,
        default_requester=task.get("requester_id") or "",
    )
    state = store.append_event(
        task_id,
        "TaskSubmitted",
        {"result": body.result, "signer": signer},
    )
    return A2ATaskResponse(
        task_id=task_id,
        status=state["status"],
        message=f"Task {task_id} completed",
        result=body.result,
    )


@router.post("/a2a/task/{task_id}/cancel")
async def cancel_task(task_id: str, body: A2ACancelRequest = A2ACancelRequest()):
    store = get_task_store()
    task = store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    signer = _verify_write_auth(
        task_id=task_id,
        op_type=OP_CANCEL,
        auth=body.auth,
        default_requester=task.get("requester_id") or "",
    )
    state = store.append_event(
        task_id,
        "TaskCancelled",
        {"reason": body.reason, "signer": signer},
    )
    return A2ATaskResponse(
        task_id=task_id,
        status=state["status"],
        message=body.reason or f"Task {task_id} cancelled",
    )


@router.get("/a2a/task/{task_id}/status")
async def get_task_status(task_id: str):
    task = get_task_store().get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return A2ATaskResponse(
        task_id=task_id,
        status=task["status"],
        message=f"Task {task_id}: {task['status']}",
        voucher_id=task.get("voucher_id"),
        result=task.get("result"),
    )


@router.get("/a2a/task/{task_id}/events")
async def get_task_events(task_id: str):
    store = get_task_store()
    if not store.get(task_id):
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return {"task_id": task_id, "events": store.list_events(task_id)}


@router.post("/a2a/task/{task_id}/handoff")
async def get_handoff(task_id: str, body: A2AHandoffRequest = A2AHandoffRequest()):
    store = get_task_store()
    task = store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    signer = _verify_write_auth(
        task_id=task_id,
        op_type=OP_HANDOFF,
        auth=body.auth,
        default_requester=body.buyer_id or task.get("requester_id") or "",
    )
    req = A2ATaskRequest(task_id=task_id, skill=task["skill"], params=task["params"])
    handoff = a2a_task_to_handoff(
        req,
        buyer_id=body.buyer_id or task.get("requester_id", "unknown"),
        seller_id=body.seller_id or config.AGENT_ID,
    )
    handoff["signer"] = signer
    store.append_event(task_id, "HandoffGenerated", {"handoff": handoff, "signer": signer})
    return handoff
