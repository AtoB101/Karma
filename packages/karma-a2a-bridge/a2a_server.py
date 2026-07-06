import time
import uuid
from fastapi import APIRouter, HTTPException
from models import AgentCard, A2ATaskRequest, A2ATaskResponse
from card_builder import build_agent_card
from handoff_bridge import a2a_task_to_voucher, a2a_task_to_handoff
import config

router = APIRouter()

_agent_card: AgentCard | None = None
_task_store: dict[str, dict] = {}


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


@router.get("/.well-known/agent-card.json")
async def serve_agent_card():
    return get_agent_card().model_dump()


@router.post("/a2a/task")
async def receive_task(req: A2ATaskRequest):
    card = get_agent_card()
    skill_ids = [s.id for s in card.skills]
    if card.skills and req.skill not in skill_ids:
        raise HTTPException(status_code=400, detail=f"Skill '{req.skill}' not supported. Available: {skill_ids}")
    _task_store[req.task_id] = {
        "task_id": req.task_id,
        "skill": req.skill,
        "params": req.params,
        "requester_id": req.requester_id,
        "status": "negotiating",
        "created_at": int(time.time()),
        "updated_at": int(time.time()),
        "result": None,
        "voucher_id": None,
    }
    return A2ATaskResponse(
        task_id=req.task_id,
        status="negotiating",
        message=f"Task {req.task_id} for skill '{req.skill}' — awaiting confirmation",
    )


@router.post("/a2a/task/{task_id}/confirm")
async def confirm_task(task_id: str, seller_id: str = "", amount: float = 0.0):
    task = _task_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    task["status"] = "accepted"
    task["updated_at"] = int(time.time())
    if amount > 0:
        voucher = a2a_task_to_voucher(
            A2ATaskRequest(task_id=task_id, skill=task["skill"], params=task["params"]),
            seller_id=seller_id or config.AGENT_ID,
            amount=amount,
        )
        task["voucher_id"] = voucher["voucher_id"]
        task["voucher"] = voucher
    return A2ATaskResponse(
        task_id=task_id,
        status="accepted",
        message=f"Task {task_id} confirmed",
        voucher_id=task.get("voucher_id"),
    )


@router.post("/a2a/task/{task_id}/submit")
async def submit_task(task_id: str, result: dict = {}):
    task = _task_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    task["status"] = "completed"
    task["result"] = result
    task["updated_at"] = int(time.time())
    return A2ATaskResponse(
        task_id=task_id,
        status="completed",
        message=f"Task {task_id} completed",
        result=result,
    )


@router.post("/a2a/task/{task_id}/cancel")
async def cancel_task(task_id: str, reason: str = ""):
    task = _task_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    task["status"] = "cancelled"
    task["reason"] = reason
    task["updated_at"] = int(time.time())
    return A2ATaskResponse(
        task_id=task_id,
        status="cancelled",
        message=reason or f"Task {task_id} cancelled",
    )


@router.get("/a2a/task/{task_id}/status")
async def get_task_status(task_id: str):
    task = _task_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return A2ATaskResponse(
        task_id=task_id,
        status=task["status"],
        message=f"Task {task_id}: {task['status']}",
        voucher_id=task.get("voucher_id"),
        result=task.get("result"),
    )


@router.post("/a2a/task/{task_id}/handoff")
async def get_handoff(task_id: str, buyer_id: str = "", seller_id: str = ""):
    task = _task_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    req = A2ATaskRequest(task_id=task_id, skill=task["skill"], params=task["params"])
    handoff = a2a_task_to_handoff(
        req,
        buyer_id=buyer_id or task.get("requester_id", "unknown"),
        seller_id=seller_id or config.AGENT_ID,
    )
    return handoff
