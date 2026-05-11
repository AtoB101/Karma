"""
PRIVATE — Karma Runtime API
============================
Internal service. Never expose to public internet.
Called by public API to apply verification and settlement decisions.

Endpoints:
  POST /v1/verify                          — run private verification engine
  POST /v1/settlement/{task_id}/apply-verification  — apply result to settlement
  POST /v1/reputation/update               — update agent reputation
  GET  /v1/risk/{task_id}                  — get risk assessment

DO NOT commit to public repository.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from core.schemas import (
    EvidenceBundle,
    ReputationSnapshot,
    SettlementState,
    TaskContract,
    TaskStatus,
    VerificationResult,
    AgentRole,
)

logger = structlog.get_logger(__name__)

# These are imported from private modules
from core.verification.engine import PrivateVerificationEngine
from core.settlement.state_machine import PrivateSettlementStateMachine, SettlementStore
from core.reputation.system import PrivateReputationSystem, ReputationStore
from core.risk.scorer import RiskScorer
from core.fraud.detector import FraudDetector
from core.behavior.analyzer import BehaviorAnalyzer


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("karma_private_runtime_starting")
    yield


app = FastAPI(
    title="Karma Private Runtime",
    description="INTERNAL — Do not expose publicly",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None,   # no public docs
    redoc_url=None,
)

# ---------------------------------------------------------------------------
# Dependency injection (wire up real stores in production)
# ---------------------------------------------------------------------------

def get_verification_engine() -> PrivateVerificationEngine:
    from db.stores.private_stores import get_receipt_store, get_signing_service
    return PrivateVerificationEngine(
        signing_service=get_signing_service(),
        receipt_store=get_receipt_store(),
    )

def get_settlement_machine() -> PrivateSettlementStateMachine:
    from db.stores.private_stores import get_settlement_store
    return PrivateSettlementStateMachine(store=get_settlement_store())

def get_reputation_system() -> PrivateReputationSystem:
    from db.stores.private_stores import get_reputation_store
    return PrivateReputationSystem(store=get_reputation_store())

risk_scorer    = RiskScorer()
fraud_detector = FraudDetector()
behavior_analyzer = BehaviorAnalyzer()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

class VerifyRequest(BaseModel):
    bundle: EvidenceBundle
    contract: TaskContract


@app.post("/v1/verify", response_model=VerificationResult)
async def verify(body: VerifyRequest):
    engine = get_verification_engine()
    result = await engine.verify(body.bundle, body.contract)
    logger.info("verification_complete", task_id=body.bundle.task_id, decision=result.decision)
    return result


class ApplyVerificationRequest(BaseModel):
    result: VerificationResult


@app.post("/v1/settlement/{task_id}/apply-verification", response_model=SettlementState)
async def apply_verification(task_id: str, body: ApplyVerificationRequest):
    machine = get_settlement_machine()
    state = await machine.apply_verification(task_id, body.result)
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
async def update_reputation(body: ReputationUpdateRequest):
    system = get_reputation_system()
    snapshot = await system.update(
        agent_id=body.agent_id,
        role=body.role,
        final_status=body.final_status,
        verification_confidence=body.verification_confidence,
        total_duration_ms=body.total_duration_ms,
        all_checks_passed=body.all_checks_passed,
        is_wash_trade=body.is_wash_trade,
    )
    return snapshot


class RiskRequest(BaseModel):
    contract: TaskContract
    buyer_rep: ReputationSnapshot | None = None
    worker_rep: ReputationSnapshot | None = None


@app.post("/v1/risk/assess")
async def assess_risk(body: RiskRequest):
    assessment = risk_scorer.assess(body.contract, body.buyer_rep, body.worker_rep)
    return assessment


@app.get("/health")
async def health():
    return {"status": "ok", "runtime": "private"}
