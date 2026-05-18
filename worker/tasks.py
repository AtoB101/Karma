"""
Karma — Celery Async Worker
Handles verification, settlement, and reputation updates asynchronously.
"""
from __future__ import annotations

from celery import Celery
from celery.utils.log import get_task_logger

from config.settings import settings

app = Celery(
    "karma",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_routes={
        "worker.tasks.run_verification":   {"queue": "verification"},
        "worker.tasks.run_settlement":     {"queue": "settlement"},
        "worker.tasks.update_reputation":  {"queue": "reputation"},
        "worker.tasks.expire_stale_payment_intents": {"queue": "settlement"},
    },
    beat_schedule={
        "expire-stale-payment-intents-hourly": {
            "task": "worker.tasks.expire_stale_payment_intents",
            "schedule": 3600.0,
        },
    },
)

logger = get_task_logger(__name__)


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

@app.task(
    name="worker.tasks.run_verification",
    bind=True,
    max_retries=3,
    default_retry_delay=10,
)
def run_verification(self, task_id: str, bundle_dict: dict, contract_dict: dict):
    """
    Async verification task.
    Called after worker agent submits evidence bundle.
    """
    import asyncio
    from core.schemas import EvidenceBundle, TaskContract

    bundle   = EvidenceBundle(**bundle_dict)
    contract = TaskContract(**contract_dict)

    try:
        result = asyncio.run(_async_verify(bundle, contract))
        logger.info(f"Verification complete: task={task_id} decision={result['decision']}")
        return result
    except Exception as exc:
        logger.error(f"Verification failed: task={task_id} error={exc}")
        raise self.retry(exc=exc)


@app.task(
    name="worker.tasks.run_settlement",
    bind=True,
    max_retries=3,
    default_retry_delay=5,
)
def run_settlement(self, task_id: str, verification_result_dict: dict):
    """Apply verification result to settlement state machine."""
    import asyncio
    from core.schemas import VerificationResult

    result = VerificationResult(**verification_result_dict)
    try:
        state = asyncio.run(_async_settle(task_id, result))
        logger.info(f"Settlement complete: task={task_id} status={state['status']}")
        return state
    except Exception as exc:
        raise self.retry(exc=exc)


@app.task(
    name="worker.tasks.update_reputation",
    bind=True,
    max_retries=3,
    default_retry_delay=5,
)
def update_reputation(
    self,
    agent_id: str,
    role: str,
    final_status: str,
    verification_confidence: float | None = None,
    total_duration_ms: int | None = None,
    all_checks_passed: bool = False,
):
    import asyncio
    try:
        snapshot = asyncio.run(_async_update_rep(
            agent_id, role, final_status, verification_confidence,
            total_duration_ms, all_checks_passed,
        ))
        logger.info(f"Reputation updated: agent={agent_id} score={snapshot['score']}")
        return snapshot
    except Exception as exc:
        raise self.retry(exc=exc)


# ---------------------------------------------------------------------------
# Async helpers (private runtime calls)
# ---------------------------------------------------------------------------

async def _async_verify(bundle, contract) -> dict:
    import httpx
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(
            f"{settings.private_runtime_url}/v1/verify",
            json={"bundle": bundle.model_dump(mode="json"),
                  "contract": contract.model_dump(mode="json")},
        )
        r.raise_for_status()
        return r.json()


async def _async_settle(task_id: str, result) -> dict:
    import httpx
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            f"{settings.private_runtime_url}/v1/settlement/{task_id}/apply-verification",
            json={"result": result.model_dump(mode="json")},
        )
        r.raise_for_status()
        return r.json()


async def _async_update_rep(agent_id, role, final_status, confidence, duration_ms, all_passed) -> dict:
    import httpx
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            f"{settings.private_runtime_url}/v1/reputation/update",
            json={
                "agent_id": agent_id,
                "role": role,
                "final_status": final_status,
                "verification_confidence": confidence,
                "total_duration_ms": duration_ms,
                "all_checks_passed": all_passed,
            },
        )
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------------------
# On-chain settlement task
# ---------------------------------------------------------------------------

@app.task(
    name="worker.tasks.run_onchain_settlement",
    bind=True,
    max_retries=3,
    default_retry_delay=15,
)
def run_onchain_settlement(
    self,
    task_id: str,
    verification_result_dict: dict,
    bundle_dict: dict,
    contract_dict: dict,
):
    """
    Execute on-chain settlement via existing Karma contracts.
    Only runs when SETTLEMENT_MODE=testnet or hybrid.
    """
    import asyncio
    from config.settings import settings
    from core.schemas import EvidenceBundle, TaskContract, VerificationResult, VerificationDecision
    from services.chain.settlement_adapter import settlement_router

    if not settlement_router.is_onchain():
        logger.info(f"Skipping on-chain settlement (mode={settings.settlement_mode})")
        return {"skipped": True, "mode": settings.settlement_mode}

    result   = VerificationResult(**verification_result_dict)
    bundle   = EvidenceBundle(**bundle_dict)
    contract = TaskContract(**contract_dict)

    try:
        # Compute evidence hash
        bundle_hash = settlement_router.submit_evidence_hash(task_id, bundle)

        if result.decision == VerificationDecision.RELEASE:
            amount_wei = int(contract.escrow_amount)
            tx_result = settlement_router.release_payment(contract, result, bundle, amount_wei)
            if tx_result:
                # Persist tx_hash to DB
                asyncio.run(_persist_chain_result(task_id, tx_result, bundle_hash, settings.settlement_mode))
                logger.info(f"On-chain release complete: task={task_id} tx={tx_result.tx_hash}")
                return {
                    "task_id":      task_id,
                    "tx_hash":      tx_result.tx_hash,
                    "block_number": tx_result.block_number,
                    "status":       tx_result.status,
                    "bundle_hash":  bundle_hash,
                }
        elif result.decision in ("refund", "hold"):
            refund_info = settlement_router.refund_payment(task_id, result)
            asyncio.run(_persist_offchain_result(task_id, bundle_hash, "refund", settings.settlement_mode))
            return {"task_id": task_id, "action": "refund", **refund_info}

        elif result.decision == "dispute":
            dispute_info = settlement_router.open_dispute(task_id, bundle_hash)
            asyncio.run(_persist_offchain_result(task_id, bundle_hash, "disputed", settings.settlement_mode))
            return {"task_id": task_id, "action": "dispute", **dispute_info}

    except Exception as exc:
        logger.error(f"On-chain settlement failed: task={task_id} error={exc}")
        raise self.retry(exc=exc)


async def _persist_chain_result(task_id: str, tx_result, bundle_hash: str, mode: str) -> None:
    """Write tx_hash and chain fields back to settlements table."""
    from db.session import AsyncSessionLocal
    from db.models.orm import SettlementModel
    from sqlalchemy import select

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(SettlementModel).where(SettlementModel.task_id == task_id)
        )
        row = result.scalar_one_or_none()
        if row:
            from config.settings import settings
            row.tx_hash             = tx_result.tx_hash
            row.onchain_status      = tx_result.status
            row.chain_id            = settings.testnet_chain_id
            row.contract_address    = settings.karma_engine_address
            row.evidence_bundle_hash= bundle_hash
            row.quote_id            = tx_result.quote_id
            row.settlement_mode     = mode
            await session.commit()


async def _persist_offchain_result(task_id: str, bundle_hash: str, onchain_status: str, mode: str) -> None:
    from db.session import AsyncSessionLocal
    from db.models.orm import SettlementModel
    from sqlalchemy import select

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(SettlementModel).where(SettlementModel.task_id == task_id)
        )
        row = result.scalar_one_or_none()
        if row:
            row.evidence_bundle_hash = bundle_hash
            row.onchain_status       = onchain_status
            row.settlement_mode      = mode
            await session.commit()


@app.task(name="worker.tasks.expire_stale_payment_intents")
def expire_stale_payment_intents() -> dict[str, int]:
    """Hourly beat: mark expired payment intents (Phase 3 maintenance)."""
    import asyncio

    from config.settings import settings
    from services.payment_intent_service import expire_stale_intents

    if not settings.payment_intent_expire_enabled:
        return {"expired_count": 0}

    async def _run() -> int:
        from db.session import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            count = await expire_stale_intents(session)
            await session.commit()
            return count

    count = asyncio.run(_run())
    logger.info("expire_stale_payment_intents complete", extra={"expired_count": count})
    return {"expired_count": count}
