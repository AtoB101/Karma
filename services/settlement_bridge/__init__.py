"""Settlement → FeeBridge orchestration helpers (main repo).

Bilateral.settle already calls quoteFee then collectAndRecord internally.
These helpers build the expected calldata / field conventions for BFF,
relayers, and MiniApp finalize responses.

Rules (karma8 KARMA_MAIN_HANDOFF):
- orderId = bytes32(bindingId) — unique, no replay
- developer = builder_address (via Bilateral.setBindingDeveloper)
- feeUsdc MUST equal quoteFee result (else FeeBridge FeeMismatch)
- cold-start enableRevenueMode=false → fee=0 still collectAndRecord (GMV)
- buyer==seller → self_deal; Mirror skips developer GMV
"""
from __future__ import annotations

from typing import Any


# keccak selectors (for documentation / eth_call builders)
QUOTE_FEE_SELECTOR = "0x"  # quoteFee(address,uint256) — client uses ABI
COLLECT_AND_RECORD_SIG = "collectAndRecord(bytes32,address,address,address,uint256,uint256)"
QUOTE_FEE_SIG = "quoteFee(address,uint256)"
SET_BINDING_DEVELOPER_SIG = "setBindingDeveloper(uint256,address)"
SETTLE_SIG = "settle(uint256,bytes32)"


def order_id_bytes32(binding_id: int) -> str:
    """Unique FeeBridge orderId = bytes32(bindingId)."""
    if binding_id < 0:
        raise ValueError("binding_id must be >= 0")
    return "0x" + int(binding_id).to_bytes(32, "big").hex()


def is_self_deal(buyer: str | None, seller: str | None) -> bool:
    if not buyer or not seller:
        return False
    return buyer.lower() == seller.lower()


def resolve_developer(*, builder_address: str | None, seller_wallet: str | None) -> str | None:
    """BUILDER attribution preferred; fall back to seller (on-chain default)."""
    if builder_address:
        return builder_address.lower()
    if seller_wallet:
        return seller_wallet.lower()
    return None


def fee_bridge_settle_plan(
    *,
    binding_id: int,
    buyer: str | None,
    seller: str | None,
    builder_address: str | None,
    amount_usdc: str | int,
    proof_hash: str | None = None,
    quoted_fee_usdc: str | int | None = None,
) -> dict[str, Any]:
    """Build the settle → FeeBridge plan for clients/relayers.

    On-chain path (preferred):
      1. setBindingDeveloper(bindingId, developer) if builder set
      2. Bilateral.settle(bindingId, proofHash)
         → internal quoteFee(developer, amount)
         → collectAndRecord(..., fee) with fee == quote (or 0 cold-start)

    Do NOT call FeeBridge.collectAndRecord from MiniApp with a guessed fee.
    """
    developer = resolve_developer(builder_address=builder_address, seller_wallet=seller)
    self_deal = is_self_deal(buyer, seller)
    order_id = order_id_bytes32(binding_id)
    amount = str(amount_usdc)

    plan: dict[str, Any] = {
        "orderId": order_id,
        "binding_id": binding_id,
        "self_deal": self_deal,
        "self_deal_note": (
            "buyer==seller: do not treat as normal developer GMV business; "
            "SettlementMirror skips developer GMV credit"
            if self_deal
            else None
        ),
        "developer": developer,
        "amountUsdc": amount,
        "steps": [
            {
                "step": 1,
                "contract": "KarmaBilateral",
                "method": SET_BINDING_DEVELOPER_SIG,
                "args": {"bindingId": binding_id, "developer": developer},
                "required": bool(builder_address),
                "note": "Sets FeeBridge.developer = builder_address; skip if unset (seller default)",
            },
            {
                "step": 2,
                "contract": "KarmaBilateral",
                "method": SETTLE_SIG,
                "args": {"bindingId": binding_id, "proofHash": proof_hash},
                "note": (
                    "Internal: quoteFee(developer, amount) then "
                    "collectAndRecord(orderId,buyer,seller,developer,amount,fee) "
                    "with fee exactly equal to quote (FeeMismatch otherwise). "
                    "Cold-start fee=0 still collectAndRecord for GMV."
                ),
            },
        ],
        "fee_bridge": {
            "quoteFee": {
                "signature": QUOTE_FEE_SIG,
                "developer": developer,
                "amountUsdc": amount,
            },
            "collectAndRecord": {
                "signature": COLLECT_AND_RECORD_SIG,
                "orderId": order_id,
                "buyer": (buyer.lower() if buyer else None),
                "seller": (seller.lower() if seller else None),
                "developer": developer,
                "amountUsdc": amount,
                "feeUsdc": (
                    str(quoted_fee_usdc)
                    if quoted_fee_usdc is not None
                    else "MUST_EQUAL_quoteFee_RESULT"
                ),
                "fee_rule": "fee MUST equal quoteFee return value (FeeMismatch if not)",
                "cold_start": "enableRevenueMode=false → fee=0; still call collectAndRecord",
            },
        },
        "admin_wiring": {
            "setTreasury": "Bilateral.setTreasury(TREASURY) — onlyAdmin",
            "setFeeBridge": "Bilateral.setFeeBridge(FEE_BRIDGE) — onlyAdmin",
            "fee_bridge_core": "FeeBridge.core MUST == Bilateral address",
        },
    }
    return plan
