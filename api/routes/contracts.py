"""Karma API — Task Contracts"""
from __future__ import annotations

import base64
from datetime import datetime
import json
import math

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from api.middleware.auth import resolve_agent_id_from_request
from core.schemas import TaskContract
from db.session import get_db
from db.models.orm import (
    AgentModel,
    CapacityModel,
    IdentityProfileModel,
    TaskContractModel,
    TaskContractVersionModel,
)
from db.stores.settlement_store import PostgresSettlementStore
from services.actor_guards import caller_is_privileged
from services import order_contract, spending_grant
from services.path_param_safety import validate_public_url_segment
from services.settlement_party_access import actor_identity_ids, require_party_read
from services.signing import sha256_of
from services.text_safety import validate_json_strings_safe, validate_safe_storage_text
from services.settlement_amounts import assert_token_precision

router = APIRouter()


class CreateContractRequest(BaseModel):
    task_id: str | None = Field(
        default=None,
        description="Optional explicit task id (must be unused). If omitted, a UUID is assigned.",
    )
    client_agent_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=512)
    description: str = Field(default="", max_length=32768)
    expected_output_schema: dict
    expected_step_count: int = Field(ge=1, le=1_000_000)
    escrow_amount: float
    currency: str = Field(default="USD", max_length=16)
    deadline_at: datetime
    quality_standard: str | None = Field(default=None, max_length=2048)
    inspection_standard: str | None = Field(default=None, max_length=2048)
    shipment_terms: str | None = Field(default=None, max_length=2048)
    delivery_criteria: str | None = Field(default=None, max_length=2048)
    penalty: str | None = Field(default=None, max_length=2048)
    arbitration_rules: str | None = Field(default=None, max_length=2048)

    @field_validator("title")
    @classmethod
    def _safe_title(cls, v: str) -> str:
        return validate_safe_storage_text(v, field="title")

    @field_validator("description")
    @classmethod
    def _safe_description(cls, v: str) -> str:
        return validate_safe_storage_text(v, field="description")

    @field_validator("currency")
    @classmethod
    def _safe_currency(cls, v: str) -> str:
        return validate_safe_storage_text(v, field="currency")

    @field_validator("client_agent_id")
    @classmethod
    def _safe_client_agent_id(cls, v: str) -> str:
        return validate_safe_storage_text(v, field="client_agent_id")

    @model_validator(mode="after")
    def _safe_trade_clauses(self) -> "CreateContractRequest":
        for field in (
            "quality_standard",
            "inspection_standard",
            "shipment_terms",
            "delivery_criteria",
            "penalty",
            "arbitration_rules",
        ):
            value = getattr(self, field)
            if value is not None:
                setattr(self, field, validate_safe_storage_text(value, field=field))
        return self

    @model_validator(mode="after")
    def _limit_schema_json_size(self) -> "CreateContractRequest":
        raw = json.dumps(self.expected_output_schema, sort_keys=True, default=str)
        if len(raw.encode("utf-8")) > 65536:
            raise ValueError("expected_output_schema JSON must be <= 65536 bytes")
        validate_json_strings_safe(self.expected_output_schema, field="expected_output_schema")
        return self


@router.post("", response_model=TaskContract, status_code=201)
async def create_contract(
    body: CreateContractRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    if body.task_id is not None:
        validate_public_url_segment("task_id", body.task_id)
        if await db.get(TaskContractModel, body.task_id):
            raise HTTPException(409, "task_id already in use")

    if body.escrow_amount < settings.escrow_min_amount - 1e-9:
        raise HTTPException(
            status_code=400,
            detail=f"escrow_amount must be >= {settings.escrow_min_amount}",
        )
    if body.escrow_amount > settings.escrow_max_amount + 1e-9:
        raise HTTPException(
            status_code=400,
            detail=f"escrow_amount must be <= {settings.escrow_max_amount}",
        )
    # NaN 能同时躲过上面两个比较；金额必须是有限数。
    if not math.isfinite(float(body.escrow_amount)):
        raise HTTPException(
            status_code=400, detail="escrow_amount must be a finite number"
        )
    # 链上只有 6 位小数；多出来的位数在链上不存在，账实就会对不平。
    assert_token_precision(body.escrow_amount, field="escrow_amount")
    if settings.spending_grant_enforced:
        actor_id = resolve_agent_id_from_request(request)
        if not actor_id:
            raise HTTPException(401, "agent identity required to create contract")
        agent = await db.get(AgentModel, actor_id)
        owner_id = agent.owner_identity_id if agent is not None else None
        await spending_grant.assert_spend_allowed(
            db,
            agent_id=actor_id,
            owner_identity_id=owner_id,
            token_address=None,
            amount=float(body.escrow_amount),
        )
    cap = await db.get(CapacityModel, body.client_agent_id)
    if cap is not None and float(cap.available_credits) + 1e-9 < float(body.escrow_amount):
        raise HTTPException(
            status_code=409,
            detail="escrow_amount exceeds buyer available_credits on capacity ledger",
        )

    data = body.model_dump()
    if body.task_id is not None:
        data["task_id"] = body.task_id
    else:
        data.pop("task_id", None)
    contract = TaskContract(**data)
    contract.contract_hash = sha256_of(contract.model_dump(exclude={"contract_hash"}))
    contract.terms_hash = order_contract.terms_hash_hex(order_contract.build_terms(contract))
    contract.contract_status = order_contract.STATUS_DRAFT

    db.add(TaskContractModel(
        task_id=contract.task_id,
        client_agent_id=contract.client_agent_id,
        title=contract.title,
        description=contract.description,
        expected_output_schema=contract.expected_output_schema,
        expected_step_count=contract.expected_step_count,
        escrow_amount=contract.escrow_amount,
        currency=contract.currency,
        deadline_at=contract.deadline_at,
        quality_standard=contract.quality_standard,
        inspection_standard=contract.inspection_standard,
        shipment_terms=contract.shipment_terms,
        delivery_criteria=contract.delivery_criteria,
        penalty=contract.penalty,
        arbitration_rules=contract.arbitration_rules,
        contract_hash=contract.contract_hash,
        terms_hash=contract.terms_hash,
        contract_status=contract.contract_status,
        version=contract.version,
        created_at=contract.created_at,
    ))
    return contract


@router.get("/{task_id}", response_model=TaskContract)
async def get_contract(task_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """读任务合同。

    P1-7：此前任何身份都能读别人的合同（对手方、金额、完整需求描述）。
    现在默认只有当事人（买方／被指派卖方）或平台运维岗能读；
    ``TASK_RECORDS_PUBLIC_READ=true`` 可恢复成「人人可审计」。
    """
    row = await db.get(TaskContractModel, task_id)
    if not row:
        raise HTTPException(404, f"Contract {task_id} not found")
    await require_party_read(
        db,
        request,
        _contract_party_ids(row) | await _settlement_party_ids(db, task_id),
        public_read=bool(settings.task_records_public_read),
    )
    return _row_to_contract(row)


class SignContractRequest(BaseModel):
    role: str = Field(pattern="^(buyer|worker)$")
    signature: str = Field(min_length=1, max_length=1024)
    address: str | None = Field(default=None, max_length=42)
    public_key: str | None = Field(default=None, max_length=512)


class ReviseContractRequest(BaseModel):
    """Counter-proposal: only fields explicitly provided are changed; everything else stays."""
    title: str | None = Field(default=None, max_length=512)
    description: str | None = Field(default=None, max_length=32768)
    expected_output_schema: dict | None = None
    expected_step_count: int | None = Field(default=None, ge=1, le=1_000_000)
    escrow_amount: float | None = None
    currency: str | None = Field(default=None, max_length=16)
    deadline_at: datetime | None = None
    quality_standard: str | None = Field(default=None, max_length=2048)
    inspection_standard: str | None = Field(default=None, max_length=2048)
    shipment_terms: str | None = Field(default=None, max_length=2048)
    delivery_criteria: str | None = Field(default=None, max_length=2048)
    penalty: str | None = Field(default=None, max_length=2048)
    arbitration_rules: str | None = Field(default=None, max_length=2048)

    @model_validator(mode="after")
    def _safe_revise_strings(self) -> "ReviseContractRequest":
        for field in (
            "title", "description", "currency", "quality_standard", "inspection_standard",
            "shipment_terms", "delivery_criteria", "penalty", "arbitration_rules",
        ):
            value = getattr(self, field)
            if value is not None:
                setattr(self, field, validate_safe_storage_text(value, field=field))
        return self


def _order_contract_chain_id() -> int:
    return settings.order_contract_eip712_chain_id or settings.testnet_chain_id


async def _buyer_bound_wallet(db: AsyncSession, client_agent_id: str) -> str | None:
    """Resolve the client agent's owner wallet — the address the buyer must sign with."""
    buyer_agent = await db.get(AgentModel, client_agent_id)
    if buyer_agent is None or not buyer_agent.owner_identity_id:
        return None
    identity = await db.get(IdentityProfileModel, buyer_agent.owner_identity_id)
    if identity is None:
        return None
    return (identity.bound_wallet_address or "").strip() or None


def _same_ed25519_public_key(registered: str, presented: str) -> bool:
    """Compare Ed25519 public keys tolerant of hex / base64 / 0x-prefix encodings."""
    def _norm(value: str) -> bytes | None:
        value = (value or "").strip()
        if not value:
            return None
        try:
            if value.startswith("0x"):
                return bytes.fromhex(value[2:])
            if len(value) == 64:
                return bytes.fromhex(value)
            return base64.b64decode(value)
        except Exception:
            return None

    a, b = _norm(registered), _norm(presented)
    return a is not None and a == b


@router.post("/{task_id}/sign")
async def sign_contract(
    task_id: str,
    body: SignContractRequest,
    db: AsyncSession = Depends(get_db),
):
    """Collect a buyer (EIP-712) or worker (Ed25519) signature on the termsHash."""
    validate_public_url_segment("task_id", task_id)
    row = await db.get(TaskContractModel, task_id)
    if not row:
        raise HTTPException(404, f"Contract {task_id} not found")
    if not row.terms_hash:
        raise HTTPException(409, "contract has no terms_hash; recreate the contract")

    terms = order_contract.build_terms(_row_to_contract(row))
    if order_contract.terms_hash_hex(terms) != row.terms_hash:
        raise HTTPException(409, "terms_hash mismatch: contract fields changed after creation")

    if body.role == "buyer":
        if row.buyer_signature:
            raise HTTPException(409, "buyer already signed")
        if not body.address:
            raise HTTPException(422, "address is required for buyer signature")
        try:
            order_contract.verify_buyer_signature(
                buyer_address=body.address,
                buyer_signature=body.signature,
                terms_hash=row.terms_hash,
                task_id=task_id,
                chain_id=_order_contract_chain_id(),
                verifying_contract=settings.order_contract_eip712_verifying_contract,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        bound_wallet = await _buyer_bound_wallet(db, row.client_agent_id)
        if not bound_wallet or bound_wallet.lower() != body.address.strip().lower():
            raise HTTPException(422, "buyer address does not match the client agent's bound wallet")
        row.buyer_signature = body.signature
        row.buyer_address = body.address
    else:
        if not row.worker_agent_id:
            raise HTTPException(409, "assign a worker before the worker signs")
        if row.worker_signature:
            raise HTTPException(409, "worker already signed")
        if not body.public_key:
            raise HTTPException(422, "public_key is required for worker signature")
        if not order_contract.verify_worker_signature(
            terms_hash=row.terms_hash,
            signature_b64=body.signature,
            public_key_b64=body.public_key,
        ):
            raise HTTPException(422, "invalid worker signature")
        worker_agent = await db.get(AgentModel, row.worker_agent_id)
        registered_pub = (worker_agent.public_key or "").strip() if worker_agent else ""
        if not registered_pub or not _same_ed25519_public_key(registered_pub, body.public_key):
            raise HTTPException(422, "worker public_key does not match the registered agent key")
        row.worker_signature = body.signature
        row.worker_public_key = body.public_key

    if row.buyer_signature and row.worker_signature:
        row.contract_status = order_contract.STATUS_SIGNED
        if not row.signed_at:
            row.signed_at = datetime.utcnow()
    elif row.buyer_signature or row.worker_signature:
        row.contract_status = order_contract.STATUS_BUYER_SIGNED
    return _row_to_contract(row)


async def _snapshot_contract_version(db: AsyncSession, row: TaskContractModel) -> None:
    """Persist the pre-revision state so the terms version anchored on-chain
    can always be reconstructed for dispute resolution."""
    db.add(
        TaskContractVersionModel(
            task_id=row.task_id,
            version=int(row.version or 1),
            terms_hash=row.terms_hash,
            terms=order_contract.build_terms(_row_to_contract(row)),
            worker_agent_id=row.worker_agent_id,
            contract_status=row.contract_status or "draft",
            buyer_signature=row.buyer_signature,
            buyer_address=row.buyer_address,
            worker_signature=row.worker_signature,
            worker_public_key=row.worker_public_key,
            signed_at=row.signed_at,
        )
    )
    await db.flush()


@router.post("/{task_id}/revise")
async def revise_contract(
    task_id: str,
    body: ReviseContractRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Counter-proposal: bump the version, recompute terms_hash, and require re-signing."""
    validate_public_url_segment("task_id", task_id)
    row = await db.get(TaskContractModel, task_id)
    if not row:
        raise HTTPException(404, f"Contract {task_id} not found")

    state = await PostgresSettlementStore(db).get(task_id)
    if state and getattr(state, "onchain_binding_id", None) is not None:
        raise HTTPException(409, "contract already anchored on-chain; cannot revise")
    if getattr(row, "onchain_binding_id", None) is not None:
        raise HTTPException(409, "contract already anchored on-chain; cannot revise")

    actor_ids = await actor_identity_ids(db, request)
    parties = {row.client_agent_id}
    if row.worker_agent_id:
        parties.add(row.worker_agent_id)
    if actor_ids and not (parties & actor_ids) and not caller_is_privileged(request):
        raise HTTPException(403, "only a contract party may revise")

    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(422, "no fields to revise")
    await _snapshot_contract_version(db, row)
    for field, value in changes.items():
        if field in ("task_id", "client_agent_id"):
            continue
        if field == "expected_output_schema" and value is None:
            continue
        setattr(row, field, value)

    if "escrow_amount" in changes:
        escrow = float(changes["escrow_amount"])
        if escrow < settings.escrow_min_amount - 1e-9 or escrow > settings.escrow_max_amount + 1e-9:
            raise HTTPException(400, "escrow_amount out of range")
        assert_token_precision(escrow, field="escrow_amount")

    row.version = int(row.version or 1) + 1
    row.terms_hash = order_contract.terms_hash_hex(order_contract.build_terms(_row_to_contract(row)))
    row.contract_status = order_contract.STATUS_DRAFT
    row.buyer_signature = None
    row.buyer_address = None
    row.worker_signature = None
    row.worker_public_key = None
    row.signed_at = None
    return _row_to_contract(row)


@router.get("/{task_id}/terms")
async def get_contract_terms(
    task_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    version: int | None = None,
):
    """Return signed order terms + signatures — the ruling artifact for disputes."""
    validate_public_url_segment("task_id", task_id)
    row = await db.get(TaskContractModel, task_id)
    if not row:
        raise HTTPException(404, f"Contract {task_id} not found")
    await require_party_read(
        db,
        request,
        _contract_party_ids(row) | await _settlement_party_ids(db, task_id),
        public_read=bool(settings.task_records_public_read),
    )
    if version is not None:
        hist = (await db.execute(
            select(TaskContractVersionModel).where(
                TaskContractVersionModel.task_id == task_id,
                TaskContractVersionModel.version == version,
            )
        )).scalar_one_or_none()
        if hist is None:
            raise HTTPException(404, f"Contract {task_id} version {version} not found")
        return {
            "task_id": task_id,
            "version": hist.version,
            "terms_hash": hist.terms_hash,
            "contract_status": hist.contract_status,
            "terms": hist.terms,
            "buyer": {"address": hist.buyer_address, "signature": hist.buyer_signature},
            "worker": {
                "agent_id": hist.worker_agent_id,
                "public_key": hist.worker_public_key,
                "signature": hist.worker_signature,
            },
            "signed_at": hist.signed_at.isoformat() if hist.signed_at else None,
            "created_at": hist.created_at.isoformat() if hist.created_at else None,
        }
    contract = _row_to_contract(row)
    return {
        "task_id": row.task_id,
        "terms_hash": row.terms_hash,
        "contract_status": row.contract_status,
        "terms": order_contract.build_terms(contract),
        "buyer": {"address": row.buyer_address, "signature": row.buyer_signature},
        "worker": {
            "agent_id": row.worker_agent_id,
            "public_key": row.worker_public_key,
            "signature": row.worker_signature,
        },
        "signed_at": row.signed_at.isoformat() if row.signed_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("/{task_id}/anchor")
async def get_contract_anchor(
    task_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Dispute-resolution anchor check: does the on-chain binding scopeHash equal
    the signed contract terms_hash? Returns the evidence an arbitrator needs."""
    validate_public_url_segment("task_id", task_id)
    row = await db.get(TaskContractModel, task_id)
    if not row:
        raise HTTPException(404, f"Contract {task_id} not found")
    await require_party_read(
        db,
        request,
        _contract_party_ids(row) | await _settlement_party_ids(db, task_id),
        public_read=bool(settings.task_records_public_read),
    )
    state = await PostgresSettlementStore(db).get(task_id)
    binding_id = getattr(state, "onchain_binding_id", None) if state else None
    if binding_id is None:
        binding_id = getattr(row, "onchain_binding_id", None)
    result: dict = {
        "task_id": task_id,
        "terms_hash": row.terms_hash,
        "onchain_binding_id": binding_id,
        "onchain_scope_hash": None,
        "anchored": False,
        "note": "",
    }
    if not row.terms_hash:
        result["note"] = "contract has no terms_hash"
        return result
    if binding_id is None:
        result["note"] = "binding not yet on-chain"
        return result
    try:
        from services.chain.settlement_adapter import OnChainSettlementAdapter
        chain_scope = OnChainSettlementAdapter().binding_status(binding_id).get("scope_hash")
        result["onchain_scope_hash"] = chain_scope
        expected = order_contract.terms_hash_bytes32(row.terms_hash)
        result["anchored"] = bool(chain_scope and chain_scope.lower() == expected.lower())
        if not result["anchored"]:
            result["note"] = "on-chain scopeHash does not match signed terms_hash"
    except Exception as exc:  # noqa: BLE001
        result["note"] = f"on-chain read failed: {exc}"
    return result


def _contract_party_ids(row: TaskContractModel) -> set[str]:
    ids = {row.client_agent_id}
    if getattr(row, "worker_agent_id", None):
        ids.add(row.worker_agent_id)
    return {i for i in ids if i}


async def _settlement_party_ids(db: AsyncSession, task_id: str) -> set[str]:
    """结算上的买卖双方也算当事人（合同可能还没 assign，但结算已锁定 worker）。"""
    try:
        state = await PostgresSettlementStore(db).get(task_id)
    except Exception:
        return set()
    if state is None:
        return set()
    ids = {state.client_agent_id}
    if state.worker_agent_id:
        ids.add(state.worker_agent_id)
    return {i for i in ids if i}


@router.patch("/{task_id}/assign")
async def assign_worker(
    task_id: str,
    worker_agent_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """指派卖家。

    2026-09-17 复核：这个端点此前**没有任何归属校验** —— 任何调用者都能把任意合同
    的 worker 改成任何人（等于替别人决定「谁来交付」）。现在只有买方本人
    （或平台运维岗）能指派，且不会悄悄覆盖一个已经存在的卖家。
    """
    validate_public_url_segment("task_id", task_id)
    validate_public_url_segment("worker_agent_id", worker_agent_id)
    row = await db.get(TaskContractModel, task_id)
    if not row:
        raise HTTPException(404)
    if worker_agent_id == row.client_agent_id:
        raise HTTPException(
            status_code=409,
            detail="worker_agent_id cannot equal contract client_agent_id (self-assignment)",
        )
    actor_ids = await actor_identity_ids(db, request)
    if actor_ids and row.client_agent_id not in actor_ids and not caller_is_privileged(request):
        raise HTTPException(403, "only the buyer may assign the worker for this contract")
    if row.worker_agent_id and row.worker_agent_id != worker_agent_id:
        raise HTTPException(
            status_code=409,
            detail="contract already has a different assigned worker",
        )
    row.worker_agent_id = worker_agent_id
    return _row_to_contract(row)


def _row_to_contract(row: TaskContractModel) -> TaskContract:
    return TaskContract(
        task_id=row.task_id,
        client_agent_id=row.client_agent_id,
        worker_agent_id=row.worker_agent_id,
        title=row.title,
        description=row.description,
        expected_output_schema=row.expected_output_schema,
        expected_step_count=row.expected_step_count,
        escrow_amount=row.escrow_amount,
        currency=row.currency,
        deadline_at=row.deadline_at,
        quality_standard=row.quality_standard,
        inspection_standard=row.inspection_standard,
        shipment_terms=row.shipment_terms,
        delivery_criteria=row.delivery_criteria,
        penalty=row.penalty,
        arbitration_rules=row.arbitration_rules,
        contract_hash=row.contract_hash,
        terms_hash=row.terms_hash,
        contract_status=row.contract_status or "draft",
        version=row.version or 1,
        buyer_signature=row.buyer_signature,
        buyer_address=row.buyer_address,
        worker_signature=row.worker_signature,
        worker_public_key=row.worker_public_key,
        signed_at=row.signed_at,
        created_at=row.created_at,
    )
