"""
Challenge Window Manager
========================
Manages time-bounded challenge windows that gate settlement approval.

A challenge window opens after evidence publication and verifier
attestations. During the window, anyone may raise a challenge.
Settlement may only proceed when the window is closed and no
active dispute exists.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from decentralized_verifier import (
    ChallengeWindow,
    ChallengeRecord,
    ChallengeWindowStatus,
    ChallengeDecision,
    utc_now_iso,
)


@dataclass
class _ChallengeWindowState:
    """Internal mutable state for a single challenge window."""
    window: ChallengeWindow
    challenge: Optional[ChallengeRecord] = None


class ChallengeWindowManager:
    """
    Manages lifecycle of challenge windows for attested tasks.

    Usage::

        mgr = ChallengeWindowManager(default_duration_seconds=1800)

        window = mgr.open_window(
            task_id="task_001",
            evidence_hash="abc123...",
            task_type="api",
        )

        if mgr.is_window_closed(window) and mgr.can_settle(window):
            ...  # proceed to settlement

        mgr.raise_challenge(
            window=window,
            challenger="0xBob",
            reason="evidence_hash_mismatch",
            evidence_cid="bafy...",
        )
        # Now can_settle() returns False until arbitrator resolves.
    """

    def __init__(self, *, default_duration_seconds: int = 1800) -> None:
        """
        Args:
            default_duration_seconds: Default challenge window duration
                (30 min = 1800s for API/MCP tasks; 24h for content tasks).
        """
        self.default_duration_seconds = default_duration_seconds
        self._windows: dict[str, _ChallengeWindowState] = {}

    # ──────────────────────── Window Lifecycle ──────────────────────────────

    def open_window(
        self,
        task_id: str,
        evidence_hash: str,
        task_type: str = "default",
        duration_seconds: int | None = None,
    ) -> ChallengeWindow:
        """
        Open a new challenge window for a task.

        Args:
            task_id: Unique task identifier (matches on-chain taskId).
            evidence_hash: SHA-256 of the evidence bundle (64-char hex).
            task_type: Task category for duration lookup (api, mcp, etc.).
            duration_seconds: Override the default duration.

        Returns:
            A ChallengeWindow dataclass representing the opened window.

        Raises:
            ValueError: If a window is already open for this task_id.
        """
        if task_id in self._windows:
            raise ValueError(f"Challenge window already exists for task_id={task_id}")

        dur = duration_seconds or self.default_duration_seconds
        now = datetime.now(timezone.utc)
        start = now.replace(microsecond=0)
        end = start + timedelta(seconds=dur)

        window = ChallengeWindow(
            challenge_id=f"challenge-{task_id}",
            task_id=task_id,
            evidence_hash=evidence_hash,
            start_at=start.isoformat(),
            end_at=end.isoformat(),
            duration_seconds=dur,
            status=ChallengeWindowStatus.OPEN,
        )
        self._windows[task_id] = _ChallengeWindowState(window=window)
        return window

    # ──────────────────────── Status Checks ─────────────────────────────────

    def is_window_open(self, window: ChallengeWindow) -> bool:
        """
        Returns True if the challenge window is currently open.

        Checks both the in-memory status AND the wall-clock time.
        """
        self._sync_window_status(window)
        return window.status == ChallengeWindowStatus.OPEN

    def is_window_closed(self, window: ChallengeWindow) -> bool:
        """Returns True if the challenge window has closed."""
        self._sync_window_status(window)
        return window.status == ChallengeWindowStatus.CLOSED

    def can_settle(self, window: ChallengeWindow) -> bool:
        """
        Returns True if settlement can proceed for this window.

        Conditions:
        - Window must be CLOSED (time expired).
        - Window must NOT be DISPUTED (no active challenge).
        """
        self._sync_window_status(window)
        return window.status == ChallengeWindowStatus.CLOSED

    def get_remaining_seconds(self, window: ChallengeWindow) -> int:
        """Return how many seconds remain in the challenge window (0 if closed)."""
        self._sync_window_status(window)
        if window.status != ChallengeWindowStatus.OPEN:
            return 0
        now = datetime.now(timezone.utc)
        end = datetime.fromisoformat(window.end_at)
        remaining = (end - now).total_seconds()
        return max(0, int(remaining))

    # ──────────────────────── Challenge Actions ─────────────────────────────

    def raise_challenge(
        self,
        window: ChallengeWindow,
        challenger: str,
        reason: str,
        evidence_cid: str,
    ) -> ChallengeRecord:
        """
        Raise a challenge during the challenge window.

        Args:
            window: The ChallengeWindow to challenge.
            challenger: Wallet address of the challenger (0x...).
            reason: Reason code (e.g. "evidence_hash_mismatch").
            evidence_cid: IPFS CID of challenge evidence.

        Returns:
            A ChallengeRecord for the raised challenge.

        Raises:
            ValueError: If window is closed or already challenged.
        """
        self._sync_window_status(window)

        if window.status != ChallengeWindowStatus.OPEN:
            raise ValueError(
                f"Cannot raise challenge: window status is {window.status.value}"
            )

        state = self._windows.get(window.task_id)
        if state is None:
            raise ValueError(f"No window state found for task_id={window.task_id}")
        if state.challenge is not None:
            raise ValueError(f"Challenge already raised for task_id={window.task_id}")

        record = ChallengeRecord(
            challenge_id=f"challenge-{window.task_id}-{uuid.uuid4().hex[:8]}",
            task_id=window.task_id,
            challenger_wallet=challenger,
            reason_code=reason,
            evidence_hash=window.evidence_hash,
            challenge_evidence_cid=evidence_cid,
            status="open",
            decision="",
            created_at=utc_now_iso(),
        )

        state.challenge = record
        window.status = ChallengeWindowStatus.DISPUTED
        return record

    def resolve_challenge(
        self,
        window: ChallengeWindow,
        decision: ChallengeDecision,
    ) -> ChallengeRecord:
        """
        Arbitrator resolves a challenge.

        Args:
            window: The ChallengeWindow with an active dispute.
            decision: UPHELD (challenge valid, settlement blocked) or
                      OVERRULED (challenge invalid, settlement proceeds).

        Returns:
            The updated ChallengeRecord.

        Raises:
            ValueError: If no active challenge exists.
        """
        state = self._windows.get(window.task_id)
        if state is None or state.challenge is None:
            raise ValueError(
                f"No active challenge for task_id={window.task_id}"
            )

        challenge = state.challenge
        challenge.status = "resolved"
        challenge.decision = decision.value

        if decision == ChallengeDecision.UPHELD:
            # Settlement permanently blocked.
            window.status = ChallengeWindowStatus.DISPUTED
        else:
            # OVERRULED — settleable if window also closed.
            self._sync_window_status(window)

        return challenge

    # ──────────────────────── Internal Helpers ──────────────────────────────

    def _sync_window_status(self, window: ChallengeWindow) -> None:
        """
        Sync the in-memory window status with wall-clock time.

        A window automatically transitions from OPEN → CLOSED when the
        clock passes end_at, unless it's DISPUTED (which stays DISPUTED
        until arbitrator resolution).
        """
        if window.status == ChallengeWindowStatus.OPEN:
            end = datetime.fromisoformat(window.end_at)
            if datetime.now(timezone.utc) > end:
                window.status = ChallengeWindowStatus.CLOSED

    def _get_state(self, task_id: str) -> Optional[_ChallengeWindowState]:
        """Return internal state for a task or None."""
        return self._windows.get(task_id)
