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
from sqlalchemy.ext.asyncio import AsyncSession

from api.middleware.auth import require_auth_if_enabled, resolve_agent_id_from_request
from config.settings import settings
from db.session import get_db
from db.models.orm import TaskContractModel
from services import order_contract, spending_grant
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


class DisputeRequest(BaseModel):
    binding_id: int
    evidence_hash: str = Field(description="0x-prefixed 32-byte hex evidence hash")
    task_id: str | None = Field(
        default=None,
        description="Optional contract task_id; when set, the on-chain binding scopeHash must equal the signed contract terms_hash",
    )


class RelayRequest(BaseModel):
    raw_tx: str = Field(description="0x-prefixed client-signed raw transaction")


@router.post("/lock")
async def lock(
    body: LockRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_auth_if_enabled),
):
    grant = None
    amount_human: float | None = None
    if settings.spending_grant_enforced and body.role == "agent":
        agent_id = resolve_agent_id_from_request(request)
        if not agent_id:
            raise HTTPException(401, "agent identity required for agent-side lock")
        amount_human = float(body.amount) / (10 ** _TOKEN_DECIMALS)
        grant = await spending_grant.assert_spend_allowed(
            db,
            agent_id=agent_id,
            token_address=body.token,
            amount=amount_human,
        )
    try:
        bill_id = _chain().lock_direct(body.token, body.amount, body.role)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"on-chain lock failed: {e}") from e
    if grant is not None and amount_human is not None:
        await spending_grant.record_spend(
            db,
            grant_id=grant.grant_id,
            amount=amount_human,
            owner_identity_id=grant.owner_identity_id,
            agent_id=grant.agent_id,
        )
        await db.commit()
    return {"bill_id": bill_id, "token": body.token, "amount": body.amount, "state": "MINTED"}


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
        await spending_grant.assert_agent_authorized(db, agent_id=agent_id)
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
        await spending_grant.assert_agent_authorized(db, agent_id=agent_id)
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
