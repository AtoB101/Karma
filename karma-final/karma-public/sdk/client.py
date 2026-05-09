"""
Karma SDK — KarmaClient
High-level client that wires hook layer, bundle builder,
verification, and settlement into a single interface.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

import httpx

from core.schemas import (
    AgentRole,
    EvidenceBundle,
    ReputationSnapshot,
    SettlementState,
    TaskContract,
    TaskStatus,
    VerificationResult,
)
from core.hooks.hook_layer import InMemoryReceiptStore, KarmaHookLayer, ReceiptStore
from core.evidence.bundle_builder import EvidenceBundleBuilder
from agents.openmanus.adapter import KarmaOpenManusAgent


class KarmaClient:
    """
    High-level SDK client for the Karma Trust Protocol.

    Handles:
    - Agent tool execution with automatic receipt generation
    - Evidence bundle construction and signing
    - Verification submission to runtime
    - Settlement state queries

    Usage
    -----
        client = KarmaClient(
            agent_id="worker-001",
            runtime_url="https://api.karma.xyz",
            api_key="karma_worker-001_secret",
        )
        result = await client.run_task(contract, my_task_fn)
    """

    def __init__(
        self,
        agent_id: str,
        runtime_url: str = "http://localhost:8000",
        api_key: str = "",
        receipt_store: Optional[ReceiptStore] = None,
        timeout: float = 120.0,
    ):
        self.agent_id = agent_id
        self.runtime_url = runtime_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

        self._store = receipt_store or InMemoryReceiptStore()
        self._hooks = KarmaHookLayer(
            agent_id=agent_id,
            receipt_store=self._store,
        )
        self._agent = KarmaOpenManusAgent(
            agent_id=agent_id,
            hook_layer=self._hooks,
        )
        self._builder = EvidenceBundleBuilder(receipt_store=self._store)

    # ------------------------------------------------------------------ #
    # Tool execution
    # ------------------------------------------------------------------ #

    async def run_tool(
        self,
        task_id: str,
        tool_name: str,
        tool_fn: Callable,
        input_data: Any,
        metadata: Optional[dict] = None,
        timeout: Optional[float] = None,
    ):
        """
        Execute one tool call with automatic receipt generation.
        Returns (result, ExecutionReceipt).
        """
        return await self._agent.run_tool(
            task_id=task_id,
            tool_name=tool_name,
            tool_fn=tool_fn,
            input_data=input_data,
            metadata=metadata,
            timeout=timeout,
        )

    # ------------------------------------------------------------------ #
    # Full task lifecycle
    # ------------------------------------------------------------------ #

    async def run_task(
        self,
        contract: TaskContract,
        task_fn: Callable,
    ) -> dict[str, Any]:
        """
        Run a complete task lifecycle:
          1. Execute task_fn (which calls run_tool internally)
          2. Build evidence bundle
          3. Submit for verification
          4. Return result dict with bundle + verification + settlement

        task_fn signature: async (contract, client) -> final_result
        """
        # Execute
        final_result = await task_fn(contract, self)

        # Build bundle
        bundle = await self._builder.build(contract, final_result or {})

        # Submit verification
        verification = await self.submit_verification(bundle, contract)

        return {
            "final_result":   final_result,
            "bundle":         bundle,
            "verification":   verification,
        }

    # ------------------------------------------------------------------ #
    # Runtime API calls
    # ------------------------------------------------------------------ #

    async def submit_verification(
        self,
        bundle: EvidenceBundle,
        contract: TaskContract,
    ) -> VerificationResult:
        """POST /v1/verify"""
        async with self._http() as http:
            resp = await http.post(
                f"{self.runtime_url}/v1/verify",
                json={
                    "bundle":   bundle.model_dump(mode="json"),
                    "contract": contract.model_dump(mode="json"),
                },
            )
            resp.raise_for_status()
            return VerificationResult(**resp.json())

    async def get_settlement(self, task_id: str) -> SettlementState:
        """GET /v1/settlement/{task_id}"""
        async with self._http() as http:
            resp = await http.get(f"{self.runtime_url}/v1/settlement/{task_id}")
            resp.raise_for_status()
            return SettlementState(**resp.json())

    async def get_reputation(self, agent_id: str) -> ReputationSnapshot:
        """GET /v1/reputation/{agent_id}"""
        async with self._http() as http:
            resp = await http.get(f"{self.runtime_url}/v1/reputation/{agent_id}")
            resp.raise_for_status()
            return ReputationSnapshot(**resp.json())

    async def get_token(self, agent_id: str, api_key: str) -> str:
        """POST /v1/auth/token — returns JWT access token."""
        async with self._http() as http:
            resp = await http.post(
                f"{self.runtime_url}/v1/auth/token",
                json={"agent_id": agent_id, "api_key": api_key},
            )
            resp.raise_for_status()
            return resp.json()["access_token"]

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _http(self) -> httpx.AsyncClient:
        headers: dict[str, str] = {}
        if self.api_key:
            headers["X-Karma-Api-Key"] = self.api_key
        return httpx.AsyncClient(timeout=self.timeout, headers=headers)

    def reset_task(self, task_id: str) -> None:
        """Clear receipts and step counter for a task (call between retries)."""
        self._agent.reset(task_id)
