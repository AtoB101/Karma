"""
Karma Trust Protocol — Verification Engine (Public Interface)
=============================================================
This module defines the public interface for submitting evidence bundles
to the Karma Verification Engine.

The verification LOGIC (check weights, thresholds, fraud detection,
human-like execution scoring, anti-cheat rules) is private and runs
inside the Karma runtime. This file shows how to integrate with it.

Usage
-----
    from karma.verification import VerificationClient

    client = VerificationClient(runtime_url="https://runtime.karma.xyz")
    result = await client.verify(bundle, contract)

    if result.decision == VerificationDecision.RELEASE:
        # safe to mark task complete
        ...
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from core.schemas import (
    EvidenceBundle,
    TaskContract,
    VerificationCheck,
    VerificationDecision,
    VerificationResult,
)


# ---------------------------------------------------------------------------
# Abstract Verification Engine
# ---------------------------------------------------------------------------

class VerificationEngine(ABC):
    """
    Interface that all Verification Engine implementations must satisfy.

    The public SDK ships this interface.
    The private runtime ships the real implementation.
    """

    @abstractmethod
    async def verify(
        self,
        bundle: EvidenceBundle,
        contract: TaskContract,
    ) -> VerificationResult:
        """
        Submit an EvidenceBundle for verification.

        Parameters
        ----------
        bundle:   The evidence bundle produced by EvidenceBundleBuilder.
        contract: The original task contract.

        Returns
        -------
        VerificationResult with a decision and per-check breakdown.
        Weights and thresholds are not exposed.
        """
        ...


# ---------------------------------------------------------------------------
# HTTP Client (calls private Karma runtime)
# ---------------------------------------------------------------------------

class VerificationClient(VerificationEngine):
    """
    Calls the Karma runtime's private verification endpoint over HTTP.
    Use this in your worker agent after building an evidence bundle.
    """

    def __init__(self, runtime_url: str, api_key: str = ""):
        self.runtime_url = runtime_url.rstrip("/")
        self.api_key = api_key

    async def verify(
        self,
        bundle: EvidenceBundle,
        contract: TaskContract,
    ) -> VerificationResult:
        import httpx

        payload = {
            "bundle": bundle.model_dump(mode="json"),
            "contract": contract.model_dump(mode="json"),
        }
        headers = {"X-Karma-Api-Key": self.api_key} if self.api_key else {}

        async with httpx.AsyncClient(timeout=60.0) as http:
            response = await http.post(
                f"{self.runtime_url}/v1/verify",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            return VerificationResult(**response.json())


# ---------------------------------------------------------------------------
# Mock Engine (for local development and testing)
# ---------------------------------------------------------------------------

class MockVerificationEngine(VerificationEngine):
    """
    Returns a fixed RELEASE decision.
    Use in unit tests — never in production.
    """

    async def verify(
        self,
        bundle: EvidenceBundle,
        contract: TaskContract,
    ) -> VerificationResult:
        checks = [
            VerificationCheck(name="receipt_completeness", passed=True),
            VerificationCheck(name="hash_integrity", passed=True),
            VerificationCheck(name="chronological_order", passed=True),
            VerificationCheck(name="task_id_consistency", passed=True),
        ]
        return VerificationResult(
            task_id=bundle.task_id,
            bundle_id=bundle.bundle_id,
            decision=VerificationDecision.RELEASE,
            confidence=1.0,
            checks=checks,
            notes="Mock engine — always releases.",
        )
