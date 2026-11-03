"""KarmaBilateral direct integration routes (moved from the BFF).

These are the endpoints the karma-openclaw MCP tools call, so agents can drive
lock/bind/settle/finalize with plain X-Karma-Api-Key auth (no HMAC).

Agent-side ``lock`` is a spend: it is gated by a signed spending grant
(``services.spending_grant``). A grant-less, expired, paused, revoked, or
insufficient grant rejects the lock before any on-chain money moves.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.middleware.auth import require_auth_if_enabled, resolve_agent_id_from_request
from config.settings import settings
from db.session import get_db
from db.models.orm import TaskContractModel
from services import order_contract, proof_availability, spending_grant
from services.actor_guards import require_arbitration_operator
from services.chain.settlement_adapter import OnChainSettlementAdapter

router = APIRouter(prefix="/v1/bilateral", tags=["bilateral"])

_adapter: OnChainSettlementAdapter | None = None

#: Decimal base for on-chain USDC amounts (6 decimals).
_TOKEN_DECIMALS = 6


def _chain() -> OnChainSettlementAdapter:
    global _adapter
    if _adapter is None:
        _adapter = OnChainSettlementAdapter()
    return _adapter



class LockRequest(BaseModel):
    token: str = Field(description="ERC-20 token address")
    amount: int = Field(description="Amount in base units (6 decimals for USDC)")
    role: str = Field(default="buyer", description="buyer | agent")


class BindRequest(BaseModel):
    buyer_bill_id: int
    agent_bill_id: int
    scope_hash: str = Field(description="0x-prefixed 32-byte hex")
    task_id: str | None = Field(
        default=None,
        description="Optional contract task_id; when set, the contract must be signed by both parties and scope_hash must equal its terms_hash",
    )


class SettleRequest(BaseModel):
    binding_id: int
    proof_hash: str = Field(description="0x-prefixed 32-byte hex proof hash")
    proof_payload: str | None = Field(
        default=None,
        description="Optional proof payload; when set, sha256(payload) must equal proof_hash and the payload is stored for later retrieval (data availability)",
    )


class DisputeRequest(BaseModel):
    binding_id: int
    evidence_hash: str = Field(description="0x-prefixed 32-byte hex evidence hash")
    task_id: str | None = Field(
        default=None,
        description="Optional contract task_id; when set, the on-chain binding scopeHash must equal the signed contract terms_hash",
    )


class RelayRequest(BaseModel):
    raw_tx: str = Field(description="0x-prefixed client-signed raw transaction")


class ResolveDisputeRequest(BaseModel):
    binding_id: int
    buyer_share_bps: int = Field(
        ge=0,
        le=10000,
        description="buyer share of the combined pool in basis points (10000 = 100%)",
    )


class AutoResolveDisputeRequest(BaseModel):
    binding_id: int


@router.post("/lock")
async def lock(
    body: LockRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_auth_if_enabled),
):
    grant = None
    agent_id = None
    amount_human: float | None = None
    if settings.spending_grant_enforced and body.role == "agent":
        agent_id = resolve_agent_id_from_request(request)
        if not agent_id:
            raise HTTPException(401, "agent identity required for agent-side lock")
        amount_human = float(body.amount) / (10 ** _TOKEN_DECIMALS)
        # Read-only pre-pick of a covering grant (fast-fail before hitting chain).
        selected = await spending_grant.assert_spend_allowed(
            db,
            agent_id=agent_id,
            token_address=body.token,
            amount=amount_human,
        )
        # Atomic check-and-deduct: two concurrent locks cannot both consume the
        # same allowance. Released below if the on-chain lock fails.
        grant = await spending_grant.reserve_spend(
            db,
            grant_id=selected.grant_id,
            amount=amount_human,
        )
    try:
        bill_id = _chain().lock_direct(body.token, body.amount, body.role)
    except Exception as e:  # noqa: BLE001
        if grant is not None and amount_human is not None:
            await spending_grant.release_spend(
                db,
                grant_id=grant.grant_id,
                amount=amount_human,
            )
            await db.commit()
        raise HTTPException(502, f"on-chain lock failed: {e}") from e
    if grant is not None and agent_id is not None and amount_human is not None:
        await spending_grant.link_bill_to_grant(
            db,
            bill_id=bill_id,
            grant_id=grant.grant_id,
            agent_id=agent_id,
            amount=amount_human,
        )
        await db.commit()
    return {"bill_id": bill_id, "token": body.token, "amount": body.amount, "state": "MINTED"}


def _agent_bill_id(status: dict) -> int | None:
    """Extract the agent bill id from a binding status payload."""
    if not isinstance(status, dict):
        return None
    agent_bill = status.get("agent_bill")
    if isinstance(agent_bill, dict) and agent_bill.get("bill_id") is not None:
        return int(agent_bill["bill_id"])
    if status.get("agent_bill_id") is not None:
        return int(status["agent_bill_id"])
    return None


async def _persist_contract_binding(db: AsyncSession, task_id: str, binding_id: int) -> None:
    """Write the chain binding id back to the contract row so revise/anchor can
    detect anchoring without relying on a settlement row existing."""
    row = await db.get(TaskContractModel, task_id)
    if row is None:
        return
    row.onchain_binding_id = binding_id
    await db.commit()


async def _require_signed_contract_for_bind(
    db: AsyncSession,
    task_id: str,
    scope_hash: str,
) -> None:
    """Bind gate: a task_id-bound bind must reference a dual-signed contract whose
    terms_hash equals the on-chain scopeHash being anchored."""
    row = await db.get(TaskContractModel, task_id)
    if not row:
        raise HTTPException(404, f"Contract {task_id} not found")
    if not row.terms_hash:
        raise HTTPException(409, "contract has no terms_hash; recreate the contract")
    if (row.contract_status or "draft") != order_contract.STATUS_SIGNED:
        raise HTTPException(409, "contract is not signed by both parties")
    if order_contract.terms_hash_bytes32(row.terms_hash) != scope_hash.strip().lower():
        raise HTTPException(409, "scope_hash does not match the signed contract terms_hash")


@router.post("/bind")
async def bind(
    body: BindRequest,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_auth_if_enabled),
):
    if body.task_id is not None:
        await _require_signed_contract_for_bind(db, body.task_id, body.scope_hash)
    try:
        binding_id = _chain().bind_direct(body.buyer_bill_id, body.agent_bill_id, body.scope_hash)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"on-chain bind failed: {e}") from e
    if body.task_id is not None:
        await _persist_contract_binding(db, body.task_id, binding_id)
    return {
        "binding_id": binding_id,
        "buyer_bill_id": body.buyer_bill_id,
        "agent_bill_id": body.agent_bill_id,
        "state": "ACTIVE",
    }


@router.post("/settle")
async def settle(
    body: SettleRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_auth_if_enabled),
):
    if settings.spending_grant_enforced:
        agent_id = resolve_agent_id_from_request(request)
        if not agent_id:
            raise HTTPException(401, "agent identity required for settle")
        try:
            status = _chain().binding_status(body.binding_id)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(502, f"on-chain status failed: {e}") from e
        agent_bill_id = _agent_bill_id(status)
        if agent_bill_id is None:
            raise HTTPException(409, "binding has no agent bill")
        await spending_grant.assert_bill_covered_by_grant(
            db, bill_id=agent_bill_id, agent_id=agent_id
        )
    if body.proof_payload is not None:
        await proof_availability.store_proof(
            db,
            payload=body.proof_payload,
            proof_hash=body.proof_hash,
        )
        await db.commit()
    if settings.require_proof_availability:
        await proof_availability.assert_proof_available(db, body.proof_hash)
    try:
        _chain().settle_direct(body.binding_id, body.proof_hash)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"on-chain settle failed: {e}") from e
    return _chain().binding_status(body.binding_id)


async def _require_contract_anchor(db: AsyncSession, task_id: str, binding_id: int) -> None:
    """Dispute gate: the on-chain binding must anchor the signed contract termsHash."""
    row = await db.get(TaskContractModel, task_id)
    if not row:
        raise HTTPException(404, f"Contract {task_id} not found")
    if not row.terms_hash:
        raise HTTPException(409, "contract has no terms_hash; recreate the contract")
    if getattr(row, "onchain_binding_id", None) is not None and row.onchain_binding_id != binding_id:
        raise HTTPException(
            409, "binding_id does not match the contract's on-chain binding"
        )
    if (row.contract_status or "draft") != order_contract.STATUS_SIGNED:
        raise HTTPException(409, "contract is not signed by both parties")
    try:
        status = _chain().binding_status(binding_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"on-chain status failed: {e}") from e
    chain_scope = status.get("scope_hash")
    expected = order_contract.terms_hash_bytes32(row.terms_hash)
    if not chain_scope or chain_scope.lower() != expected.lower():
        raise HTTPException(
            409, "on-chain binding scopeHash does not match the signed contract terms_hash"
        )


@router.post("/dispute")
async def dispute(
    body: DisputeRequest,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_auth_if_enabled),
):
    if body.task_id is not None:
        await _require_contract_anchor(db, body.task_id, body.binding_id)
    try:
        result = _chain().dispute_direct(body.binding_id, body.evidence_hash)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"on-chain dispute failed: {e}") from e
    return {
        "binding_id": body.binding_id,
        "tx_hash": result.tx_hash,
        "status": result.status,
        "state": "DISPUTED",
    }


@router.get("/status/{binding_id}")
async def status(binding_id: int):
    try:
        return _chain().binding_status(binding_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"on-chain status failed: {e}") from e


@router.post("/finalize/{binding_id}")
async def finalize(
    binding_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_auth_if_enabled),
):
    if settings.spending_grant_enforced:
        agent_id = resolve_agent_id_from_request(request)
        if not agent_id:
            raise HTTPException(401, "agent identity required for finalize")
        try:
            status = _chain().binding_status(binding_id)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(502, f"on-chain status failed: {e}") from e
        agent_bill_id = _agent_bill_id(status)
        if agent_bill_id is None:
            raise HTTPException(409, "binding has no agent bill")
        await spending_grant.assert_bill_covered_by_grant(
            db, bill_id=agent_bill_id, agent_id=agent_id
        )
    try:
        _chain().finalize_binding(binding_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"on-chain finalize failed: {e}") from e
    return _chain().binding_status(binding_id)


@router.post("/relay")
async def relay(body: RelayRequest, _auth=Depends(require_auth_if_enabled)):
    """Relay a client-signed raw transaction (production client-signing path)."""
    try:
        result = _chain().relay_signed_tx(body.raw_tx)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"relay failed: {e}") from e
    return {
        "tx_hash": result.tx_hash,
        "status": result.status,
        "block_number": result.block_number,
        "gas_used": result.gas_used,
    }


def _contract_anchor_view(row: TaskContractModel, chain_scope_hash: str | None) -> dict:
    """Ruling-view projection of the contract anchored by a binding."""
    expected = None
    if row.terms_hash:
        try:
            expected = order_contract.terms_hash_bytes32(row.terms_hash)
        except ValueError:
            expected = None
    return {
        "task_id": row.task_id,
        "version": row.version,
        "contract_status": row.contract_status,
        "terms_hash": row.terms_hash,
        "terms": {
            "title": row.title,
            "description": row.description,
            "expected_output_schema": row.expected_output_schema,
            "expected_step_count": row.expected_step_count,
            "escrow_amount": row.escrow_amount,
            "currency": row.currency,
            "deadline_at": row.deadline_at.isoformat() if row.deadline_at else None,
            "quality_standard": row.quality_standard,
            "inspection_standard": row.inspection_standard,
            "shipment_terms": row.shipment_terms,
            "delivery_criteria": row.delivery_criteria,
            "penalty": row.penalty,
            "arbitration_rules": row.arbitration_rules,
        },
        "buyer": {"address": row.buyer_address, "signature": row.buyer_signature},
        "worker": {
            "agent_id": row.worker_agent_id,
            "public_key": row.worker_public_key,
            "signature": row.worker_signature,
        },
        "signed_at": row.signed_at.isoformat() if row.signed_at else None,
        "anchored": bool(expected and chain_scope_hash and expected.lower() == chain_scope_hash.lower()),
    }


@router.post("/resolve")
async def resolve_dispute(
    body: ResolveDisputeRequest,
    _operator: str = Depends(require_arbitration_operator),
):
    """Role-gated resolve of a DISPUTED on-chain binding.

    The chain enforces the split against the submitted evidence and the evidence
    window; this endpoint is a thin relay, not an override.
    """
    try:
        result = _chain().resolve_dispute(body.binding_id, body.buyer_share_bps)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"on-chain dispute resolve failed: {e}") from e
    return {
        "binding_id": body.binding_id,
        "buyer_share_bps": body.buyer_share_bps,
        "tx_hash": result.tx_hash,
        "status": result.status,
    }


@router.post("/auto-resolve")
async def auto_resolve_dispute(
    body: AutoResolveDisputeRequest,
    _operator: str = Depends(require_arbitration_operator),
):
    """Role-gated trigger of conservative auto-resolution for a disputed binding."""
    try:
        result = _chain().auto_resolve_dispute(body.binding_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"on-chain auto-resolve failed: {e}") from e
    return {
        "binding_id": body.binding_id,
        "tx_hash": result.tx_hash,
        "status": result.status,
    }


@router.get("/dispute/{binding_id}")
async def dispute_ruling_view(
    binding_id: int,
    db: AsyncSession = Depends(get_db),
    _operator: str = Depends(require_arbitration_operator),
):
    """Ruling view: binding + arbitration record + the anchored contract terms."""
    try:
        binding = _chain().binding_status(binding_id)
        arbitration = _chain().arbitration_status(binding_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"on-chain dispute read failed: {e}") from e

    contract = None
    result = await db.execute(
        select(TaskContractModel).where(TaskContractModel.onchain_binding_id == binding_id)
    )
    row = result.scalars().first()
    if row is not None:
        contract = _contract_anchor_view(row, binding.get("scope_hash"))
    return {"binding": binding, "arbitration": arbitration, "contract": contract}
