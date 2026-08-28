"""karma8 economy surface config + read aggregation helpers.

Main repo does NOT implement treasury fee/split/ContributionNFT mint gates.
Aligned with karma8 deployments/economy-surface.example.json + ECONOMY_SURFACE.md.
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


def miniapp_origins() -> list[str]:
    """Origins to give karma8 as MINIAPP_ORIGIN (CORS / frame-ancestors)."""
    raw = (os.getenv("MINIAPP_ORIGIN") or "").strip()
    defaults = [
        "https://web.telegram.org",
        "https://webk.telegram.org",
        "https://webz.telegram.org",
    ]
    if not raw:
        return defaults
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    # ensure telegram origins present
    for d in defaults:
        if d not in parts:
            parts.append(d)
    return parts


def surface_payload(address: str | None = None) -> dict[str, Any]:
    """BFF-facing payload matching karma8 economy-surface.example.json shape."""
    addrs = economy_addresses()
    chain_id = int(os.getenv("KARMA_SIWE_CHAIN_ID") or os.getenv("CHAIN_ID") or "11155111")
    return {
        "chainId": chain_id,
        "rpcUrl": (os.getenv("RPC_URL") or None),
        "embed_url": economy_embed_url(),
        "embed_rewards_url": economy_embed_url(tab="rewards"),
        "address": (address.lower() if address else None),
        # Live eth_call fills these when RPC + addresses are set
        "revenueMode": None,
        "enableRevenueMode": None,
        "feeBps": None,
        "feeBpsColdStart": 0,
        "tier": None,
        "nftWeight": None,
        "pendingPoints": None,
        "earnedUsdc": None,
        "contracts": {
            "treasury": addrs.get("TREASURY"),
            "feeBridge": addrs.get("FEE_BRIDGE"),
            "settlementMirror": addrs.get("SETTLEMENT_MIRROR"),
            "stake": addrs.get("STAKE"),
            "governor": addrs.get("GOVERNOR"),
            "developerPool": addrs.get("DEVELOPER_POOL"),
            "stakerPool": addrs.get("STAKER_POOL"),
            "contributionNft": addrs.get("CONTRIBUTION_NFT"),
            "contributorRegistry": addrs.get("CONTRIBUTOR_REGISTRY"),
            "contributionLedger": addrs.get("CONTRIBUTION_LEDGER"),
            "cocreationScoreView": addrs.get("COCREATION_SCORE_VIEW"),
            "karmaToken": addrs.get("KARMA_TOKEN"),
            "usdc": addrs.get("USDC"),
            "karmaBilateral": addrs.get("KARMA_BILATERAL"),
            # aliases used by older MiniApp clients
            "cocreationScore": addrs.get("COCREATION_SCORE_VIEW"),
            "bilateral": addrs.get("KARMA_BILATERAL"),
        },
        "embed": {
            "economyHost": (os.getenv("KARMA8_ECONOMY_HOST") or os.getenv("ECONOMY_HOST") or "http://localhost:5173"),
            "miniappUrl": economy_embed_url(),
            "tabs": ["status", "wallet", "rewards", "contrib"],
            "includesVerificationEngine": False,
        },
        "miniapp_origin_for_karma8": miniapp_origins(),
        "notes": [
            "Verification never runs on economy surface",
            "buyer==seller GMV credit skipped by SettlementMirror",
            "revenue OFF locks pool claims; fee=0 still collectAndRecord for GMV",
            "ABI source of truth: karma8 frontend/src/lib/abis.ts or abi/*.json",
            "Fill contracts from karma8 deployments/<network>.json",
            "Tell karma8 MINIAPP_ORIGIN = miniapp_origin_for_karma8",
        ],
    }
