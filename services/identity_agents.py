"""Ensure ledger identities exist as agent rows for contracts/settlement."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from db.models.orm import AgentModel


async def ensure_agent_for_identity(
    db: AsyncSession,
    identity_id: str,
    *,
    role: str,
    name: str | None = None,
) -> AgentModel:
    row = await db.get(AgentModel, identity_id)
    if row:
        return row
    agent_role = "client" if role == "buyer" else "worker"
    row = AgentModel(
        agent_id=identity_id,
        name=name or identity_id,
        role=agent_role,
        public_key=f"pk-{identity_id}",
        capabilities=[],
    )
    db.add(row)
    await db.flush()
    return row
