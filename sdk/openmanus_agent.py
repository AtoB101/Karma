"""
Karma Trust Protocol — OpenManus Agent SDK
===========================================
Re-exports the KarmaOpenManusAgent from the agents module.

Usage::

    from karma.sdk import KarmaOpenManusAgent

    agent = KarmaOpenManusAgent(
        agent_id="worker-001",
        hook_layer=hooks,
    )
    result, receipts = await agent.run_task(task_id, task_spec)
"""

# Re-export from the canonical adapter location
from agents.openmanus.adapter import KarmaOpenManusAgent

__all__ = ["KarmaOpenManusAgent"]
