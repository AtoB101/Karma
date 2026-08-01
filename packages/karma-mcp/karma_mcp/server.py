"""
karma_mcp.server — KarmaBilateral MCP stdio server.

Required environment variables:
    KARMA_RPC_URL       JSON-RPC endpoint
    KARMA_PRIVATE_KEY   hex private key (0x-prefixed)
    KARMA_CONTRACT      KarmaBilateral contract address

Optional:
    KARMA_GAS           gas limit per tx (default 300000)

Run:
    karma-mcp

Tools exposed:
    karma_discover_for_intent  user goal → find Karma merchants/agents
    karma_fulfill_intent       discover → negotiate → voucher → settle spine
    karma_lock          lock USDC → mint Bill Token
    karma_bind          bilateral bind two Bill Tokens → Binding
    karma_settle        settle Binding → burn bills, release USDC
    karma_unlock        withdraw MINTED bill before bind
    karma_get_bill      read Bill Token state
    karma_get_binding   read Binding state
    karma_check_invariant  verify totalBillSupply == totalLocked
"""

from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from karma_mcp.chain import (
    chain_bind,
    chain_check_invariant,
    chain_get_bill,
    chain_get_binding,
    chain_lock,
    chain_settle,
    chain_unlock,
)

# ── Server instance ───────────────────────────────────────────────────────────

mcp = FastMCP(
    "karma-mcp",
    instructions=(
        "Karma MCP server — discover merchants, then lock/bind/settle agent payments.\n"
        "\n"
        "Assistant flow:\n"
        "  0. karma_fulfill_intent — preferred: NL goal → discover → voucher → settle spine.\n"
        "  1. Or karma_discover_for_intent then manual negotiate.\n"
        "  2. On-chain: karma_lock → karma_bind → karma_settle for bilateral bill tokens.\n"
        "\n"
        "Invariant: totalBillSupply[token] == totalLocked[token] at all times.\n"
        "BOUND bills cannot be withdrawn, transferred, or re-bound until settled.\n"
        "\n"
        "Required env: KARMA_RPC_URL, KARMA_PRIVATE_KEY, KARMA_CONTRACT"
    ),
)

# ─────────────────────────────────────────────────────────────────────────────
#  Core three tools
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def karma_lock(token: str, amount: int, auto_approve: bool = True) -> dict[str, Any]:
    """
    Lock ERC-20 tokens (e.g. USDC) and mint a Bill Token (SBT) to the caller.

    Both demand-side (user/buyer) and supply-side (agent/seller) must call this
    independently before a bilateral bind can happen.

    Args:
        token:        ERC-20 contract address (must be allowlisted in KarmaBilateral)
        amount:       Amount in token base units (e.g. 100_000_000 for 100 USDC @ 6 decimals)
        auto_approve: Send ERC-20 approve tx automatically before locking (default True)

    Returns:
        {tx_hash, status, bill_id}

    Bill Token states after this call:
        MINTED → can bind or unlock (withdraw)
    """
    return chain_lock(token, amount, auto_approve)


@mcp.tool()
def karma_bind(
    buyer_bill_id: int,
    agent_bill_id: int,
    scope_hash: str,
) -> dict[str, Any]:
    """
    Bilaterally bind a buyer Bill Token and an agent Bill Token into a Binding.

    Both bills transition MINTED → BOUND atomically.
    BOUND bills are frozen: they cannot be withdrawn, transferred, or re-bound
    until the Binding is settled, disputed, or timed out.

    Args:
        buyer_bill_id: Bill Token ID held by the demand side (user / buyer)
        agent_bill_id: Bill Token ID held by the supply side (agent / seller)
        scope_hash:    Hex-encoded 32-byte keccak256 of the task scope / agreement
                       (e.g. keccak256 of the task description JSON)

    Returns:
        {tx_hash, status, binding_id}

    Caller must own buyer_bill_id.
    Both bills must be from the same token type and different owners.
    """
    return chain_bind(buyer_bill_id, agent_bill_id, scope_hash)


@mcp.tool()
def karma_settle(binding_id: int, proof_hash: str) -> dict[str, Any]:
    """
    Settle a Binding: verify proof, burn both Bill Tokens, release USDC atomically.

    This is the terminal happy path. After settle:
      - Both Bill Tokens are BURNED (supply decreases)
      - USDC is released to each owner (locked amount decreases)
      - Invariant maintained: totalBillSupply[token] == totalLocked[token]

    Args:
        binding_id: ID of the Binding to settle (must be ACTIVE or PENDING)
        proof_hash: Hex-encoded 32-byte keccak256 of execution proof / evidence CID

    Returns:
        {tx_hash, status}

    Callable by buyer or agent. Dispute window must have passed (default 30 min).
    For disputes use karma_dispute and karma_resolve_dispute (admin only).
    """
    return chain_settle(binding_id, proof_hash)

# ─────────────────────────────────────────────────────────────────────────────
#  Supporting tools
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def karma_unlock(bill_id: int) -> dict[str, Any]:
    """
    Withdraw a MINTED (unbound) Bill Token and reclaim locked funds.

    Only callable on MINTED bills. Reverts if bill is BOUND — funds are locked
    until settle / dispute / timeout.

    Args:
        bill_id: Bill Token ID to unlock

    Returns:
        {tx_hash, status}
    """
    return chain_unlock(bill_id)


@mcp.tool()
def karma_get_bill(bill_id: int) -> dict[str, Any]:
    """
    Read the current state of a Bill Token.

    Returns:
        {bill_id, owner, token, amount, state, minted_at}

    state is one of: MINTED | BOUND | BURNED
    """
    return chain_get_bill(bill_id)


@mcp.tool()
def karma_get_binding(binding_id: int) -> dict[str, Any]:
    """
    Read the current state of a Binding.

    Returns:
        {binding_id, buyer_bill_id, agent_bill_id, scope_hash, state,
         created_at, settle_after, proof_hash, disputed_at, dispute_initiator}

    state is one of: ACTIVE | PENDING | SETTLED | DISPUTED | REFUNDED
    """
    return chain_get_binding(binding_id)


@mcp.tool()
def karma_check_invariant(token: str) -> dict[str, Any]:
    """
    Verify the global protocol invariant for a token on-chain:
        totalBillSupply[token] == totalLocked[token]

    Returns:
        {token, invariant_ok: bool}

    invariant_ok should always be True. If False, the contract has a bug.
    """
    return chain_check_invariant(token)


@mcp.tool()
def karma_fulfill_intent(
    requirement_text: str,
    buyer_identity_id: str,
    amount: float = 0.0,
    auto_complete: bool = False,
    confirmation_session_id: str = "",
    require_owner_confirmation: bool = True,
) -> dict[str, Any]:
    """
    End-to-end: understand intent → discover → owner Yes/No (when required) →
    negotiate → voucher → settlement start → optional auto evidence+settle.

    This is the primary assistant tool for "user asked me to do X".
    In production, first call often returns status=awaiting_owner_confirmation
    with owner_prompt_zh — show that to the owner, then decide via
    /v1/confirmations/sessions/{id}/decide and retry with confirmation_session_id.
    Use require_owner_confirmation=false only for demos.
    """
    import httpx

    payload: dict[str, Any] = {
        "requirement_text": requirement_text,
        "buyer_identity_id": buyer_identity_id,
        "auto_complete": auto_complete,
        "negotiate_a2a": True,
        "auto_fund_capacity": True,
        "require_owner_confirmation": require_owner_confirmation,
    }
    if amount and amount > 0:
        payload["amount"] = amount
    if confirmation_session_id:
        payload["confirmation_session_id"] = confirmation_session_id

    headers: dict[str, str] = {"Content-Type": "application/json"}
    api_key = os.getenv("KARMA_API_KEY", "")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        headers["X-API-Key"] = api_key

    api_base = os.getenv("KARMA_API_BASE", "").rstrip("/")
    if not api_base:
        return {"error": "KARMA_API_BASE is required for karma_fulfill_intent"}
    try:
        resp = httpx.post(
            f"{api_base}/v1/orchestration/fulfill-intent",
            json=payload,
            headers=headers,
            timeout=60,
        )
        if resp.is_success:
            return resp.json()
        return {"error": f"fulfill failed: HTTP {resp.status_code}", "detail": resp.text[:800]}
    except httpx.HTTPError as exc:
        return {"error": f"fulfill unreachable: {exc}"}


@mcp.tool()
def karma_discover_for_intent(
    requirement_text: str,
    buyer_identity_id: str = "",
    amount: float = 0.0,
    limit: int = 10,
) -> dict[str, Any]:
    """
    Understand a user's goal and discover Karma agents/merchants that can fulfill it.

    Call this first when the user describes a task (e.g. order food, book a flight).
    Returns ranked candidates + a trade_launch_hint. Then negotiate via A2A and
    settle with karma_lock / karma_bind / karma_settle (or the trade/voucher API).

    Uses KARMA_API_BASE (+ optional KARMA_API_KEY). Falls back to A2A bridge
    /a2a/discover when A2A_BRIDGE_URL is set.
    """
    import httpx

    payload: dict[str, Any] = {
        "requirement_text": requirement_text,
        "limit": limit,
    }
    if buyer_identity_id:
        payload["buyer_identity_id"] = buyer_identity_id
    if amount and amount > 0:
        payload["amount"] = amount

    headers: dict[str, str] = {"Content-Type": "application/json"}
    api_key = os.getenv("KARMA_API_KEY", "")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        headers["X-API-Key"] = api_key

    api_base = os.getenv("KARMA_API_BASE", "").rstrip("/")
    if api_base:
        try:
            resp = httpx.post(
                f"{api_base}/v1/discovery/intent",
                json=payload,
                headers=headers,
                timeout=15,
            )
            if resp.is_success:
                return resp.json()
        except httpx.HTTPError:
            pass

    bridge = os.getenv("A2A_BRIDGE_URL", "http://localhost:8080").rstrip("/")
    try:
        resp = httpx.post(f"{bridge}/a2a/discover", json=payload, timeout=15)
        if resp.is_success:
            return resp.json()
        return {"error": f"discover failed: HTTP {resp.status_code}", "detail": resp.text[:500]}
    except httpx.HTTPError as exc:
        return {"error": f"discover unreachable: {exc}"}


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    # Discovery-only assistants may run without chain keys; settlement tools still need them.
    if os.getenv("KARMA_MCP_DISCOVERY_ONLY", "0").strip().lower() not in {"1", "true", "yes"}:
        _require_env()
    mcp.run(transport="stdio")


def _require_env() -> None:
    missing = [v for v in ("KARMA_RPC_URL", "KARMA_PRIVATE_KEY", "KARMA_CONTRACT") if not os.getenv(v)]
    if missing:
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing)}\n"
            "Set KARMA_RPC_URL, KARMA_PRIVATE_KEY, and KARMA_CONTRACT before running karma-mcp.\n"
            "Or set KARMA_MCP_DISCOVERY_ONLY=1 to expose discover without chain keys."
        )


if __name__ == "__main__":
    main()
