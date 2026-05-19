"""
Karma Trust Protocol — OpenClaw Agent SDK
==========================================
Drop-in wrapper for OpenClaw agents that instruments every tool call
with Karma execution receipts, handoff validation, and settlement awareness.

Usage (inside an OpenClaw agent)::

    from karma.sdk import KarmaOpenClawAgent
    from karma.sdk.integrations import discover_and_connect

    # One-click: auto-discover Karma endpoint from OpenClaw env / metadata
    agent = await discover_and_connect(agent_id="worker-001")

    # Or explicit:
    agent = KarmaOpenClawAgent(
        agent_id="worker-001",
        runtime_url="http://localhost:8000",
        api_key="karma_worker-001_...",
    )

    # Wrap any tool call:
    result, receipt = await agent.run_tool(
        task_id="task-42",
        tool_name="browser.navigate",
        tool_fn=navigate_fn,
        input_data={"url": "https://example.com"},
    )

    # Check automation readiness:
    ready = await agent.check_automation_readiness()
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from core.schemas import ExecutionReceipt
from core.hooks.hook_layer import (
    ExecutionReceiptExtensionConcrete,
    InMemoryReceiptStore,
    KarmaHookLayer,
    ReceiptSigner,
)
from sdk.adapters import MCPExecutionAdapter

logger = logging.getLogger(__name__)


class KarmaOpenClawAgent:
    """
    Drop-in Karma wrapper for OpenClaw agents.

    Instruments every tool call with:
    - Execution receipt generation (MCP template)
    - Receipt signing (when signer provided)
    - Automation readiness checks
    - Handoff validation

    Parameters
    ----------
    agent_id:       Unique agent identity in Karma network.
    runtime_url:    Karma API base URL (e.g. http://localhost:8000).
    api_key:        Karma API key (karma_<agent>_<secret>).
    hook_layer:     Pre-configured KarmaHookLayer (optional — created if omitted).
    signer:         ReceiptSigner for cryptographic signatures (optional).
    """

    def __init__(
        self,
        agent_id: str,
        runtime_url: str = "http://localhost:8000",
        api_key: str = "",
        hook_layer: Optional[KarmaHookLayer] = None,
        signer: Optional[ReceiptSigner] = None,
    ):
        self.agent_id = agent_id
        self.runtime_url = runtime_url.rstrip("/")
        self.api_key = api_key

        self._client = None  # lazy-loaded KarmaClient

        if hook_layer is not None:
            self.hook_layer = hook_layer
        else:
            self.hook_layer = KarmaHookLayer(
                agent_id=agent_id,
                receipt_store=InMemoryReceiptStore(),
                signer=signer,
            )

        self._receipts: dict[str, list[ExecutionReceipt]] = {}
        self._step_counter: dict[str, int] = {}

    # ── Tool execution ────────────────────────────────────────

    async def run_tool(
        self,
        task_id: str,
        tool_name: str,
        tool_fn: Callable,
        input_data: Any,
        mcp_server_id: str = "openclaw",
        metadata: Optional[dict[str, Any]] = None,
        timeout: Optional[float] = None,
        extension: Optional[ExecutionReceiptExtensionConcrete] = None,
    ) -> tuple[Any, ExecutionReceipt]:
        """
        Execute a single tool call with Karma instrumentation.

        Returns (tool_result, signed_execution_receipt).
        """
        self._step_counter[task_id] = self._step_counter.get(task_id, 0) + 1
        step_index = self._step_counter[task_id]

        result, receipt = await self.hook_layer.run_tool(
            task_id=task_id,
            tool_name=f"{mcp_server_id}.{tool_name}",
            tool_fn=tool_fn,
            input_data=input_data,
            metadata=metadata or {},
            timeout=timeout,
            extension=extension,
        )

        self._receipts.setdefault(task_id, []).append(receipt)
        return result, receipt

    def run_tool_sync(
        self,
        task_id: str,
        tool_name: str,
        result: Any,
        input_data: Any,
        success: bool = True,
        mcp_server_id: str = "openclaw",
        error_message: Optional[str] = None,
    ) -> ExecutionReceipt:
        """
        Record a tool call that already completed (no wrapping needed).

        Useful for tools that ran outside the hook layer.
        """
        self._step_counter[task_id] = self._step_counter.get(task_id, 0) + 1
        step_index = self._step_counter[task_id]
        started = datetime.now(timezone.utc)
        ended = datetime.now(timezone.utc)

        receipt = MCPExecutionAdapter.build(
            task_id=task_id,
            agent_id=self.agent_id,
            step_index=step_index,
            mcp_server_id=mcp_server_id,
            tool_name=tool_name,
            tool_input=input_data,
            tool_output=result,
            started_at=started,
            ended_at=ended,
            success=success,
            error_message=error_message,
        )

        self._receipts.setdefault(task_id, []).append(receipt)
        return receipt

    # ── Receipt management ────────────────────────────────────

    def get_receipts(self, task_id: str) -> list[ExecutionReceipt]:
        """Return all receipts collected for a task."""
        return self._receipts.get(task_id, [])

    def get_receipt_count(self, task_id: str) -> int:
        """Return receipt count for a task."""
        return len(self._receipts.get(task_id, []))

    def reset(self, task_id: str) -> None:
        """Clear collected receipts and step counter for a task."""
        self._receipts.pop(task_id, None)
        self._step_counter.pop(task_id, None)
        self.hook_layer.reset_task(task_id)

    # ── HTTP client (lazy) ───────────────────────────────────

    def _get_client(self):
        """Lazy-init KarmaClient for API calls."""
        if self._client is None:
            from sdk.client import KarmaClient
            self._client = KarmaClient(
                agent_id=self.agent_id,
                runtime_url=self.runtime_url,
                api_key=self.api_key,
            )
        return self._client

    async def _api_get(self, path: str) -> dict[str, Any]:
        """Raw GET to Karma public API with api_key header."""
        import httpx
        url = self.runtime_url + path
        headers = {"X-Karma-Api-Key": self.api_key, "Accept": "application/json"}
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.json()

    async def _api_post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        """Raw POST to Karma public API with api_key header."""
        import httpx
        url = self.runtime_url + path
        headers = {
            "X-Karma-Api-Key": self.api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            return resp.json()

    # ── Automation readiness ──────────────────────────────────

    async def check_automation_readiness(self) -> dict[str, Any]:
        """
        Check if this agent is cleared for automated execution.

        Calls GET /v1/openclaw/automation-readiness on the Karma API.
        """
        try:
            return await self._api_get("/v1/openclaw/automation-readiness")
        except Exception as exc:
            logger.warning("automation-readiness check failed: %s", exc)
            return {"ready": False, "error": str(exc)}

    async def get_handoff_draft(self, task_id: str) -> dict[str, Any]:
        """Get the handoff draft for a task from Karma API."""
        return await self._api_get(f"/v1/openclaw/handoff-draft?task_id={task_id}")

    async def confirm_handoff(self, task_id: str) -> dict[str, Any]:
        """Confirm handoff server-side (POST /v1/openclaw/handoff-confirm)."""
        return await self._api_post("/v1/openclaw/handoff-confirm", {
            "task_id": task_id,
            "agent_id": self.agent_id,
        })

    # ── Submit receipts to API ────────────────────────────────

    async def submit_receipt(self, receipt: ExecutionReceipt) -> dict[str, Any]:
        """Submit an execution receipt to Karma API."""
        return await self._api_post("/v1/receipts", receipt.model_dump(mode="json"))

    async def submit_all_receipts(self, task_id: str) -> list[dict[str, Any]]:
        """Submit all collected receipts for a task."""
        results = []
        for receipt in self._receipts.get(task_id, []):
            results.append(await self.submit_receipt(receipt))
        return results

    # ── Convenience: one-click full pipeline ──────────────────

    async def one_click_verify_and_settle(
        self,
        task_id: str,
        contract: dict[str, Any],
        handoff_json: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Full verification + settlement pipeline (one call).

        1. Validate handoff (if provided)
        2. Check automation readiness
        3. Submit all receipts
        4. Submit verification
        5. Return settlement status
        """
        result: dict[str, Any] = {"task_id": task_id, "steps": {}}

        # 1. Handoff
        if handoff_json:
            try:
                handoff = json.loads(handoff_json)
                result["steps"]["handoff"] = {"ok": True, "handoff": handoff}
            except Exception as exc:
                result["steps"]["handoff"] = {"ok": False, "error": str(exc)}
                return result

        # 2. Readiness
        result["steps"]["readiness"] = await self.check_automation_readiness()

        # 3. Receipts
        receipt_results = await self.submit_all_receipts(task_id)
        result["steps"]["receipts"] = {
            "count": len(receipt_results),
            "submitted": receipt_results,
        }

        # 4. Verification
        verification = await self._api_post("/v1/verify", {
            "bundle": {"receipts": self._serialize_receipts(task_id)},
            "contract": contract,
        })
        result["steps"]["verification"] = verification

        # 5. Settlement status
        settlement = await self._api_get(f"/v1/settlement/{task_id}")
        result["steps"]["settlement"] = settlement

        return result

    def _serialize_receipts(self, task_id: str) -> list[dict[str, Any]]:
        return [r.model_dump(mode="json") for r in self._receipts.get(task_id, [])]

    # ── Repr ──────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"KarmaOpenClawAgent(agent_id={self.agent_id!r}, "
            f"runtime={self.runtime_url!r})"
        )
