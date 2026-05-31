"""KarmaBilateral MCP tools for OpenClaw — lock/bind/settle via BFF API."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

from karma_openclaw.http_client import api_get, api_post


def register_bilateral_tools(mcp):
    """Register KarmaBilateral tools on the MCP server."""

    @mcp.tool()
    async def karma_bilateral_lock(token: str, amount: str, role: str = "buyer") -> dict[str, Any]:
        """Lock USDC into KarmaBilateral and mint a Bill Token.

        Both buyer AND agent must call this before any task begins.
        This replaces the old lockFunds flow.

        Args:
            token: ERC-20 token address (use USDC address for testnet)
            amount: Amount in base units, e.g. '10000000' for 10 USDC
            role: 'buyer' or 'agent'
        """
        return await api_post("/v1/bilateral/lock", {
            "token": token,
            "amount": int(amount),
            "role": role,
        })

    @mcp.tool()
    async def karma_bilateral_bind(buyer_bill_id: int, agent_bill_id: int, scope_description: str) -> dict[str, Any]:
        """Bilaterally bind buyer + agent Bill Tokens. Both sides freeze.

        Must be called AFTER both parties have locked (karma_bilateral_lock).
        This enters the BOUND state — bills cannot be withdrawn until settled.

        Args:
            buyer_bill_id: The bill ID from buyer's lock call
            agent_bill_id: The bill ID from agent's lock call
            scope_description: Human-readable task scope, e.g. 'search:latest-pricing'
        """
        import hashlib
        scope_hash = "0x" + hashlib.sha256(scope_description.encode()).hexdigest()
        return await api_post("/v1/bilateral/bind", {
            "buyer_bill_id": buyer_bill_id,
            "agent_bill_id": agent_bill_id,
            "scope_hash": scope_hash,
        })

    @mcp.tool()
    async def karma_bilateral_settle(binding_id: int, proof_description: str) -> dict[str, Any]:
        """Submit settlement proof for a binding. Enters FINALIZING state.

        After the settle delay and dispute window pass, call
        karma_bilateral_finalize to complete settlement.

        Args:
            binding_id: The binding ID from the bind call
            proof_description: What was delivered, e.g. 'ipfs://Qm...evidence'
        """
        import hashlib
        proof_hash = "0x" + hashlib.sha256(proof_description.encode()).hexdigest()
        return await api_post("/v1/bilateral/settle", {
            "binding_id": binding_id,
            "proof_hash": proof_hash,
        })

    @mcp.tool()
    async def karma_bilateral_finalize(binding_id: int) -> dict[str, Any]:
        """Finalize settlement after dispute window closes. Burns bills, releases USDC.

        Can only be called after the dispute window has passed since settle().
        """
        return await api_post(f"/v1/bilateral/finalize/{binding_id}", {})

    @mcp.tool()
    async def karma_bilateral_status(binding_id: int) -> dict[str, Any]:
        """Query the full status of a binding — state, bill states, USDC locked.

        Returns:
            binding_id, state, bill_states (list), can_settle, can_dispute,
            can_finalize, usdc_locked, settle_after
        """
        return await api_get(f"/v1/bilateral/status/{binding_id}")

    @mcp.tool()
    async def karma_bilateral_dispute(binding_id: int, reason: str) -> dict[str, Any]:
        """Raise a dispute on a binding in FINALIZING state.

        Only the buyer can dispute. Must be within the dispute window.

        Args:
            binding_id: The binding to dispute
            reason: Human-readable reason for dispute
        """
        import hashlib
        evidence_hash = "0x" + hashlib.sha256(reason.encode()).hexdigest()
        # Dispute via direct contract call through BFF
        return await api_post(f"/v1/bilateral/dispute/{binding_id}", {
            "evidence_hash": evidence_hash,
        })
