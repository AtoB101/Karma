"""Unified buyer commitment: TradeLaunch attestation OR AuthorizationVoucher EIP-712."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import HTTPException

from config.settings import Settings, settings
from services.trade_launch_signing import verify_trade_launch_attestation_signature
from services.voucher_eip712 import verify_authorization_voucher_buyer


def _trade_launch_attestation(progress_rule_spec: dict[str, Any] | None) -> dict[str, Any] | None:
    if not progress_rule_spec:
        return None
    att = progress_rule_spec.get("trade_launch_attestation")
    return att if isinstance(att, dict) else None


def assert_buyer_commitment_for_voucher(
    *,
    buyer_signature: str,
    buyer_wallet_address: str | None,
    progress_rule_spec: dict[str, Any] | None,
    buyer_identity_id: str,
    seller_identity_id: str,
    amount: float,
    bill_credit_amount: float,
    currency: str,
    task_type: str,
    task_description_hash: str,
    progress_rule_hash: str,
    evidence_requirement_hash: str,
    nonce: str,
    expiry_time: datetime,
    cfg: Settings | None = None,
) -> str:
    """
    Validate buyer_signature for voucher create.

    When ``progress_rule_spec.trade_launch_attestation`` is present and trade launch
    EIP-712 is enabled, verifies TradeLaunchIntent (pipeline / unified launch path).

    Otherwise, when ``voucher_require_eip712`` is enabled, verifies AuthorizationVoucher.

    Returns commitment mode: ``trade_launch`` | ``authorization_voucher`` | ``legacy``.
    """
    active = cfg or settings
    att = _trade_launch_attestation(progress_rule_spec)
    if att and active.trade_launch_require_eip712:
        try:
            verify_trade_launch_attestation_signature(
                attestation=att,
                buyer_signature=buyer_signature,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return "trade_launch"

    if active.voucher_require_eip712:
        if not (buyer_wallet_address or "").strip():
            raise HTTPException(
                status_code=400,
                detail="buyer_wallet_address is required when voucher EIP-712 is enforced",
            )
        chain_id = active.voucher_eip712_chain_id or active.testnet_chain_id
        v_contract = (active.voucher_eip712_verifying_contract or "").strip()
        if not v_contract:
            v_contract = "0x0000000000000000000000000000000000000000"
        try:
            verify_authorization_voucher_buyer(
                buyer_wallet_address=buyer_wallet_address,
                buyer_signature=buyer_signature,
                buyer_identity_id=buyer_identity_id,
                seller_identity_id=seller_identity_id,
                amount=amount,
                bill_credit_amount=bill_credit_amount,
                currency=currency,
                task_type=task_type,
                task_description_hash=task_description_hash,
                progress_rule_hash=progress_rule_hash,
                evidence_requirement_hash=evidence_requirement_hash,
                nonce=nonce,
                expiry_time=expiry_time,
                chain_id=int(chain_id),
                verifying_contract=v_contract,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return "authorization_voucher"

    return "legacy"
