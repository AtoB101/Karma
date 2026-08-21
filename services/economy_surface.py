"""karma8 economy surface config + read aggregation helpers.

Main repo does NOT implement treasury fee/split/ContributionNFT mint gates.
"""
from __future__ import annotations

import os
from typing import Any


def economy_addresses() -> dict[str, str | None]:
    keys = [
        "TREASURY",
        "FEE_BRIDGE",
        "SETTLEMENT_MIRROR",
        "STAKE",
        "GOVERNOR",
        "STAKER_POOL",
        "DEVELOPER_POOL",
        "CONTRIBUTION_NFT",
        "CONTRIBUTOR_REGISTRY",
        "CONTRIBUTION_LEDGER",
        "COCREATION_SCORE_VIEW",
        "KARMA_TOKEN",
        "USDC",
        "KARMA_BILATERAL",
    ]
    out: dict[str, str | None] = {}
    for k in keys:
        out[k] = (os.getenv(k) or os.getenv(f"KARMA8_{k}") or "").strip() or None
    return out


def economy_embed_url(*, tab: str | None = None) -> str:
    host = (os.getenv("KARMA8_ECONOMY_HOST") or os.getenv("ECONOMY_HOST") or "").rstrip("/")
    if not host:
        host = "http://localhost:5173"
    url = f"{host}/?view=miniapp"
    if tab:
        url += f"&tab={tab}"
    return url


def surface_payload(address: str | None = None) -> dict[str, Any]:
    """BFF-facing payload. Live eth_call can be added when RPC + addresses are set."""
    addrs = economy_addresses()
    return {
        "embed_url": economy_embed_url(),
        "embed_rewards_url": economy_embed_url(tab="rewards"),
        "address": (address.lower() if address else None),
        "revenueMode": None,  # filled by eth_call when configured
        "feeBps": None,
        "tier": None,
        "nftWeight": None,
        "pendingPoints": None,
        "earnedUsdc": None,
        "contracts": {
            "treasury": addrs.get("TREASURY"),
            "feeBridge": addrs.get("FEE_BRIDGE"),
            "settlementMirror": addrs.get("SETTLEMENT_MIRROR"),
            "stake": addrs.get("STAKE"),
            "developerPool": addrs.get("DEVELOPER_POOL"),
            "stakerPool": addrs.get("STAKER_POOL"),
            "contributionNft": addrs.get("CONTRIBUTION_NFT"),
            "contributorRegistry": addrs.get("CONTRIBUTOR_REGISTRY"),
            "contributionLedger": addrs.get("CONTRIBUTION_LEDGER"),
            "cocreationScore": addrs.get("COCREATION_SCORE_VIEW"),
            "usdc": addrs.get("USDC"),
            "bilateral": addrs.get("KARMA_BILATERAL"),
        },
        "notes": [
            "Verification never runs on economy surface",
            "buyer==seller GMV credit skipped by SettlementMirror",
            "revenue OFF locks pool claims; fee=0 still collectAndRecord for GMV",
            "ABI source of truth: karma8 frontend/src/lib/abis.ts",
        ],
    }
