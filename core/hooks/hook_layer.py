"""
Karma Trust Protocol — Hook Layer (Public Interface)
=====================================================
Insert Karma middleware around every tool call your agent makes.
This generates signed ExecutionReceipts automatically.

Usage
-----
    from karma.hooks import KarmaHookLayer, ToolCallContext
    from karma.receipts import InMemoryReceiptStore

    store = InMemoryReceiptStore()
    hooks = KarmaHookLayer(agent_id="worker-001", receipt_store=store)

    result, receipt = await hooks.run_tool(
        task_id="task-abc",
        tool_name="caption.generate",
        tool_fn=my_caption_fn,
        input_data={"image_url": "https://..."},
    )
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from datetime import datetime
from typing import Any, Callable, Optional

from core.schemas import ExecutionReceipt, ToolStatus


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def sha256_of(data: Any) -> str:
    """Return SHA-256 hex digest of any serialisable value."""
    if isinstance(data, bytes):
        raw = data
    elif isinstance(data, str):
        raw = data.encode()
    else:
        raw = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


# ---------------------------------------------------------------------------
# Tool Call Context
# ---------------------------------------------------------------------------

class ToolCallContext:
    """
    Mutable state carried through a single tool invocation.
    Attach metadata here inside before-hooks.
    """
    def __init__(
        self,
        task_id: str,
        agent_id: str,
        step_index: int,
        tool_name: str,
    ):
        self.task_id = task_id
        self.agent_id = agent_id
        self.step_index = step_index
        self.tool_name = tool_name
        self.input_payload: Any = None
        self.output_payload: Any = None
        self.started_at: Optional[datetime] = None
        self.ended_at: Optional[datetime] = None
        self.status: ToolStatus = ToolStatus.SUCCESS
        self.error_message: Optional[str] = None
        self.metadata: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Receipt Store Interface
# ---------------------------------------------------------------------------

class ReceiptStore:
    """
    Abstract receipt persistence layer.
    Implement this to plug in PostgreSQL, Redis, or S3 backends.
    """

    async def save(self, receipt: ExecutionReceipt) -> None:
        """Persist a receipt."""
        raise NotImplementedError

    async def get(self, receipt_id: str) -> Optional[ExecutionReceipt]:
        """Retrieve a single receipt by ID."""
        raise NotImplementedError

    async def list_by_task(self, task_id: str) -> list[ExecutionReceipt]:
        """Return all receipts for a given task, ordered by step_index."""
        raise NotImplementedError


class InMemoryReceiptStore(ReceiptStore):
    """
    Development / testing receipt store.
    Not suitable for production — data is lost on restart.
    """

    def __init__(self) -> None:
        self._store: dict[str, ExecutionReceipt] = {}

    async def save(self, receipt: ExecutionReceipt) -> None:
        self._store[receipt.receipt_id] = receipt

    async def get(self, receipt_id: str) -> Optional[ExecutionReceipt]:
        return self._store.get(receipt_id)

    async def list_by_task(self, task_id: str) -> list[ExecutionReceipt]:
        results = [r for r in self._store.values() if r.task_id == task_id]
        return sorted(results, key=lambda r: r.step_index)


# ---------------------------------------------------------------------------
# Hook Layer
# ---------------------------------------------------------------------------

class KarmaHookLayer:
    """
    Wraps every tool call to produce a signed ExecutionReceipt.

    Attach before/after hooks for custom telemetry or logging.
    The signing logic calls out to the Karma runtime — it is not
    embedded in this public module.
    """

    def __init__(
        self,
        agent_id: str,
        receipt_store: ReceiptStore,
        signer: Optional["ReceiptSigner"] = None,
        default_timeout: float = 60.0,
    ):
        self.agent_id = agent_id
        self.receipt_store = receipt_store
        self.signer = signer
        self.default_timeout = default_timeout
        self._step_counters: dict[str, int] = {}
        self._before_hooks: list[Callable] = []
        self._after_hooks: list[Callable] = []

    # --- Hook registration --------------------------------------------------

    def on_before(self, fn: Callable) -> None:
        """Register a coroutine called before tool execution. Receives ctx."""
        self._before_hooks.append(fn)

    def on_after(self, fn: Callable) -> None:
        """Register a coroutine called after tool execution. Receives ctx, receipt."""
        self._after_hooks.append(fn)

    # --- Execution ----------------------------------------------------------

    async def run_tool(
        self,
        task_id: str,
        tool_name: str,
        tool_fn: Callable,
        input_data: Any,
        timeout: Optional[float] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> tuple[Any, ExecutionReceipt]:
        """
        Execute a tool and return (result, receipt).

        Parameters
        ----------
        task_id:    The task this call belongs to.
        tool_name:  Logical name of the tool (e.g. "caption.generate").
        tool_fn:    Sync or async callable.
        input_data: Anything JSON-serialisable.
        timeout:    Override default timeout (seconds).
        metadata:   Extra fields embedded in the receipt.
        """
        step = self._next_step(task_id)
        ctx = ToolCallContext(
            task_id=task_id,
            agent_id=self.agent_id,
            step_index=step,
            tool_name=tool_name,
        )
        if metadata:
            ctx.metadata = metadata

        return await self._execute(ctx, tool_fn, input_data, timeout or self.default_timeout)

    def reset_task(self, task_id: str) -> None:
        """Reset step counter for a task (call between retries)."""
        self._step_counters.pop(task_id, None)

    # --- Internal -----------------------------------------------------------

    def _next_step(self, task_id: str) -> int:
        self._step_counters[task_id] = self._step_counters.get(task_id, 0) + 1
        return self._step_counters[task_id]

    async def _execute(
        self,
        ctx: ToolCallContext,
        tool_fn: Callable,
        input_data: Any,
        timeout: float,
    ) -> tuple[Any, ExecutionReceipt]:
        ctx.input_payload = input_data
        ctx.started_at = datetime.utcnow()
        t0 = time.perf_counter_ns()

        for hook in self._before_hooks:
            try:
                await hook(ctx)
            except Exception:
                pass

        result: Any = None
        try:
            coro = (
                tool_fn(input_data)
                if asyncio.iscoroutinefunction(tool_fn)
                else asyncio.get_event_loop().run_in_executor(None, tool_fn, input_data)
            )
            result = await asyncio.wait_for(coro, timeout=timeout)
            ctx.output_payload = result
            ctx.status = ToolStatus.SUCCESS
        except asyncio.TimeoutError:
            ctx.status = ToolStatus.TIMEOUT
            ctx.error_message = f"Exceeded {timeout}s timeout"
        except Exception as exc:
            ctx.status = ToolStatus.FAILURE
            ctx.error_message = str(exc)
        finally:
            ctx.ended_at = datetime.utcnow()

        duration_ms = (time.perf_counter_ns() - t0) // 1_000_000
        receipt = self._build_receipt(ctx, duration_ms)

        for hook in self._after_hooks:
            try:
                await hook(ctx, receipt)
            except Exception:
                pass

        await self.receipt_store.save(receipt)
        return result, receipt

    def _build_receipt(self, ctx: ToolCallContext, duration_ms: int) -> ExecutionReceipt:
        input_hash = sha256_of(ctx.input_payload)
        output_hash = (
            sha256_of(ctx.output_payload)
            if ctx.output_payload is not None
            else sha256_of(b"")
        )

        receipt = ExecutionReceipt(
            task_id=ctx.task_id,
            agent_id=ctx.agent_id,
            step_index=ctx.step_index,
            tool_name=ctx.tool_name,
            input_hash=input_hash,
            output_hash=output_hash,
            started_at=ctx.started_at or datetime.utcnow(),
            ended_at=ctx.ended_at or datetime.utcnow(),
            duration_ms=duration_ms,
            status=ctx.status,
            error_message=ctx.error_message,
            metadata=ctx.metadata,
        )

        if self.signer:
            receipt.signature = self.signer.sign_receipt(receipt)

        return receipt


# ---------------------------------------------------------------------------
# Receipt Signer Interface (implement in your runtime)
# ---------------------------------------------------------------------------

class ReceiptSigner:
    """
    Interface for signing receipts with an agent's Ed25519 private key.
    Implement this in your private runtime and pass it to KarmaHookLayer.

    Example
    -------
        class MyReceiptSigner(ReceiptSigner):
            def sign_receipt(self, receipt: ExecutionReceipt) -> str:
                payload = receipt.model_dump(include={
                    "task_id", "agent_id", "step_index", "tool_name",
                    "input_hash", "output_hash", "started_at", "ended_at", "status"
                })
                return my_ed25519_sign(payload)
    """

    def sign_receipt(self, receipt: ExecutionReceipt) -> str:
        raise NotImplementedError
