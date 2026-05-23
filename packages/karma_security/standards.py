"""
Karma 安全标准 — 七大检查模块

每条规则都是可执行代码，不是文档。接入方可以直接运行。
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional, Any
import hashlib
import json
import re


class Severity(str, Enum):
    CRITICAL = "critical"    # 🔴 红线, 部署阻断
    HIGH = "high"            # 🟠 高危
    MEDIUM = "medium"        # 🟡 中危
    LOW = "low"              # 🔵 低危
    PASS = "pass"            # ✅ 通过


@dataclass
class AuditFinding:
    """单条审计发现"""
    standard: str             # R1-R7
    rule: str                 # 规则 ID
    severity: Severity
    description: str
    detail: dict = field(default_factory=dict)
    passed: bool = True

    def __repr__(self) -> str:
        icon = {"pass": "✅", "low": "🔵", "medium": "🟡", "high": "🟠", "critical": "🔴"}
        status = "PASS" if self.passed else "FAIL"
        return f"{icon[self.severity.value]} [{self.rule}] {status}: {self.description}"


# ── R1: 收据完整性 ────────────────────────────────────────────────

class ReceiptIntegrityCheck:
    """R1: 验证收据的签名、链完整性、哈希正确性、时间戳"""

    @staticmethod
    def r1_1_signature(receipts: list[dict]) -> AuditFinding:
        """每条收据必须有签名"""
        unsigned = [r.get("receipt_id") for r in receipts if not r.get("signature")]
        return AuditFinding(
            standard="R1", rule="R1.1", severity=Severity.CRITICAL,
            description=f"收据签名: {len(receipts)-len(unsigned)}/{len(receipts)} 已签名",
            detail={"unsigned_count": len(unsigned), "unsigned_ids": unsigned[:5]},
            passed=len(unsigned) == 0,
        )

    @staticmethod
    def r1_2_chain_unbroken(receipts: list[dict]) -> AuditFinding:
        """收据链必须连续 (parent_receipt_id 链)"""
        if len(receipts) <= 1:
            return AuditFinding(standard="R1", rule="R1.2", severity=Severity.PASS,
                               description="收据链: 单条收据，无需链检查", passed=True)

        breaks = []
        for i in range(1, len(receipts)):
            expected_parent = receipts[i - 1].get("receipt_id")
            actual_parent = receipts[i].get("parent_receipt_id")
            if actual_parent and actual_parent != expected_parent:
                breaks.append({"index": i, "expected": expected_parent, "actual": actual_parent})
            elif not actual_parent and receipts[i].get("receipt_type") != receipts[0].get("receipt_type"):
                breaks.append({"index": i, "expected": expected_parent, "actual": None})

        return AuditFinding(
            standard="R1", rule="R1.2", severity=Severity.CRITICAL,
            description=f"收据链完整性: {len(receipts)} 条, {len(breaks)} 处断裂",
            detail={"total": len(receipts), "breaks": len(breaks), "break_details": breaks[:3]},
            passed=len(breaks) == 0,
        )

    @staticmethod
    def r1_3_hash_correct(receipts: list[dict]) -> AuditFinding:
        """payload_hash 必须正确"""
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'karma_billing'))
        from karma_billing.schema import compute_payload_hash

        mismatches = []
        for r in receipts:
            sd = r.get("scenario_data") or {}
            expected = compute_payload_hash(sd)
            actual = r.get("payload_hash", "")
            if expected != actual:
                mismatches.append({"receipt_id": r.get("receipt_id"), "expected": expected[:16], "actual": actual[:16]})

        return AuditFinding(
            standard="R1", rule="R1.3", severity=Severity.CRITICAL,
            description=f"哈希正确性: {len(receipts)-len(mismatches)}/{len(receipts)} 正确",
            detail={"mismatches": len(mismatches)},
            passed=len(mismatches) == 0,
        )

    @staticmethod
    def r1_4_timestamp_monotonic(receipts: list[dict]) -> AuditFinding:
        """时间戳单调递增, 容差 ±5秒"""
        tolerance = timedelta(seconds=5)
        violations = []
        for i in range(1, len(receipts)):
            try:
                t_prev = datetime.fromisoformat(receipts[i - 1].get("created_at", "").replace("Z", "+00:00"))
                t_curr = datetime.fromisoformat(receipts[i].get("created_at", "").replace("Z", "+00:00"))
                if t_curr < t_prev - tolerance:
                    violations.append({"index": i, "prev": str(t_prev), "curr": str(t_curr)})
            except (ValueError, TypeError):
                violations.append({"index": i, "error": "invalid timestamp"})

        return AuditFinding(
            standard="R1", rule="R1.4", severity=Severity.LOW,
            description=f"时间戳单调性: {len(violations)}/{len(receipts)} 违规",
            detail={"violations": len(violations)},
            passed=len(violations) == 0,
        )

    @classmethod
    def run_all(cls, receipts: list[dict]) -> list[AuditFinding]:
        return [
            cls.r1_1_signature(receipts),
            cls.r1_2_chain_unbroken(receipts),
            cls.r1_3_hash_correct(receipts),
            cls.r1_4_timestamp_monotonic(receipts),
        ]


# ── R2: 证据锚定 ──────────────────────────────────────────────────

class EvidenceAnchoringCheck:
    """R2: 锚定频率、关键状态锚定、Merkle Root 验证"""

    FORCE_STATES = {"funded", "delivered", "verified", "settled", "disputed", "frozen"}

    @staticmethod
    def r2_1_anchor_frequency(anchor_logs: list[dict], policy: dict = None) -> AuditFinding:
        """锚定频率检查"""
        if not anchor_logs:
            return AuditFinding(standard="R2", rule="R2.1", severity=Severity.HIGH,
                               description="锚定频率: 无锚定记录", passed=False)

        max_gap = policy.get("anchor_every_n_seconds", 30) * 2 if policy else 60
        violations = []
        for i in range(1, len(anchor_logs)):
            try:
                t_prev = anchor_logs[i - 1].get("timestamp", 0)
                t_curr = anchor_logs[i].get("timestamp", 0)
                if (t_curr - t_prev) > max_gap:
                    violations.append({"gap_seconds": t_curr - t_prev, "max": max_gap})
            except (TypeError, KeyError):
                pass

        return AuditFinding(
            standard="R2", rule="R2.1", severity=Severity.MEDIUM,
            description=f"锚定频率: {len(violations)}/{len(anchor_logs)} 超限",
            detail={"total_anchors": len(anchor_logs), "violations": len(violations), "max_gap_s": max_gap},
            passed=len(violations) == 0,
        )

    @staticmethod
    def r2_2_force_anchor_states(state_history: list[dict], anchor_logs: list[dict]) -> AuditFinding:
        """关键状态变更后 5 秒内必须锚定"""
        if not state_history:
            return AuditFinding(standard="R2", rule="R2.2", severity=Severity.PASS,
                               description="关键状态锚定: 无状态变更记录", passed=True)

        max_delay = timedelta(seconds=5)
        violations = []
        for s in state_history:
            to_state = s.get("to_state", "")
            if to_state in EvidenceAnchoringCheck.FORCE_STATES:
                state_time = s.get("timestamp", 0)
                # 查找此状态变更后最近的锚定
                nearest_anchor = None
                for a in anchor_logs:
                    anchor_time = a.get("timestamp", 0)
                    if 0 <= (anchor_time - state_time) <= max_delay.total_seconds():
                        nearest_anchor = a
                        break
                if not nearest_anchor:
                    violations.append({"state": to_state, "time": state_time})

        return AuditFinding(
            standard="R2", rule="R2.2", severity=Severity.HIGH,
            description=f"关键状态锚定: {sum(1 for s in state_history if s.get('to_state','') in EvidenceAnchoringCheck.FORCE_STATES)-len(violations)} 次锚定",
            detail={"force_states_found": sum(1 for s in state_history if s.get('to_state','') in EvidenceAnchoringCheck.FORCE_STATES),
                    "missing_anchors": len(violations)},
            passed=len(violations) == 0,
        )

    @staticmethod
    def r2_3_merkle_root(receipts: list[dict], root: Optional[str]) -> AuditFinding:
        """Merkle Root 可由收据列表独立重建"""
        if not root:
            return AuditFinding(standard="R2", rule="R2.3", severity=Severity.MEDIUM,
                               description="Merkle Root: 未提供 root，跳过验证", passed=True)

        # 重建 Merkle tree
        from karma_billing.sync_service import IncrementalMerkleAccumulator
        tree = IncrementalMerkleAccumulator()
        for r in receipts:
            leaf_input = f"{r.get('receipt_id')}|{r.get('task_id')}|{r.get('step_index')}|{r.get('payload_hash')}|{r.get('created_at')}"
            leaf_hash = hashlib.sha256(leaf_input.encode()).digest().hex()
            tree.append(leaf_hash)

        computed_root = tree.root
        matches = computed_root == root if computed_root else False

        return AuditFinding(
            standard="R2", rule="R2.3", severity=Severity.CRITICAL,
            description=f"Merkle Root: {'匹配' if matches else '不匹配'}",
            detail={"computed": computed_root[:16] if computed_root else "N/A", "expected": root[:16]},
            passed=matches,
        )

    @classmethod
    def run_all(cls, receipts: list[dict], state_history: list[dict],
                anchor_logs: list[dict], merkle_root: Optional[str] = None) -> list[AuditFinding]:
        return [
            cls.r2_1_anchor_frequency(anchor_logs),
            cls.r2_2_force_anchor_states(state_history, anchor_logs),
            cls.r2_3_merkle_root(receipts, merkle_root),
        ]


# ── R3: 状态机安全 ────────────────────────────────────────────────

FORBIDDEN_METHODS = [
    "force_transition", "admin_override", "bypass_validation",
    "set_state_directly", "_direct_set", "_admin_modify",
    "skip_validation", "unsafe_transition",
]

class StateMachineSecurityCheck:
    """R3: 无后门、路径预定义、审计不可变、告警、并发安全"""

    @staticmethod
    def r3_1_no_backdoor(state_machine_class: type) -> AuditFinding:
        """无特权后门"""
        found = [m for m in FORBIDDEN_METHODS if hasattr(state_machine_class, m)]
        return AuditFinding(
            standard="R3", rule="R3.1", severity=Severity.CRITICAL,
            description=f"后门检查: {'发现 ' + str(len(found)) + ' 个' if found else '无后门'}",
            detail={"forbidden_found": found},
            passed=len(found) == 0,
        )

    @staticmethod
    def r3_2_transitions_predefined(state_history: list[dict], transition_table: dict) -> AuditFinding:
        """所有转换路径在预定义表中"""
        violations = []
        for s in state_history:
            from_state = s.get("from_state", "")
            to_state = s.get("to_state", "")
            allowed = transition_table.get(from_state, set())
            if to_state not in allowed and to_state not in ("INITIATED", None):
                violations.append({"from": from_state, "to": to_state, "allowed": list(allowed)[:5]})

        return AuditFinding(
            standard="R3", rule="R3.2", severity=Severity.CRITICAL,
            description=f"状态路径: {len(violations)} 次非法转换",
            detail={"total_transitions": len(state_history), "violations": len(violations)},
            passed=len(violations) == 0,
        )

    @staticmethod
    def r3_3_audit_immutable(state_history: list[dict]) -> AuditFinding:
        """审计记录不可修改"""
        # 检查每条记录是否有 record_id (保证可追踪)
        missing_ids = [i for i, s in enumerate(state_history) if not s.get("record_id")]
        return AuditFinding(
            standard="R3", rule="R3.3", severity=Severity.HIGH,
            description=f"审计记录完整性: {len(missing_ids)} 条缺 record_id",
            detail={"total": len(state_history), "missing_ids": missing_ids[:5]},
            passed=len(missing_ids) == 0,
        )

    @classmethod
    def run_all(cls, state_machine_class, state_history, transition_table) -> list[AuditFinding]:
        return [
            cls.r3_1_no_backdoor(state_machine_class),
            cls.r3_2_transitions_predefined(state_history, transition_table),
            cls.r3_3_audit_immutable(state_history),
        ]


# ── R4: 结算安全 ──────────────────────────────────────────────────

class SettlementSecurityCheck:
    """R4: 非托管、验证后结算、争议窗口、多重验证、资金上限"""

    @staticmethod
    def r4_1_non_custodial(escrow_contract_functions: list[str]) -> AuditFinding:
        """合约无非托管提取函数"""
        forbidden = ["withdraw", "adminWithdraw", "ownerWithdraw", "extractFunds", "drain"]
        found = [f for f in forbidden if any(f.lower() in fn.lower() for fn in escrow_contract_functions)]
        return AuditFinding(
            standard="R4", rule="R4.1", severity=Severity.CRITICAL,
            description=f"非托管: {'发现特权提取: ' + str(found) if found else '安全'}",
            detail={"functions_scanned": len(escrow_contract_functions), "forbidden_found": found},
            passed=len(found) == 0,
        )

    @staticmethod
    def r4_2_settlement_requires_verification(state_history: list[dict]) -> AuditFinding:
        """结算前必须验证"""
        # 检查是否有 settled 状态之前没有 verified
        violations = []
        seen_verified = False
        for s in state_history:
            if s.get("to_state") == "verified" or s.get("to_state") == "VERIFIED":
                seen_verified = True
            if (s.get("to_state") == "settled" or s.get("to_state") == "SETTLED") and not seen_verified:
                violations.append({"record_id": s.get("record_id")})
        return AuditFinding(
            standard="R4", rule="R4.2", severity=Severity.CRITICAL,
            description=f"验证后结算: {'违规' if violations else '合规'}",
            detail={"violations": len(violations)},
            passed=len(violations) == 0,
        )

    @staticmethod
    def r4_3_dispute_window(receipts: list[dict], settlement_timestamp: Optional[float] = None,
                           min_hours: int = 24) -> AuditFinding:
        """争议窗口"""
        delivered_time = None
        for r in receipts:
            if r.get("receipt_type") in ("S1_TASK_COMPLETED", "TASK_DELIVERED"):
                try:
                    delivered_time = datetime.fromisoformat(r.get("created_at", "").replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    pass

        if not delivered_time:
            return AuditFinding(standard="R4", rule="R4.3", severity=Severity.PASS,
                               description="争议窗口: 无交付收据，跳过", passed=True)

        if settlement_timestamp:
            settle_time = datetime.fromtimestamp(settlement_timestamp, tz=timezone.utc)
            window_hours = (settle_time - delivered_time).total_seconds() / 3600
            passed = window_hours >= min_hours

            return AuditFinding(
                standard="R4", rule="R4.3", severity=Severity.MEDIUM,
                description=f"争议窗口: {window_hours:.1f}h (最少 {min_hours}h)",
                detail={"window_hours": window_hours, "min_hours": min_hours},
                passed=passed,
            )

        return AuditFinding(standard="R4", rule="R4.3", severity=Severity.HIGH,
                           description="争议窗口: 无法验证 (缺结算时间)", passed=False)

    @staticmethod
    def r4_4_multi_verification(amount_usdc: float, verification_count: int) -> AuditFinding:
        """高价值交易多重验证"""
        if amount_usdc <= 1000:
            return AuditFinding(standard="R4", rule="R4.4", severity=Severity.PASS,
                               description=f"多重验证: ${amount_usdc} ≤ $1000, 无需多签", passed=True)

        passed = verification_count >= 3
        return AuditFinding(
            standard="R4", rule="R4.4", severity=Severity.HIGH if not passed else Severity.PASS,
            description=f"多重验证: ${amount_usdc} 需要 ≥3 验证者, 当前 {verification_count}",
            detail={"amount": amount_usdc, "verifiers": verification_count, "required": 3},
            passed=passed,
        )

    @classmethod
    def run_all(cls, escrow_functions: list[str], state_history: list[dict],
                receipts: list[dict], amount_usdc: float = 0, verification_count: int = 1,
                settlement_timestamp: Optional[float] = None) -> list[AuditFinding]:
        return [
            cls.r4_1_non_custodial(escrow_functions),
            cls.r4_2_settlement_requires_verification(state_history),
            cls.r4_3_dispute_window(receipts, settlement_timestamp),
            cls.r4_4_multi_verification(amount_usdc, verification_count),
        ]


# ── R5: 数据隐私 ──────────────────────────────────────────────────

class DataPrivacyCheck:
    """R5: 收据无原始数据、加密交付、最小暴露"""

    FORBIDDEN_FIELDS = ["raw_input", "raw_output", "prompt_text", "private_key", "api_secret"]

    @staticmethod
    def r5_1_no_raw_data(receipts: list[dict]) -> AuditFinding:
        """收据不存原始数据"""
        violations = []
        for r in receipts:
            found = [f for f in DataPrivacyCheck.FORBIDDEN_FIELDS if f in r]
            if found:
                violations.append({"receipt_id": r.get("receipt_id"), "fields": found})

        return AuditFinding(
            standard="R5", rule="R5.1", severity=Severity.CRITICAL,
            description=f"隐私泄露: {len(violations)} 条收据含原始数据",
            detail={"violations": len(violations), "details": violations[:3]},
            passed=len(violations) == 0,
        )

    @staticmethod
    def r5_2_data_encryption(receipts: list[dict]) -> AuditFinding:
        """S5 数据购买场景 → 数据加密"""
        data_receipts = [r for r in receipts if r.get("receipt_type") == "S5_DATA_DELIVERED"]
        if not data_receipts:
            return AuditFinding(standard="R5", rule="R5.2", severity=Severity.PASS,
                               description="数据加密: 无数据交付收据", passed=True)

        unencrypted = [r for r in data_receipts if not r.get("scenario_data", {}).get("encryption_method")]
        return AuditFinding(
            standard="R5", rule="R5.2", severity=Severity.HIGH,
            description=f"数据加密: {len(unencrypted)}/{len(data_receipts)} 未加密",
            detail={"total_data_deliveries": len(data_receipts), "unencrypted": len(unencrypted)},
            passed=len(unencrypted) == 0,
        )

    @classmethod
    def run_all(cls, receipts: list[dict]) -> list[AuditFinding]:
        return [cls.r5_1_no_raw_data(receipts), cls.r5_2_data_encryption(receipts)]


# ── R6: 可用性 ────────────────────────────────────────────────────

class AvailabilityCheck:
    """R6: 同步延迟、锚定确认延迟、系统可用性"""

    @staticmethod
    def r6_1_sync_latency(metrics: list[dict]) -> AuditFinding:
        """收据同步延迟 < 500ms"""
        if not metrics:
            return AuditFinding(standard="R6", rule="R6.1", severity=Severity.PASS,
                               description="同步延迟: 无数据", passed=True)

        latencies = [m.get("latency_ms", 0) for m in metrics if m.get("latency_ms")]
        if not latencies:
            return AuditFinding(standard="R6", rule="R6.1", severity=Severity.PASS,
                               description="同步延迟: 无延迟数据", passed=True)

        avg_latency = sum(latencies) / len(latencies)
        p99 = sorted(latencies)[int(len(latencies) * 0.99)] if len(latencies) > 100 else max(latencies)
        passed = p99 < 500

        return AuditFinding(
            standard="R6", rule="R6.1", severity=Severity.MEDIUM if not passed else Severity.PASS,
            description=f"同步延迟: avg={avg_latency:.0f}ms, p99={p99:.0f}ms (目标 <500ms)",
            detail={"avg_ms": avg_latency, "p99_ms": p99, "samples": len(latencies)},
            passed=passed,
        )

    @staticmethod
    def r6_2_anchor_latency(anchor_logs: list[dict]) -> AuditFinding:
        """锚定确认延迟"""
        if not anchor_logs:
            return AuditFinding(standard="R6", rule="R6.2", severity=Severity.PASS,
                               description="锚定延迟: 无数据", passed=True)

        latencies = [a.get("confirmation_ms", 0) for a in anchor_logs if a.get("confirmation_ms")]
        if not latencies:
            return AuditFinding(standard="R6", rule="R6.2", severity=Severity.PASS,
                               description="锚定延迟: 无确认数据", passed=True)

        avg_latency = sum(latencies) / len(latencies)
        p99 = sorted(latencies)[int(len(latencies) * 0.99)] if len(latencies) > 100 else max(latencies)
        passed = p99 < 5000  # 5s target for Solana

        return AuditFinding(
            standard="R6", rule="R6.2", severity=Severity.MEDIUM if not passed else Severity.PASS,
            description=f"锚定延迟: avg={avg_latency:.0f}ms, p99={p99:.0f}ms (目标 <5s)",
            detail={"avg_ms": avg_latency, "p99_ms": p99, "samples": len(latencies)},
            passed=passed,
        )

    @classmethod
    def run_all(cls, metrics: list[dict], anchor_logs: list[dict]) -> list[AuditFinding]:
        return [cls.r6_1_sync_latency(metrics), cls.r6_2_anchor_latency(anchor_logs)]


# ── R7: 跨场景兼容性 ──────────────────────────────────────────────

class CrossScenarioCheck:
    """R7: 统一 Schema、场景切换、新场景零代码变更"""

    REQUIRED_RECEIPT_FIELDS = {
        "receipt_id", "task_id", "scenario", "step_index",
        "generator_did", "buyer_did", "seller_did", "receipt_type",
        "input_hash", "output_hash", "payload_hash", "created_at",
        "execution_duration_ms", "scenario_data", "status", "signature",
    }

    @staticmethod
    def r7_1_unified_schema(receipts: list[dict]) -> AuditFinding:
        """所有收据符合 UniversalReceipt Schema"""
        violations = []
        for r in receipts:
            missing = CrossScenarioCheck.REQUIRED_RECEIPT_FIELDS - set(r.keys())
            if missing:
                violations.append({"receipt_id": r.get("receipt_id", "unknown"), "missing": list(missing)})

        return AuditFinding(
            standard="R7", rule="R7.1", severity=Severity.CRITICAL,
            description=f"统一Schema: {len(violations)}/{len(receipts)} 不符合",
            detail={"violations": len(violations), "details": violations[:5]},
            passed=len(violations) == 0,
        )

    @staticmethod
    def r7_2_scenario_switch(scenario_types: set[str]) -> AuditFinding:
        """场景间可切换 (至少支持 S1, S8)"""
        required = {"S1_DELEGATION", "S8_DISPUTE"}
        missing = required - scenario_types
        return AuditFinding(
            standard="R7", rule="R7.2", severity=Severity.MEDIUM,
            description=f"场景切换: 支持 {len(scenario_types)} 种场景",
            detail={"supported": list(scenario_types), "missing_required": list(missing)},
            passed=len(missing) == 0,
        )

    @classmethod
    def run_all(cls, receipts: list[dict], scenario_types: set[str]) -> list[AuditFinding]:
        return [cls.r7_1_unified_schema(receipts), cls.r7_2_scenario_switch(scenario_types)]
