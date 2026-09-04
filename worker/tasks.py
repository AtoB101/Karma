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
        "worker.tasks.sweep_timed_out_escrows":      {"queue": "settlement"},
        "worker.tasks.auto_verify_bundle":           {"queue": "verification"},
        "worker.tasks.check_challenge_expiry":        {"queue": "verification"},
        "worker.tasks.update_verifier_reputation":    {"queue": "reputation"},
        "worker.tasks.sync_attestations_to_chain":     {"queue": "verification"},
    },
    beat_schedule={
        "expire-stale-payment-intents-hourly": {
            "task": "worker.tasks.expire_stale_payment_intents",
            "schedule": 3600.0,
        },
        "sweep-timed-out-escrows-hourly": {
            "task": "worker.tasks.sweep_timed_out_escrows",
            "schedule": 3600.0,
        },
        "check-challenge-expiry-every-5-min": {
            "task": "worker.tasks.check_challenge_expiry",
            "schedule": 300.0,
        },
        "update-verifier-reputation-hourly": {
            "task": "worker.tasks.update_verifier_reputation",
            "schedule": 3600.0,
        },
        "finalize-onchain-settlements-every-5-min": {
            "task": "worker.tasks.finalize_onchain_settlement",
            "schedule": 300.0,
        },
    },
)

logger = get_task_logger(__name__)


# ── Import decentralized verifier tasks so Celery discovers them ──
import decentralized_verifier.tasks  # noqa: F401  — registers shared_task entries


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
            amount_wei = int(contract.escrow_amount * (10 ** settings.settlement_token_decimals))
            tx_result = settlement_router.release_payment(contract, result, bundle, amount_wei)
            if tx_result:
                # Persist tx_hash to DB (settle → FINALIZING; finalizeSettle is a follow-up)
                asyncio.run(
                    _persist_chain_result(
                        task_id,
                        tx_result,
                        bundle_hash,
                        settings.settlement_mode,
                        contract=contract,
                        onchain_status="finalizing",
                    )
                )
                logger.info(f"On-chain settle submitted: task={task_id} tx={tx_result.tx_hash}")
                return {
                    "task_id":      task_id,
                    "tx_hash":      tx_result.tx_hash,
                    "block_number": tx_result.block_number,
                    "status":       tx_result.status,
                    "onchain_status": "finalizing",
                    "binding_id":   tx_result.binding_id,
                    "bundle_hash":  bundle_hash,
                    "note":         "Call finalizeSettle after dispute window",
                }
        elif result.decision in (VerificationDecision.REFUND, VerificationDecision.HOLD):
            refund_info = settlement_router.refund_payment(
                task_id, result, task_contract=contract
            )
            status = "refunded" if refund_info.get("status") == "confirmed" else "refund"
            asyncio.run(
                _persist_chain_or_offchain_result(
                    task_id, bundle_hash, status, settings.settlement_mode, refund_info, contract
                )
            )
            return {"task_id": task_id, "action": "refund", **refund_info}

        elif result.decision == VerificationDecision.DISPUTE:
            dispute_info = settlement_router.open_dispute(
                task_id, bundle_hash, task_contract=contract
            )
            status = "disputed" if dispute_info.get("status") == "confirmed" else "dispute_pending"
            asyncio.run(
                _persist_chain_or_offchain_result(
                    task_id, bundle_hash, status, settings.settlement_mode, dispute_info, contract
                )
            )
            return {"task_id": task_id, "action": "dispute", **dispute_info}

    except Exception as exc:
        logger.error(f"On-chain settlement failed: task={task_id} error={exc}")
        raise self.retry(exc=exc)


async def _persist_chain_result(
    task_id: str,
    tx_result,
    bundle_hash: str,
    mode: str,
    *,
    contract=None,
    onchain_status: str | None = None,
) -> None:
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
            row.onchain_status      = onchain_status or tx_result.status
            row.chain_id            = settings.testnet_chain_id
            row.contract_address    = settings.karma_bilateral_address or settings.karma_engine_address
            row.evidence_bundle_hash= bundle_hash
            row.quote_id            = tx_result.quote_id
            row.settlement_mode     = mode
            if contract is not None:
                if getattr(contract, "onchain_binding_id", None) is not None:
                    row.onchain_binding_id = int(contract.onchain_binding_id)
                if getattr(contract, "onchain_buyer_bill_id", None) is not None:
                    row.onchain_buyer_bill_id = int(contract.onchain_buyer_bill_id)
                if getattr(contract, "onchain_agent_bill_id", None) is not None:
                    row.onchain_agent_bill_id = int(contract.onchain_agent_bill_id)
            elif getattr(tx_result, "binding_id", None) is not None:
                row.onchain_binding_id = int(tx_result.binding_id)
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


async def _persist_chain_or_offchain_result(
    task_id: str,
    bundle_hash: str,
    onchain_status: str,
    mode: str,
    info: dict,
    contract=None,
) -> None:
    """Persist refund/dispute outcomes (on-chain tx or offchain-only note)."""
    from db.session import AsyncSessionLocal
    from db.models.orm import SettlementModel
    from sqlalchemy import select

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(SettlementModel).where(SettlementModel.task_id == task_id)
        )
        row = result.scalar_one_or_none()
        if not row:
            return
        from config.settings import settings

        row.evidence_bundle_hash = bundle_hash
        row.onchain_status = onchain_status
        row.settlement_mode = mode
        if info.get("tx_hash"):
            row.tx_hash = info["tx_hash"]
            row.chain_id = settings.testnet_chain_id
            row.contract_address = settings.karma_bilateral_address or settings.karma_engine_address
        if info.get("binding_id") is not None:
            row.onchain_binding_id = int(info["binding_id"])
            row.quote_id = f"binding:{info['binding_id']}"
        if contract is not None:
            if getattr(contract, "onchain_buyer_bill_id", None) is not None:
                row.onchain_buyer_bill_id = int(contract.onchain_buyer_bill_id)
            if getattr(contract, "onchain_agent_bill_id", None) is not None:
                row.onchain_agent_bill_id = int(contract.onchain_agent_bill_id)
            if getattr(contract, "onchain_binding_id", None) is not None:
                row.onchain_binding_id = int(contract.onchain_binding_id)
        await session.commit()


@app.task(name="worker.tasks.lock_and_bind_onchain", bind=True, max_retries=3, default_retry_delay=15)
def lock_and_bind_onchain(self, task_id: str, escrow_wei: int, seller_penalty_wei: int = 0):
    """On settlement acceptance (接单): lock buyer escrow + seller penalty on-chain
    and bind the two bills into a binding. Seller penalty defaults to
    escrow_wei * SETTLEMENT_DEFAULT_PENALTY_BPS / 10000."""
    import asyncio
    from config.settings import settings
    from core.schemas import TaskContract
    from services.chain.settlement_adapter import settlement_router

    if not settlement_router.is_onchain():
        return {"skipped": True, "mode": settings.settlement_mode}

    contract = TaskContract.model_construct(
        task_id=task_id,
        escrow_amount=float(escrow_wei),
        onchain_do_lock=True,
    )
    try:
        result = asyncio.run(_lock_and_bind(contract, seller_penalty_wei))
        logger.info(f"lock_and_bind_onchain ok: task={task_id} binding={result.get('binding_id')}")
        return {"task_id": task_id, **result}
    except Exception as exc:
        logger.error(f"lock_and_bind_onchain failed: task={task_id} error={exc}")
        raise self.retry(exc=exc)


async def _lock_and_bind(contract, seller_penalty_wei: int) -> dict:
    from config.settings import settings
    from services.chain.settlement_adapter import settlement_router

    escrow_wei = int(contract.escrow_amount)
    if seller_penalty_wei <= 0:
        seller_penalty_wei = (escrow_wei * settings.settlement_default_penalty_bps) // 10_000

    buyer = settlement_router.lock_funds(contract)
    agent = settlement_router.lock_agent_penalty(contract, seller_penalty_wei)
    bind = settlement_router.bind_bills(contract)
    return {
        "buyer_bill_id": getattr(contract, "onchain_buyer_bill_id", None),
        "agent_bill_id": getattr(contract, "onchain_agent_bill_id", None),
        "binding_id": bind.binding_id,
        "tx_hash": bind.tx_hash,
        "buyer": buyer,
        "agent": agent,
    }


@app.task(name="worker.tasks.finalize_onchain_settlement")
def finalize_onchain_settlement() -> dict:
    """Beat: auto-finalize bindings whose dispute window has closed, releasing
    the buyer's payment to the seller."""
    import asyncio
    from config.settings import settings
    from services.chain.settlement_adapter import settlement_router

    if not settlement_router.is_onchain():
        return {"finalized": 0, "mode": settings.settlement_mode}

    count = asyncio.run(_finalize_due_bindings())
    logger.info("finalize_onchain_settlement complete", extra={"finalized": count})
    return {"finalized": count}


async def _finalize_due_bindings() -> int:
    import time as _time
    from db.session import AsyncSessionLocal
    from db.models.orm import SettlementModel
    from sqlalchemy import select
    from services.chain.settlement_adapter import settlement_router

    now = int(_time.time())
    finalized = 0
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(SettlementModel).where(SettlementModel.onchain_status == "finalizing")
        )
        rows = result.scalars().all()
        ids = [r.onchain_binding_id for r in rows if r.onchain_binding_id is not None]
    for binding_id in ids:
        try:
            due = settlement_router.finalize_after(int(binding_id))
            if due != 0 and due <= now:
                tx = settlement_router.finalize_binding(int(binding_id))
                if tx.status == "confirmed":
                    finalized += 1
        except Exception as exc:  # window open / not finalizing / RPC — skip
            logger.warning("finalize_binding_skipped", binding_id=binding_id, error=str(exc))
            continue
    return finalized


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


@app.task(name="worker.tasks.sweep_timed_out_escrows")
def sweep_timed_out_escrows() -> dict:
    """Hourly beat: refund orders stuck in escrow past the timeout (P2-8).

    超时退款 sweep——LOCKED/EXECUTED/EVIDENCE_SUBMITTED 停滞超过
    ESCROW_TIMEOUT_SWEEP_HOURS 的订单自动保守退款；争议中的订单跳过。
    """
    from config.settings import settings

    if not settings.escrow_timeout_sweep_enabled:
        return {"refunded_count": 0, "enabled": False}

    from services.miniapp_commerce.timeout_sweep import sweep_timed_out_escrows as _sweep

    result = _sweep()
    return {
        "refunded_count": len(result["refunded"]),
        "skipped_disputed": result.get("skipped_disputed", 0),
        "scanned": result.get("scanned", 0),
        "enabled": True,
    }
