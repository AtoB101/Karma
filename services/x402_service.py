"""Phase 2 — x402 pay-and-fetch orchestration + receipt audit."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from core.schemas import ExecutionReceipt, ExternalPaymentRecord, ToolStatus
from db.stores.receipt_store import PostgresReceiptStore
from db.stores.settlement_store import PostgresSettlementStore
from sdk.x402.client import X402Client
from sdk.x402.chain_executor import EnvSigningX402PaymentExecutor, SepoliaErc20X402PaymentExecutor
from sdk.x402.executors import MockX402PaymentExecutor, resolve_x402_private_key
from sdk.x402.url_safety import UnsafeX402UrlError
from services.task_contract_guard import ensure_task_contract_exists


def _hex64(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_x402_client() -> X402Client:
    backend = (settings.x402_payment_backend or "mock").strip().lower()
    if backend == "mock":
        executor = MockX402PaymentExecutor()
    elif backend == "env":
        executor = EnvSigningX402PaymentExecutor(private_key=resolve_x402_private_key())
    elif backend == "sepolia":
        executor = SepoliaErc20X402PaymentExecutor(private_key=resolve_x402_private_key())
    else:
        raise ValueError(f"unsupported X402_PAYMENT_BACKEND: {backend}")
    return X402Client(executor, allow_private_hosts=settings.x402_allow_private_hosts)


async def pay_and_fetch_with_audit(
    db: AsyncSession,
    *,
    task_id: str,
    agent_id: str,
    url: str,
    max_budget_usdc: float | None = None,
) -> dict[str, Any]:
    budget = max_budget_usdc if max_budget_usdc is not None else settings.x402_default_max_budget_usdc
    if budget <= 0:
        raise ValueError("max_budget_usdc must be positive")
    await ensure_task_contract_exists(db, task_id)

    client = build_x402_client()
    try:
        result = await client.pay_and_fetch(url, max_budget_usdc=budget)
    except UnsafeX402UrlError as exc:
        raise ValueError(str(exc)) from exc

    receipt_store = PostgresReceiptStore(db)
    latest = await receipt_store.get_latest_by_task(task_id)
    step_index = 1 if latest is None else latest.step_index + 1

    ext = result.external_payment
    receipt: ExecutionReceipt | None = None
    if ext is not None:
        now = datetime.now(timezone.utc)
        receipt = ExecutionReceipt(
            task_id=task_id,
            agent_id=agent_id,
            step_index=step_index,
            tool_name="x402.fetch",
            input_hash=_hex64(url.encode()),
            output_hash=_hex64(result.body),
            started_at=now,
            ended_at=now,
            duration_ms=1,
            status=ToolStatus.SUCCESS if 200 <= result.status_code < 300 else ToolStatus.FAILURE,
            external_payment=ExternalPaymentRecord(
                protocol=ext.protocol,
                tx_hash=ext.tx_hash,
                amount_usdc=ext.amount_usdc,
                resource_url=ext.resource_url,
                payment_proof=ext.payment_proof,
                network=ext.network,
                asset=ext.asset,
                metadata=dict(ext.metadata or {}),
            ),
            signature="0xtrade_x402_audit" if not settings.receipt_require_signature else None,
            metadata={"x402_status_code": result.status_code},
        )
        await receipt_store.save(receipt)

        settlement_store = PostgresSettlementStore(db)
        settlement = await settlement_store.get(task_id)
        if settlement:
            fs = settlement.funding_source or "internal"
            if fs == "internal":
                settlement.funding_source = "x402"
            elif fs == "x402":
                pass
            else:
                settlement.funding_source = "hybrid"
            await settlement_store.save(settlement)

    return {
        "status_code": result.status_code,
        "body_preview": result.body[:512].decode("utf-8", errors="replace"),
        "payment_attempts": result.payment_attempts,
        "external_payment": ext.model_dump() if ext else None,
        "receipt_id": receipt.receipt_id if receipt else None,
        "funding_source_updated": ext is not None,
    }
