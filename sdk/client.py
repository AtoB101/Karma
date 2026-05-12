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
    ExplainableRiskReport,
    ArbitrationAssignment,
    ArbitrationCase,
    ArbitrationMaterialPackage,
    ArbitrationPoolMember,
    ArbitrationVoteDecision,
    AuthorizationVoucher,
    CapacityState,
    EvidenceBundle,
    IdentityProfile,
    ProgressReceipt,
    ResponsibilityEdgeIngestResult,
    ResponsibilityEdgeType,
    ResponsibilityBatchScanRun,
    ResponsibilityBatchScanResult,
    ResponsibilityRecoverStaleRunsResult,
    ResponsibilityScanExecutionMode,
    ResponsibilityScanQueueStats,
    ResponsibilityPathFeaturesSummary,
    ResponsibilityPublicRiskModel,
    ResponsibilityRiskSignal,
    ResponsibilityScanMode,
    ResponsibilityScoreSummary,
    TaskTemporalConsistencyReport,
    ReputationSnapshot,
    SettlementState,
    SubIdentity,
    SubIdentityType,
    TaskPathHashSummary,
    TaskContract,
    TaskStatus,
    VerificationResult,
    VoucherVerificationResult,
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

    async def get_capacity(self, identity_id: str) -> CapacityState:
        """GET /v1/capacity/{identity_id}"""
        async with self._http() as http:
            resp = await http.get(f"{self.runtime_url}/v1/capacity/{identity_id}")
            resp.raise_for_status()
            return CapacityState(**resp.json())

    async def lock_capacity(self, identity_id: str, amount: float) -> CapacityState:
        """POST /v1/capacity/{identity_id}/lock"""
        async with self._http() as http:
            resp = await http.post(
                f"{self.runtime_url}/v1/capacity/{identity_id}/lock",
                json={"amount": amount},
            )
            resp.raise_for_status()
            return CapacityState(**resp.json())

    async def release_capacity(self, identity_id: str, amount: float) -> CapacityState:
        """POST /v1/capacity/{identity_id}/release"""
        async with self._http() as http:
            resp = await http.post(
                f"{self.runtime_url}/v1/capacity/{identity_id}/release",
                json={"amount": amount},
            )
            resp.raise_for_status()
            return CapacityState(**resp.json())

    async def create_voucher(
        self,
        *,
        buyer_identity_id: str,
        seller_identity_id: str,
        amount: float,
        bill_credit_amount: float,
        task_type: str,
        task_description_hash: str,
        progress_rule_hash: str,
        evidence_requirement_hash: str,
        expiry_time: str,
        nonce: str,
        buyer_signature: str,
        currency: str = "USDC",
        buyer_sub_identity_id: Optional[str] = None,
        seller_sub_identity_id: Optional[str] = None,
    ) -> AuthorizationVoucher:
        """POST /v1/vouchers"""
        payload = {
            "buyer_identity_id": buyer_identity_id,
            "seller_identity_id": seller_identity_id,
            "amount": amount,
            "currency": currency,
            "bill_credit_amount": bill_credit_amount,
            "task_type": task_type,
            "task_description_hash": task_description_hash,
            "progress_rule_hash": progress_rule_hash,
            "evidence_requirement_hash": evidence_requirement_hash,
            "expiry_time": expiry_time,
            "nonce": nonce,
            "buyer_signature": buyer_signature,
            "buyer_sub_identity_id": buyer_sub_identity_id,
            "seller_sub_identity_id": seller_sub_identity_id,
        }
        async with self._http() as http:
            resp = await http.post(f"{self.runtime_url}/v1/vouchers", json=payload)
            resp.raise_for_status()
            return AuthorizationVoucher(**resp.json())

    async def get_voucher(self, voucher_id: str) -> AuthorizationVoucher:
        """GET /v1/vouchers/{voucher_id}"""
        async with self._http() as http:
            resp = await http.get(f"{self.runtime_url}/v1/vouchers/{voucher_id}")
            resp.raise_for_status()
            return AuthorizationVoucher(**resp.json())

    async def verify_voucher(
        self,
        voucher_id: str,
        seller_identity_id: str,
        expected_amount: Optional[float] = None,
    ) -> VoucherVerificationResult:
        """POST /v1/vouchers/{voucher_id}/verify"""
        payload: dict[str, Any] = {"seller_identity_id": seller_identity_id}
        if expected_amount is not None:
            payload["expected_amount"] = expected_amount
        async with self._http() as http:
            resp = await http.post(
                f"{self.runtime_url}/v1/vouchers/{voucher_id}/verify",
                json=payload,
            )
            resp.raise_for_status()
            return VoucherVerificationResult(**resp.json())

    async def accept_voucher(self, voucher_id: str, seller_identity_id: str) -> AuthorizationVoucher:
        """POST /v1/vouchers/{voucher_id}/accept"""
        async with self._http() as http:
            resp = await http.post(
                f"{self.runtime_url}/v1/vouchers/{voucher_id}/accept",
                json={"seller_identity_id": seller_identity_id},
            )
            resp.raise_for_status()
            return AuthorizationVoucher(**resp.json())

    async def submit_progress(self, progress: ProgressReceipt) -> ProgressReceipt:
        """POST /v1/progress"""
        async with self._http() as http:
            resp = await http.post(
                f"{self.runtime_url}/v1/progress",
                json=progress.model_dump(mode="json"),
            )
            resp.raise_for_status()
            return ProgressReceipt(**resp.json())

    async def confirm_progress(self, progress_receipt_id: str) -> ProgressReceipt:
        """POST /v1/progress/{progress_receipt_id}/confirm"""
        async with self._http() as http:
            resp = await http.post(
                f"{self.runtime_url}/v1/progress/{progress_receipt_id}/confirm",
                json={},
            )
            resp.raise_for_status()
            return ProgressReceipt(**resp.json())

    async def list_progress(self, task_id: str) -> list[ProgressReceipt]:
        """GET /v1/progress/task/{task_id}"""
        async with self._http() as http:
            resp = await http.get(f"{self.runtime_url}/v1/progress/task/{task_id}")
            resp.raise_for_status()
            return [ProgressReceipt(**item) for item in resp.json()]

    async def partial_settlement(self, task_id: str, settled_value_percent: float, reason: str | None = None) -> SettlementState:
        """POST /v1/settlement/{task_id}/partial"""
        payload: dict[str, Any] = {"settled_value_percent": settled_value_percent}
        if reason:
            payload["reason"] = reason
        async with self._http() as http:
            resp = await http.post(f"{self.runtime_url}/v1/settlement/{task_id}/partial", json=payload)
            resp.raise_for_status()
            return SettlementState(**resp.json())

    async def regret_task(self, task_id: str, buyer_identity_id: str | None = None, reason: str | None = None) -> SettlementState:
        """POST /v1/settlement/{task_id}/regret"""
        payload: dict[str, Any] = {}
        if buyer_identity_id:
            payload["buyer_identity_id"] = buyer_identity_id
        if reason:
            payload["reason"] = reason
        async with self._http() as http:
            resp = await http.post(f"{self.runtime_url}/v1/settlement/{task_id}/regret", json=payload)
            resp.raise_for_status()
            return SettlementState(**resp.json())

    async def open_dispute(self, task_id: str, reason: str | None = None) -> SettlementState:
        """POST /v1/settlement/{task_id}/dispute"""
        payload: dict[str, Any] = {}
        if reason:
            payload["reason"] = reason
        async with self._http() as http:
            resp = await http.post(f"{self.runtime_url}/v1/settlement/{task_id}/dispute", json=payload)
            resp.raise_for_status()
            return SettlementState(**resp.json())

    async def auto_arbitrate(self, task_id: str) -> SettlementState:
        """POST /v1/settlement/{task_id}/auto-arbitrate"""
        async with self._http() as http:
            resp = await http.post(f"{self.runtime_url}/v1/settlement/{task_id}/auto-arbitrate", json={})
            resp.raise_for_status()
            return SettlementState(**resp.json())

    async def init_identity_profile(self, identity_id: str) -> IdentityProfile:
        """POST /v1/identities/{identity_id}/profile/init"""
        async with self._http() as http:
            resp = await http.post(f"{self.runtime_url}/v1/identities/{identity_id}/profile/init", json={})
            resp.raise_for_status()
            return IdentityProfile(**resp.json())

    async def get_identity_profile(self, identity_id: str) -> IdentityProfile:
        """GET /v1/identities/{identity_id}/profile"""
        async with self._http() as http:
            resp = await http.get(f"{self.runtime_url}/v1/identities/{identity_id}/profile")
            resp.raise_for_status()
            return IdentityProfile(**resp.json())

    async def rotate_display_id(self, identity_id: str) -> IdentityProfile:
        """POST /v1/identities/{identity_id}/rotate-display-id"""
        async with self._http() as http:
            resp = await http.post(f"{self.runtime_url}/v1/identities/{identity_id}/rotate-display-id", json={})
            resp.raise_for_status()
            return IdentityProfile(**resp.json())

    async def create_sub_identity(
        self,
        identity_id: str,
        sub_identity_type: SubIdentityType,
        alias: str,
    ) -> SubIdentity:
        """POST /v1/identities/{identity_id}/sub-identities"""
        payload = {"sub_identity_type": sub_identity_type.value, "alias": alias}
        async with self._http() as http:
            resp = await http.post(
                f"{self.runtime_url}/v1/identities/{identity_id}/sub-identities",
                json=payload,
            )
            resp.raise_for_status()
            return SubIdentity(**resp.json())

    async def list_sub_identities(self, identity_id: str) -> list[SubIdentity]:
        """GET /v1/identities/{identity_id}/sub-identities"""
        async with self._http() as http:
            resp = await http.get(f"{self.runtime_url}/v1/identities/{identity_id}/sub-identities")
            resp.raise_for_status()
            return [SubIdentity(**item) for item in resp.json()]

    async def delete_sub_identity(self, identity_id: str, sub_identity_id: str) -> SubIdentity:
        """DELETE /v1/identities/{identity_id}/sub-identities/{sub_identity_id}"""
        async with self._http() as http:
            resp = await http.delete(
                f"{self.runtime_url}/v1/identities/{identity_id}/sub-identities/{sub_identity_id}",
            )
            resp.raise_for_status()
            return SubIdentity(**resp.json())

    async def join_arbitration_pool(self, arbitrator_identity_id: str, stake_amount: float = 0.0) -> ArbitrationPoolMember:
        """POST /v1/arbitration/pool/join"""
        payload = {"arbitrator_identity_id": arbitrator_identity_id, "stake_amount": stake_amount}
        async with self._http() as http:
            resp = await http.post(f"{self.runtime_url}/v1/arbitration/pool/join", json=payload)
            resp.raise_for_status()
            return ArbitrationPoolMember(**resp.json())

    async def list_arbitration_pool(self) -> list[ArbitrationPoolMember]:
        """GET /v1/arbitration/pool"""
        async with self._http() as http:
            resp = await http.get(f"{self.runtime_url}/v1/arbitration/pool")
            resp.raise_for_status()
            return [ArbitrationPoolMember(**item) for item in resp.json()]

    async def create_arbitration_case(
        self,
        *,
        task_id: str,
        opened_by: str,
        reason: str | None = None,
        required_arbitrators: int = 3,
    ) -> ArbitrationCase:
        """POST /v1/arbitration/cases"""
        payload: dict[str, Any] = {
            "task_id": task_id,
            "opened_by": opened_by,
            "required_arbitrators": required_arbitrators,
        }
        if reason:
            payload["reason"] = reason
        async with self._http() as http:
            resp = await http.post(f"{self.runtime_url}/v1/arbitration/cases", json=payload)
            resp.raise_for_status()
            return ArbitrationCase(**resp.json())

    async def assign_arbitrators(self, case_id: str, count: int = 3) -> list[ArbitrationAssignment]:
        """POST /v1/arbitration/cases/{case_id}/assign-auto"""
        async with self._http() as http:
            resp = await http.post(
                f"{self.runtime_url}/v1/arbitration/cases/{case_id}/assign-auto",
                json={"count": count},
            )
            resp.raise_for_status()
            return [ArbitrationAssignment(**item) for item in resp.json()]

    async def list_arbitration_assignments(self, case_id: str) -> list[ArbitrationAssignment]:
        """GET /v1/arbitration/cases/{case_id}/assignments"""
        async with self._http() as http:
            resp = await http.get(f"{self.runtime_url}/v1/arbitration/cases/{case_id}/assignments")
            resp.raise_for_status()
            return [ArbitrationAssignment(**item) for item in resp.json()]

    async def submit_arbitration_material(
        self,
        *,
        case_id: str,
        submitted_by: str,
        bundle_id: str | None = None,
        progress_receipt_ids: list[str] | None = None,
        evidence_hashes: list[str] | None = None,
        storage_uri: str | None = None,
        format_version: str = "arbitration-material-v1",
    ) -> ArbitrationMaterialPackage:
        """POST /v1/arbitration/cases/{case_id}/materials"""
        payload: dict[str, Any] = {
            "submitted_by": submitted_by,
            "bundle_id": bundle_id,
            "progress_receipt_ids": progress_receipt_ids or [],
            "evidence_hashes": evidence_hashes or [],
            "storage_uri": storage_uri,
            "format_version": format_version,
        }
        async with self._http() as http:
            resp = await http.post(
                f"{self.runtime_url}/v1/arbitration/cases/{case_id}/materials",
                json=payload,
            )
            resp.raise_for_status()
            return ArbitrationMaterialPackage(**resp.json())

    async def list_arbitration_materials(self, case_id: str) -> list[ArbitrationMaterialPackage]:
        """GET /v1/arbitration/cases/{case_id}/materials"""
        async with self._http() as http:
            resp = await http.get(f"{self.runtime_url}/v1/arbitration/cases/{case_id}/materials")
            resp.raise_for_status()
            return [ArbitrationMaterialPackage(**item) for item in resp.json()]

    async def cast_arbitration_vote(
        self,
        *,
        case_id: str,
        arbitrator_identity_id: str,
        decision: ArbitrationVoteDecision,
        partial_percent: float | None = None,
        rationale: str | None = None,
    ) -> ArbitrationCase:
        """POST /v1/arbitration/cases/{case_id}/vote"""
        payload: dict[str, Any] = {
            "arbitrator_identity_id": arbitrator_identity_id,
            "decision": decision.value,
            "partial_percent": partial_percent,
            "rationale": rationale,
        }
        async with self._http() as http:
            resp = await http.post(
                f"{self.runtime_url}/v1/arbitration/cases/{case_id}/vote",
                json=payload,
            )
            resp.raise_for_status()
            return ArbitrationCase(**resp.json())

    async def execute_arbitration_case(self, case_id: str) -> SettlementState:
        """POST /v1/arbitration/cases/{case_id}/execute"""
        async with self._http() as http:
            resp = await http.post(
                f"{self.runtime_url}/v1/arbitration/cases/{case_id}/execute",
                json={},
            )
            resp.raise_for_status()
            return SettlementState(**resp.json())

    async def ingest_responsibility_edge(
        self,
        *,
        source_identity_id: str,
        target_identity_id: str,
        edge_type: ResponsibilityEdgeType = ResponsibilityEdgeType.MANUAL_LINK,
        task_id: str | None = None,
        voucher_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ResponsibilityEdgeIngestResult:
        """POST /v1/responsibility/edges"""
        payload: dict[str, Any] = {
            "source_identity_id": source_identity_id,
            "target_identity_id": target_identity_id,
            "edge_type": edge_type.value,
            "task_id": task_id,
            "voucher_id": voucher_id,
            "metadata": metadata or {},
        }
        async with self._http() as http:
            resp = await http.post(f"{self.runtime_url}/v1/responsibility/edges", json=payload)
            resp.raise_for_status()
            return ResponsibilityEdgeIngestResult(**resp.json())

    async def list_responsibility_signals(self, identity_id: str, limit: int = 50) -> list[ResponsibilityRiskSignal]:
        """GET /v1/responsibility/identity/{identity_id}/signals"""
        async with self._http() as http:
            resp = await http.get(f"{self.runtime_url}/v1/responsibility/identity/{identity_id}/signals?limit={limit}")
            resp.raise_for_status()
            return [ResponsibilityRiskSignal(**item) for item in resp.json()]

    async def get_task_path_hash(self, task_id: str) -> TaskPathHashSummary:
        """GET /v1/responsibility/task/{task_id}/path-hash"""
        async with self._http() as http:
            resp = await http.get(f"{self.runtime_url}/v1/responsibility/task/{task_id}/path-hash")
            resp.raise_for_status()
            return TaskPathHashSummary(**resp.json())

    async def get_task_temporal_consistency(self, task_id: str) -> TaskTemporalConsistencyReport:
        """GET /v1/responsibility/task/{task_id}/temporal-consistency"""
        async with self._http() as http:
            resp = await http.get(f"{self.runtime_url}/v1/responsibility/task/{task_id}/temporal-consistency")
            resp.raise_for_status()
            return TaskTemporalConsistencyReport(**resp.json())

    async def get_responsibility_score(self, identity_id: str, window_hours: int = 24) -> ResponsibilityScoreSummary:
        """GET /v1/responsibility/identity/{identity_id}/score"""
        async with self._http() as http:
            resp = await http.get(
                f"{self.runtime_url}/v1/responsibility/identity/{identity_id}/score?window_hours={window_hours}"
            )
            resp.raise_for_status()
            return ResponsibilityScoreSummary(**resp.json())

    async def get_responsibility_path_features(
        self,
        identity_id: str,
        *,
        window_hours: int = 24,
        max_hops: int = 4,
    ) -> ResponsibilityPathFeaturesSummary:
        """GET /v1/responsibility/identity/{identity_id}/path-features"""
        async with self._http() as http:
            resp = await http.get(
                f"{self.runtime_url}/v1/responsibility/identity/{identity_id}/path-features"
                f"?window_hours={window_hours}&max_hops={max_hops}"
            )
            resp.raise_for_status()
            return ResponsibilityPathFeaturesSummary(**resp.json())

    async def get_public_responsibility_risk_model(self) -> ResponsibilityPublicRiskModel:
        """GET /v1/responsibility/model/public-risk"""
        async with self._http() as http:
            resp = await http.get(f"{self.runtime_url}/v1/responsibility/model/public-risk")
            resp.raise_for_status()
            return ResponsibilityPublicRiskModel(**resp.json())

    async def create_responsibility_batch_scan(
        self,
        *,
        identity_ids: list[str] | None = None,
        execution_mode: ResponsibilityScanExecutionMode = ResponsibilityScanExecutionMode.SYNC,
        scan_mode: ResponsibilityScanMode = ResponsibilityScanMode.FULL,
        base_scan_id: str | None = None,
        window_hours: int = 24,
        max_hops: int = 4,
        min_score_threshold: float = 8.0,
        retry_max_attempts: int = 3,
        retry_backoff_seconds: int = 30,
    ) -> ResponsibilityBatchScanResult:
        """POST /v1/responsibility/scan-runs"""
        payload: dict[str, Any] = {
            "identity_ids": identity_ids,
            "execution_mode": execution_mode.value,
            "scan_mode": scan_mode.value,
            "base_scan_id": base_scan_id,
            "window_hours": window_hours,
            "max_hops": max_hops,
            "min_score_threshold": min_score_threshold,
            "retry_max_attempts": retry_max_attempts,
            "retry_backoff_seconds": retry_backoff_seconds,
        }
        async with self._http() as http:
            resp = await http.post(f"{self.runtime_url}/v1/responsibility/scan-runs", json=payload)
            resp.raise_for_status()
            return ResponsibilityBatchScanResult(**resp.json())

    async def get_responsibility_batch_scan(
        self,
        scan_id: str,
        *,
        findings_limit: int = 200,
    ) -> ResponsibilityBatchScanResult:
        """GET /v1/responsibility/scan-runs/{scan_id}"""
        async with self._http() as http:
            resp = await http.get(
                f"{self.runtime_url}/v1/responsibility/scan-runs/{scan_id}?findings_limit={findings_limit}"
            )
            resp.raise_for_status()
            return ResponsibilityBatchScanResult(**resp.json())

    async def claim_responsibility_batch_scan(
        self,
        *,
        runner_identity_id: str,
        lease_seconds: int = 300,
        include_failed: bool = True,
    ) -> ResponsibilityBatchScanRun:
        """POST /v1/responsibility/scan-runs/claim"""
        async with self._http() as http:
            resp = await http.post(
                f"{self.runtime_url}/v1/responsibility/scan-runs/claim",
                json={
                    "runner_identity_id": runner_identity_id,
                    "lease_seconds": lease_seconds,
                    "include_failed": include_failed,
                },
            )
            resp.raise_for_status()
            return ResponsibilityBatchScanRun(**resp.json())

    async def get_responsibility_scan_queue_stats(self) -> ResponsibilityScanQueueStats:
        """GET /v1/responsibility/scan-runs/queue/stats"""
        async with self._http() as http:
            resp = await http.get(f"{self.runtime_url}/v1/responsibility/scan-runs/queue/stats")
            resp.raise_for_status()
            return ResponsibilityScanQueueStats(**resp.json())

    async def recover_stale_responsibility_batch_scans(
        self,
        *,
        limit: int = 100,
    ) -> ResponsibilityRecoverStaleRunsResult:
        """POST /v1/responsibility/scan-runs/recover-stale"""
        async with self._http() as http:
            resp = await http.post(
                f"{self.runtime_url}/v1/responsibility/scan-runs/recover-stale",
                json={"limit": limit},
            )
            resp.raise_for_status()
            return ResponsibilityRecoverStaleRunsResult(**resp.json())

    async def execute_responsibility_batch_scan(
        self,
        scan_id: str,
        *,
        force: bool = False,
        runner_identity_id: str | None = None,
        lease_seconds: int = 300,
    ) -> ResponsibilityBatchScanResult:
        """POST /v1/responsibility/scan-runs/{scan_id}/execute"""
        async with self._http() as http:
            resp = await http.post(
                f"{self.runtime_url}/v1/responsibility/scan-runs/{scan_id}/execute",
                json={
                    "force": force,
                    "runner_identity_id": runner_identity_id,
                    "lease_seconds": lease_seconds,
                },
            )
            resp.raise_for_status()
            return ResponsibilityBatchScanResult(**resp.json())

    async def heartbeat_responsibility_batch_scan(
        self,
        scan_id: str,
        *,
        runner_identity_id: str,
        lease_seconds: int = 300,
    ) -> ResponsibilityBatchScanRun:
        """POST /v1/responsibility/scan-runs/{scan_id}/heartbeat"""
        async with self._http() as http:
            resp = await http.post(
                f"{self.runtime_url}/v1/responsibility/scan-runs/{scan_id}/heartbeat",
                json={
                    "runner_identity_id": runner_identity_id,
                    "lease_seconds": lease_seconds,
                },
            )
            resp.raise_for_status()
            return ResponsibilityBatchScanRun(**resp.json())

    async def retry_responsibility_batch_scan(self, scan_id: str) -> ResponsibilityBatchScanResult:
        """POST /v1/responsibility/scan-runs/{scan_id}/retry"""
        async with self._http() as http:
            resp = await http.post(
                f"{self.runtime_url}/v1/responsibility/scan-runs/{scan_id}/retry",
                json={},
            )
            resp.raise_for_status()
            return ResponsibilityBatchScanResult(**resp.json())

    async def cancel_responsibility_batch_scan(
        self,
        scan_id: str,
        *,
        runner_identity_id: str | None = None,
        reason: str | None = None,
    ) -> ResponsibilityBatchScanRun:
        """POST /v1/responsibility/scan-runs/{scan_id}/cancel"""
        async with self._http() as http:
            resp = await http.post(
                f"{self.runtime_url}/v1/responsibility/scan-runs/{scan_id}/cancel",
                json={
                    "runner_identity_id": runner_identity_id,
                    "reason": reason,
                },
            )
            resp.raise_for_status()
            return ResponsibilityBatchScanRun(**resp.json())

    async def export_explainable_risk_report(
        self,
        *,
        identity_id: str | None = None,
        task_id: str | None = None,
        signer_identity_id: str | None = None,
        signature: str | None = None,
        window_hours: int = 24,
        max_hops: int = 4,
        top_signals_limit: int = 20,
    ) -> ExplainableRiskReport:
        """POST /v1/responsibility/reports/export"""
        payload: dict[str, Any] = {
            "identity_id": identity_id,
            "task_id": task_id,
            "signer_identity_id": signer_identity_id,
            "signature": signature,
            "window_hours": window_hours,
            "max_hops": max_hops,
            "top_signals_limit": top_signals_limit,
        }
        async with self._http() as http:
            resp = await http.post(f"{self.runtime_url}/v1/responsibility/reports/export", json=payload)
            resp.raise_for_status()
            return ExplainableRiskReport(**resp.json())

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
