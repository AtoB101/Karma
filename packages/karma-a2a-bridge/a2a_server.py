from fastapi import APIRouter, HTTPException
from models import AgentCard, A2ATaskRequest, A2ATaskResponse
from card_builder import build_agent_card
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


@router.get("/.well-known/agent-card.json")
async def serve_agent_card():
    return get_agent_card().model_dump()


@router.post("/a2a/task")
async def receive_task(req: A2ATaskRequest):
    card = get_agent_card()
    skill_ids = [s.id for s in card.skills]
    if req.skill not in skill_ids:
        raise HTTPException(status_code=400, detail=f"Skill '{req.skill}' not supported. Available: {skill_ids}")
    return A2ATaskResponse(
        task_id=req.task_id,
        status="accepted",
        message=f"Task {req.task_id} accepted for skill '{req.skill}'",
    )


@router.get("/a2a/task/{task_id}/status")
async def get_task_status(task_id: str):
    return A2ATaskResponse(
        task_id=task_id,
        status="negotiating",
        message="Task status placeholder",
    )
