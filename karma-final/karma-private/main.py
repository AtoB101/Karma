"""
PRIVATE — Karma Runtime Entry Point
Full private runtime with all decision engines wired up.
DO NOT commit to public repository.
"""
from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.security import APIKeyHeader
from fastapi import Security
from pydantic import BaseModel

from config.settings import settings
from core.schemas import (
    AgentRole, EvidenceBundle, ReputationSnapshot,
    SettlementState, TaskContract, TaskStatus, VerificationResult,
)
from core.verification.engine import PrivateVerificationEngine
from core.settlement.state_machine import PrivateSettlementStateMachine
from core.reputation.system import PrivateReputationSystem
from core.risk.scorer import RiskScorer
from core.fraud.detector import FraudDetector
from core.behavior.analyzer import BehaviorAnalyzer
from core.arbitration.engine import ArbitrationEngine

logger = structlog.get_logger(__name__)

# Internal API key guard
runtime_key_header = APIKeyHeader(name="X-Runtime-Key", auto_error=True)


def _verify_runtime_key(key: str = Security(runtime_key_header)) -> str:
    if key != settings.runtime_api_key:
        raise HTTPException(status_code=403, detail="Invalid runtime key")
    return key


# ---------------------------------------------------------------------------
# Dependency wiring
# ---------------------------------------------------------------------------

async def _get_db_session():
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    engine = create_async_engine(settings.database_url, pool_size=settings.database_pool_size)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as session:
        yield session


async def get_engines():
    """Build all private engines with real DB stores."""
    from db.stores.private_stores import (
        get_receipt_store, get_settlement_store,
        get_reputation_store, get_signing_service,
    )
    return {
        "verifier":   PrivateVerificationEngine(
            signing_service=get_signing_service(),
            receipt_store=get_receipt_store(),
        ),
        "settler":    PrivateSettlementStateMachine(store=get_settlement_store()),
        "reputation": PrivateReputationSystem(store=get_reputation_store()),
        "risk":       RiskScorer(),
        "fraud":      FraudDetector(),
        "behavior":   BehaviorAnalyzer(),
        "arbitration":ArbitrationEngine(),
    }


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("karma_private_runtime_starting", host=settings.runtime_host, port=settings.runtime_port)
    yield
    logger.info("karma_private_runtime_shutdown")


app = FastAPI(
    title="Karma Private Runtime",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,   # completely hidden
)


@app.middleware("http")
async def log_middleware(request: Request, call_next) -> Response:
    rid = str(uuid.uuid4())[:8]
    t = time.perf_counter()
    resp = await call_next(request)
    logger.info("runtime_request",
                rid=rid, path=request.url.path,
                status=resp.status_code,
                ms=round((time.perf_counter() - t) * 1000))
    return resp


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

class VerifyRequest(BaseModel):
    bundle: EvidenceBundle
    contract: TaskContract


@app.post("/v1/verify", response_model=VerificationResult)
async def verify(body: VerifyRequest, _key: str = Security(_verify_runtime_key)):
    engines = await get_engines()

    # 1. Risk assessment (pre-check)
    risk = engines["risk"].assess(body.contract, None, None)
    if risk.should_block:
        logger.warning("risk_block_verification", task_id=body.bundle.task_id, score=risk.composite_score)
        raise HTTPException(422, f"Task blocked by risk engine: {risk.notes}")

    # 2. Fraud detection
    receipts = await engines["verifier"].receipt_store.list_by_task(body.bundle.task_id)
    fraud_report = engines["fraud"].detect(body.bundle, body.contract, receipts)
    if fraud_report.recommended_action == "block":
        logger.warning("fraud_block_verification", task_id=body.bundle.task_id)
        raise HTTPException(422, f"Task blocked by fraud engine: {fraud_report.signals[0].signal_type if fraud_report.signals else 'fraud'}")

    # 3. Behavior analysis
    behavior = engines["behavior"].analyze(
        body.bundle.task_id,
        body.contract.worker_agent_id or "unknown",
        receipts,
    )

    # 4. Full verification
    result = await engines["verifier"].verify(body.bundle, body.contract)

    logger.info("verification_complete",
                task_id=body.bundle.task_id,
                decision=result.decision,
                confidence=result.confidence,
                fraud_clean=not fraud_report.is_fraudulent,
                behavior_score=behavior.behavior_score)
    return result


class ApplyVerificationRequest(BaseModel):
    result: VerificationResult


@app.post("/v1/settlement/{task_id}/apply-verification", response_model=SettlementState)
async def apply_verification(
    task_id: str,
    body: ApplyVerificationRequest,
    _key: str = Security(_verify_runtime_key),
):
    engines = await get_engines()
    state = await engines["settler"].apply_verification(task_id, body.result)

    # Trigger reputation update for both parties
    from core.schemas import TaskStatus as TS
    terminal = {TS.RELEASED, TS.REFUNDED, TS.BUYER_WINS, TS.SELLER_WINS, TS.PARTIAL}
    if state.status in terminal and state.worker_agent_id:
        for agent_id, role in [
            (state.worker_agent_id, AgentRole.WORKER),
            (state.client_agent_id, AgentRole.CLIENT),
        ]:
            await engines["reputation"].update(
                agent_id=agent_id,
                role=role,
                final_status=state.status,
                verification_confidence=body.result.confidence,
                all_checks_passed=all(c.passed for c in body.result.checks),
            )

    return state


class ReputationUpdateRequest(BaseModel):
    agent_id: str
    role: AgentRole
    final_status: TaskStatus
    verification_confidence: float | None = None
    total_duration_ms: int | None = None
    all_checks_passed: bool = False
    is_wash_trade: bool = False


@app.post("/v1/reputation/update", response_model=ReputationSnapshot)
async def update_reputation(
    body: ReputationUpdateRequest,
    _key: str = Security(_verify_runtime_key),
):
    engines = await get_engines()
    return await engines["reputation"].update(
        agent_id=body.agent_id,
        role=body.role,
        final_status=body.final_status,
        verification_confidence=body.verification_confidence,
        total_duration_ms=body.total_duration_ms,
        all_checks_passed=body.all_checks_passed,
        is_wash_trade=body.is_wash_trade,
    )


class RiskRequest(BaseModel):
    contract: TaskContract
    buyer_rep: ReputationSnapshot | None = None
    worker_rep: ReputationSnapshot | None = None


@app.post("/v1/risk/assess")
async def assess_risk(body: RiskRequest, _key: str = Security(_verify_runtime_key)):
    engines = await get_engines()
    return engines["risk"].assess(body.contract, body.buyer_rep, body.worker_rep)


@app.get("/health")
async def health():
    return {"status": "ok", "runtime": "private"}


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.runtime_host,
        port=settings.runtime_port,
        workers=2,
        log_level=settings.log_level.lower(),
    )
