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
    ArbitrationArbitratorActivitySummary,
    ArbitrationAssignment,
    ArbitrationCase,
    ArbitrationCaseEvent,
    ArbitrationCaseOverdueItem,
    ArbitrationCaseOpsReport,
    ArbitrationOpsAlert,
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
    ResponsibilityDeadLetterPurgeResult,
    ResponsibilityDeadLetterRequeueBatchResult,
    ResponsibilityDeadLetterSweepResult,
    ResponsibilityQueueMaintenanceTickResult,
    ResponsibilityRecoverStaleRunsResult,
    ResponsibilityScanExecutionMode,
    ResponsibilityScanOpsAlert,
    ResponsibilityScanOpsReport,
    ResponsibilityScanQueueStats,
    ResponsibilityScanRunnerActivitySummary,
    ResponsibilityScanRunEvent,
    ResponsibilityPathFeaturesSummary,
    ResponsibilityPublicRiskModel,
    ResponsibilityRiskSignal,
    ResponsibilityScanMode,
    ResponsibilityScoreSummary,
    ResponsibilityWorkerPullExecuteResult,
    SecurityOpsAlertReport,
    SecurityPolicyApprovalDecision,
    SecurityPolicyChangeAction,
    SecurityPolicyChangeRequest,
    SecurityPolicyChangeStatus,
    SecurityPolicyDryRunResult,
    SecurityThresholdPolicy,
    SecurityThresholdPolicyStatus,
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

    async def list_arbitration_case_events(
        self,
        case_id: str,
        *,
        limit: int = 200,
    ) -> list[ArbitrationCaseEvent]:
        """GET /v1/arbitration/cases/{case_id}/events"""
        async with self._http() as http:
            resp = await http.get(f"{self.runtime_url}/v1/arbitration/cases/{case_id}/events?limit={limit}")
            resp.raise_for_status()
            return [ArbitrationCaseEvent(**item) for item in resp.json()]

    async def get_arbitration_case_ops_report(
        self,
        *,
        window_hours: int = 24,
        recent_events_limit: int = 50,
        arbitrator_limit: int = 20,
    ) -> ArbitrationCaseOpsReport:
        """GET /v1/arbitration/cases/ops/report"""
        async with self._http() as http:
            resp = await http.get(
                f"{self.runtime_url}/v1/arbitration/cases/ops/report"
                f"?window_hours={window_hours}"
                f"&recent_events_limit={recent_events_limit}"
                f"&arbitrator_limit={arbitrator_limit}"
            )
            resp.raise_for_status()
            return ArbitrationCaseOpsReport(**resp.json())

    async def get_arbitration_case_ops_alerts(
        self,
        *,
        window_hours: int = 24,
        open_case_threshold: int = 5,
        voting_case_threshold: int = 5,
        decided_case_threshold: int = 3,
        partial_ratio_threshold: float = 0.5,
    ) -> list[ArbitrationOpsAlert]:
        """GET /v1/arbitration/cases/ops/alerts"""
        async with self._http() as http:
            resp = await http.get(
                f"{self.runtime_url}/v1/arbitration/cases/ops/alerts"
                f"?window_hours={window_hours}"
                f"&open_case_threshold={open_case_threshold}"
                f"&voting_case_threshold={voting_case_threshold}"
                f"&decided_case_threshold={decided_case_threshold}"
                f"&partial_ratio_threshold={partial_ratio_threshold}"
            )
            resp.raise_for_status()
            return [ArbitrationOpsAlert(**item) for item in resp.json()]

    async def list_arbitration_case_ops_arbitrators(
        self,
        *,
        window_hours: int = 24,
        limit: int = 20,
    ) -> list[ArbitrationArbitratorActivitySummary]:
        """GET /v1/arbitration/cases/ops/arbitrators"""
        async with self._http() as http:
            resp = await http.get(
                f"{self.runtime_url}/v1/arbitration/cases/ops/arbitrators"
                f"?window_hours={window_hours}&limit={limit}"
            )
            resp.raise_for_status()
            return [ArbitrationArbitratorActivitySummary(**item) for item in resp.json()]

    async def list_arbitration_case_ops_overdue(
        self,
        *,
        limit: int = 20,
        open_overdue_hours: int = 24,
        voting_overdue_hours: int = 24,
        decided_overdue_hours: int = 12,
    ) -> list[ArbitrationCaseOverdueItem]:
        """GET /v1/arbitration/cases/ops/overdue"""
        async with self._http() as http:
            resp = await http.get(
                f"{self.runtime_url}/v1/arbitration/cases/ops/overdue"
                f"?limit={limit}"
                f"&open_overdue_hours={open_overdue_hours}"
                f"&voting_overdue_hours={voting_overdue_hours}"
                f"&decided_overdue_hours={decided_overdue_hours}"
            )
            resp.raise_for_status()
            return [ArbitrationCaseOverdueItem(**item) for item in resp.json()]

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

    async def list_responsibility_batch_scan_events(
        self,
        scan_id: str,
        *,
        limit: int = 200,
    ) -> list[ResponsibilityScanRunEvent]:
        """GET /v1/responsibility/scan-runs/{scan_id}/events"""
        async with self._http() as http:
            resp = await http.get(
                f"{self.runtime_url}/v1/responsibility/scan-runs/{scan_id}/events?limit={limit}"
            )
            resp.raise_for_status()
            return [ResponsibilityScanRunEvent(**item) for item in resp.json()]

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

    async def get_responsibility_scan_ops_report(
        self,
        *,
        window_hours: int = 24,
        recent_events_limit: int = 50,
        top_failure_limit: int = 10,
        runner_limit: int = 20,
    ) -> ResponsibilityScanOpsReport:
        """GET /v1/responsibility/scan-runs/ops/report"""
        async with self._http() as http:
            resp = await http.get(
                f"{self.runtime_url}/v1/responsibility/scan-runs/ops/report"
                f"?window_hours={window_hours}"
                f"&recent_events_limit={recent_events_limit}"
                f"&top_failure_limit={top_failure_limit}"
                f"&runner_limit={runner_limit}"
            )
            resp.raise_for_status()
            return ResponsibilityScanOpsReport(**resp.json())

    async def list_responsibility_scan_runner_activity(
        self,
        *,
        window_hours: int = 24,
        limit: int = 20,
    ) -> list[ResponsibilityScanRunnerActivitySummary]:
        """GET /v1/responsibility/scan-runs/ops/runners"""
        async with self._http() as http:
            resp = await http.get(
                f"{self.runtime_url}/v1/responsibility/scan-runs/ops/runners"
                f"?window_hours={window_hours}&limit={limit}"
            )
            resp.raise_for_status()
            return [ResponsibilityScanRunnerActivitySummary(**item) for item in resp.json()]

    async def get_responsibility_scan_ops_alerts(
        self,
        *,
        window_hours: int = 24,
        runner_limit: int = 20,
        dead_letter_threshold: int = 5,
        stale_threshold: int = 3,
        failed_ratio_threshold: float = 0.25,
        runner_failure_min_started: int = 3,
        runner_failure_ratio_threshold: float = 0.5,
    ) -> list[ResponsibilityScanOpsAlert]:
        """GET /v1/responsibility/scan-runs/ops/alerts"""
        async with self._http() as http:
            resp = await http.get(
                f"{self.runtime_url}/v1/responsibility/scan-runs/ops/alerts"
                f"?window_hours={window_hours}"
                f"&runner_limit={runner_limit}"
                f"&dead_letter_threshold={dead_letter_threshold}"
                f"&stale_threshold={stale_threshold}"
                f"&failed_ratio_threshold={failed_ratio_threshold}"
                f"&runner_failure_min_started={runner_failure_min_started}"
                f"&runner_failure_ratio_threshold={runner_failure_ratio_threshold}"
            )
            resp.raise_for_status()
            return [ResponsibilityScanOpsAlert(**item) for item in resp.json()]

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

    async def list_dead_letter_responsibility_batch_scans(
        self,
        *,
        limit: int = 200,
    ) -> list[ResponsibilityBatchScanRun]:
        """GET /v1/responsibility/scan-runs/dead-letter"""
        async with self._http() as http:
            resp = await http.get(
                f"{self.runtime_url}/v1/responsibility/scan-runs/dead-letter?limit={limit}"
            )
            resp.raise_for_status()
            return [ResponsibilityBatchScanRun(**item) for item in resp.json()]

    async def sweep_dead_letter_responsibility_batch_scans(
        self,
        *,
        limit: int = 100,
        reason: str | None = None,
    ) -> ResponsibilityDeadLetterSweepResult:
        """POST /v1/responsibility/scan-runs/dead-letter/sweep"""
        async with self._http() as http:
            resp = await http.post(
                f"{self.runtime_url}/v1/responsibility/scan-runs/dead-letter/sweep",
                json={"limit": limit, "reason": reason},
            )
            resp.raise_for_status()
            return ResponsibilityDeadLetterSweepResult(**resp.json())

    async def requeue_dead_letter_responsibility_batch_scans(
        self,
        *,
        limit: int = 100,
        reason: str | None = None,
    ) -> ResponsibilityDeadLetterRequeueBatchResult:
        """POST /v1/responsibility/scan-runs/dead-letter/requeue-batch"""
        async with self._http() as http:
            resp = await http.post(
                f"{self.runtime_url}/v1/responsibility/scan-runs/dead-letter/requeue-batch",
                json={"limit": limit, "reason": reason},
            )
            resp.raise_for_status()
            return ResponsibilityDeadLetterRequeueBatchResult(**resp.json())

    async def purge_dead_letter_responsibility_batch_scans(
        self,
        *,
        limit: int = 100,
        older_than_hours: int = 72,
    ) -> ResponsibilityDeadLetterPurgeResult:
        """POST /v1/responsibility/scan-runs/dead-letter/purge"""
        async with self._http() as http:
            resp = await http.post(
                f"{self.runtime_url}/v1/responsibility/scan-runs/dead-letter/purge",
                json={"limit": limit, "older_than_hours": older_than_hours},
            )
            resp.raise_for_status()
            return ResponsibilityDeadLetterPurgeResult(**resp.json())

    async def pull_execute_responsibility_batch_scan(
        self,
        *,
        runner_identity_id: str,
        lease_seconds: int = 300,
        include_failed: bool = True,
        force_execute: bool = False,
    ) -> ResponsibilityWorkerPullExecuteResult:
        """POST /v1/responsibility/scan-runs/worker/pull-execute"""
        async with self._http() as http:
            resp = await http.post(
                f"{self.runtime_url}/v1/responsibility/scan-runs/worker/pull-execute",
                json={
                    "runner_identity_id": runner_identity_id,
                    "lease_seconds": lease_seconds,
                    "include_failed": include_failed,
                    "force_execute": force_execute,
                },
            )
            resp.raise_for_status()
            return ResponsibilityWorkerPullExecuteResult(**resp.json())

    async def run_responsibility_scan_queue_maintenance_tick(
        self,
        *,
        runner_identity_id: str,
        recover_limit: int = 100,
        max_claim_execute: int = 5,
        lease_seconds: int = 300,
        include_failed: bool = True,
    ) -> ResponsibilityQueueMaintenanceTickResult:
        """POST /v1/responsibility/scan-runs/maintenance/tick"""
        async with self._http() as http:
            resp = await http.post(
                f"{self.runtime_url}/v1/responsibility/scan-runs/maintenance/tick",
                json={
                    "runner_identity_id": runner_identity_id,
                    "recover_limit": recover_limit,
                    "max_claim_execute": max_claim_execute,
                    "lease_seconds": lease_seconds,
                    "include_failed": include_failed,
                },
            )
            resp.raise_for_status()
            return ResponsibilityQueueMaintenanceTickResult(**resp.json())

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

    async def requeue_dead_letter_responsibility_batch_scan(
        self,
        scan_id: str,
        *,
        reason: str | None = None,
    ) -> ResponsibilityBatchScanRun:
        """POST /v1/responsibility/scan-runs/{scan_id}/requeue"""
        async with self._http() as http:
            resp = await http.post(
                f"{self.runtime_url}/v1/responsibility/scan-runs/{scan_id}/requeue",
                json={"reason": reason},
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

    async def create_security_threshold_policy(
        self,
        *,
        config: dict[str, Any],
        note: str | None = None,
        created_by: str | None = None,
        parent_policy_id: str | None = None,
        rollout_percent: int = 100,
    ) -> SecurityThresholdPolicy:
        """POST /v1/security/policies"""
        payload = {
            "config": config,
            "note": note,
            "created_by": created_by,
            "parent_policy_id": parent_policy_id,
            "rollout_percent": rollout_percent,
        }
        async with self._http() as http:
            resp = await http.post(f"{self.runtime_url}/v1/security/policies", json=payload)
            resp.raise_for_status()
            return SecurityThresholdPolicy(**resp.json())

    async def list_security_threshold_policies(
        self,
        *,
        status: SecurityThresholdPolicyStatus | None = None,
        limit: int = 50,
    ) -> list[SecurityThresholdPolicy]:
        """GET /v1/security/policies"""
        query = f"?limit={limit}"
        if status is not None:
            query = f"?status={status.value}&limit={limit}"
        async with self._http() as http:
            resp = await http.get(f"{self.runtime_url}/v1/security/policies{query}")
            resp.raise_for_status()
            return [SecurityThresholdPolicy(**item) for item in resp.json()]

    async def get_security_threshold_policy(self, policy_id: str) -> SecurityThresholdPolicy:
        """GET /v1/security/policies/{policy_id}"""
        async with self._http() as http:
            resp = await http.get(f"{self.runtime_url}/v1/security/policies/{policy_id}")
            resp.raise_for_status()
            return SecurityThresholdPolicy(**resp.json())

    async def activate_security_threshold_policy(
        self,
        policy_id: str,
        *,
        emergency_override: bool = False,
    ) -> SecurityThresholdPolicy:
        """POST /v1/security/policies/{policy_id}/activate"""
        async with self._http() as http:
            resp = await http.post(
                f"{self.runtime_url}/v1/security/policies/{policy_id}/activate"
                f"?emergency_override={str(emergency_override).lower()}",
                json={},
            )
            resp.raise_for_status()
            return SecurityThresholdPolicy(**resp.json())

    async def set_security_threshold_policy_candidate(
        self,
        policy_id: str,
        *,
        rollout_percent: int = 10,
        emergency_override: bool = False,
    ) -> SecurityThresholdPolicy:
        """POST /v1/security/policies/{policy_id}/candidate"""
        async with self._http() as http:
            resp = await http.post(
                f"{self.runtime_url}/v1/security/policies/{policy_id}/candidate"
                f"?emergency_override={str(emergency_override).lower()}",
                json={"rollout_percent": rollout_percent},
            )
            resp.raise_for_status()
            return SecurityThresholdPolicy(**resp.json())

    async def rollback_security_threshold_policy(
        self,
        *,
        target_policy_id: str | None = None,
        emergency_override: bool = False,
    ) -> SecurityThresholdPolicy:
        """POST /v1/security/policies/rollback"""
        async with self._http() as http:
            resp = await http.post(
                f"{self.runtime_url}/v1/security/policies/rollback"
                f"?emergency_override={str(emergency_override).lower()}",
                json={"target_policy_id": target_policy_id},
            )
            resp.raise_for_status()
            return SecurityThresholdPolicy(**resp.json())

    async def create_security_policy_change_request(
        self,
        *,
        action: SecurityPolicyChangeAction,
        target_policy_id: str | None = None,
        target_rollback_policy_id: str | None = None,
        rollout_percent: int | None = None,
        note: str | None = None,
        requested_by: str | None = None,
        required_approvals: int = 2,
        dry_run_actor_id: str | None = None,
    ) -> SecurityPolicyChangeRequest:
        """POST /v1/security/policies/changes"""
        async with self._http() as http:
            resp = await http.post(
                f"{self.runtime_url}/v1/security/policies/changes",
                json={
                    "action": action.value,
                    "target_policy_id": target_policy_id,
                    "target_rollback_policy_id": target_rollback_policy_id,
                    "rollout_percent": rollout_percent,
                    "note": note,
                    "requested_by": requested_by,
                    "required_approvals": required_approvals,
                    "dry_run_actor_id": dry_run_actor_id,
                },
            )
            resp.raise_for_status()
            return SecurityPolicyChangeRequest(**resp.json())

    async def list_security_policy_change_requests(
        self,
        *,
        status: SecurityPolicyChangeStatus | None = None,
        limit: int = 50,
    ) -> list[SecurityPolicyChangeRequest]:
        """GET /v1/security/policies/changes"""
        query = f"?limit={limit}"
        if status is not None:
            query = f"?status={status.value}&limit={limit}"
        async with self._http() as http:
            resp = await http.get(f"{self.runtime_url}/v1/security/policies/changes{query}")
            resp.raise_for_status()
            return [SecurityPolicyChangeRequest(**item) for item in resp.json()]

    async def get_security_policy_change_request(self, request_id: str) -> SecurityPolicyChangeRequest:
        """GET /v1/security/policies/changes/{request_id}"""
        async with self._http() as http:
            resp = await http.get(f"{self.runtime_url}/v1/security/policies/changes/{request_id}")
            resp.raise_for_status()
            return SecurityPolicyChangeRequest(**resp.json())

    async def review_security_policy_change_request(
        self,
        request_id: str,
        *,
        approver_id: str,
        decision: SecurityPolicyApprovalDecision,
        comment: str | None = None,
    ) -> SecurityPolicyChangeRequest:
        """POST /v1/security/policies/changes/{request_id}/review"""
        async with self._http() as http:
            resp = await http.post(
                f"{self.runtime_url}/v1/security/policies/changes/{request_id}/review",
                json={
                    "approver_id": approver_id,
                    "decision": decision.value,
                    "comment": comment,
                },
            )
            resp.raise_for_status()
            return SecurityPolicyChangeRequest(**resp.json())

    async def apply_security_policy_change_request(self, request_id: str) -> SecurityPolicyChangeRequest:
        """POST /v1/security/policies/changes/{request_id}/apply"""
        async with self._http() as http:
            resp = await http.post(f"{self.runtime_url}/v1/security/policies/changes/{request_id}/apply", json={})
            resp.raise_for_status()
            return SecurityPolicyChangeRequest(**resp.json())

    async def dry_run_security_policy_change(
        self,
        *,
        action: SecurityPolicyChangeAction,
        target_policy_id: str | None = None,
        target_rollback_policy_id: str | None = None,
        rollout_percent: int | None = None,
        note: str | None = None,
        requested_by: str | None = None,
        required_approvals: int = 2,
        dry_run_actor_id: str | None = None,
    ) -> SecurityPolicyDryRunResult:
        """POST /v1/security/policies/changes/dry-run"""
        async with self._http() as http:
            resp = await http.post(
                f"{self.runtime_url}/v1/security/policies/changes/dry-run",
                json={
                    "action": action.value,
                    "target_policy_id": target_policy_id,
                    "target_rollback_policy_id": target_rollback_policy_id,
                    "rollout_percent": rollout_percent,
                    "note": note,
                    "requested_by": requested_by,
                    "required_approvals": required_approvals,
                    "dry_run_actor_id": dry_run_actor_id,
                },
            )
            resp.raise_for_status()
            return SecurityPolicyDryRunResult(**resp.json())

    async def get_security_ops_alerts(
        self,
        *,
        window_minutes: int = 15,
        failed_auth_threshold: int = 10,
        rate_limit_threshold: int = 30,
        private_runtime_error_threshold: int = 5,
        private_runtime_error_rate_threshold: float = 0.25,
        private_runtime_min_requests: int = 10,
        dimension_limit: int = 5,
        alert_cooldown_minutes: int = 10,
        failed_auth_threshold_overrides: str | None = None,
        rate_limit_threshold_overrides: str | None = None,
        private_runtime_error_threshold_overrides: str | None = None,
        private_runtime_error_rate_threshold_overrides: str | None = None,
        baseline_window_minutes: int = 24 * 60,
        baseline_drift_multiplier: float = 2.5,
        baseline_min_sample_count: int = 3,
        baseline_capture_interval_minutes: int = 10,
        apply_policy_center: bool = True,
        policy_id: str | None = None,
        policy_actor_id: str | None = None,
    ) -> SecurityOpsAlertReport:
        """GET /v1/security/ops/alerts"""
        failed_auth_threshold_overrides = failed_auth_threshold_overrides or ""
        rate_limit_threshold_overrides = rate_limit_threshold_overrides or ""
        private_runtime_error_threshold_overrides = private_runtime_error_threshold_overrides or ""
        private_runtime_error_rate_threshold_overrides = private_runtime_error_rate_threshold_overrides or ""
        policy_id = policy_id or ""
        policy_actor_id = policy_actor_id or ""
        async with self._http() as http:
            resp = await http.get(
                f"{self.runtime_url}/v1/security/ops/alerts"
                f"?window_minutes={window_minutes}"
                f"&failed_auth_threshold={failed_auth_threshold}"
                f"&rate_limit_threshold={rate_limit_threshold}"
                f"&private_runtime_error_threshold={private_runtime_error_threshold}"
                f"&private_runtime_error_rate_threshold={private_runtime_error_rate_threshold}"
                f"&private_runtime_min_requests={private_runtime_min_requests}"
                f"&dimension_limit={dimension_limit}"
                f"&alert_cooldown_minutes={alert_cooldown_minutes}"
                f"&failed_auth_threshold_overrides={failed_auth_threshold_overrides}"
                f"&rate_limit_threshold_overrides={rate_limit_threshold_overrides}"
                f"&private_runtime_error_threshold_overrides={private_runtime_error_threshold_overrides}"
                f"&private_runtime_error_rate_threshold_overrides={private_runtime_error_rate_threshold_overrides}"
                f"&baseline_window_minutes={baseline_window_minutes}"
                f"&baseline_drift_multiplier={baseline_drift_multiplier}"
                f"&baseline_min_sample_count={baseline_min_sample_count}"
                f"&baseline_capture_interval_minutes={baseline_capture_interval_minutes}"
                f"&apply_policy_center={str(apply_policy_center).lower()}"
                f"&policy_id={policy_id}"
                f"&policy_actor_id={policy_actor_id}"
            )
            resp.raise_for_status()
            return SecurityOpsAlertReport(**resp.json())

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
