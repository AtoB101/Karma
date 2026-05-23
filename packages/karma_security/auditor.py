"""
SecurityAuditor — 运行全部 7 大安全标准检查，生成合规报告。

这是 Karma 安全标准的可执行实现。任何接入方可以独立运行。
"""

from dataclasses import dataclass, field
from typing import Optional, Any
from datetime import datetime, timezone
import json

from .standards import (
    Severity, AuditFinding,
    ReceiptIntegrityCheck,
    EvidenceAnchoringCheck,
    StateMachineSecurityCheck,
    SettlementSecurityCheck,
    DataPrivacyCheck,
    AvailabilityCheck,
    CrossScenarioCheck,
)


@dataclass
class AuditReport:
    """安全审计报告"""
    version: str = "KARMA_SECURITY_V1"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    findings: list[AuditFinding] = field(default_factory=list)
    
    @property
    def total_checks(self) -> int:
        return len(self.findings)
    
    @property
    def passed(self) -> int:
        return sum(1 for f in self.findings if f.passed)
    
    @property
    def failed(self) -> int:
        return sum(1 for f in self.findings if not f.passed)
    
    @property
    def criticals(self) -> int:
        return sum(1 for f in self.findings if not f.passed and f.severity == Severity.CRITICAL)
    
    @property
    def highs(self) -> int:
        return sum(1 for f in self.findings if not f.passed and f.severity == Severity.HIGH)
    
    @property
    def score(self) -> float:
        """0.0 - 10.0 的安全评分"""
        if not self.findings:
            return 10.0
        
        weights = {
            Severity.CRITICAL: 4.0,
            Severity.HIGH: 2.0,
            Severity.MEDIUM: 1.0,
            Severity.LOW: 0.5,
        }
        
        max_penalty = sum(weights.get(f.severity, 0) for f in self.findings) * 1.0
        actual_penalty = sum(weights.get(f.severity, 0) for f in self.findings if not f.passed)
        
        if max_penalty == 0:
            return 10.0
        
        return round(10.0 * (1.0 - actual_penalty / max_penalty), 1)
    
    @property
    def status(self) -> str:
        s = self.score
        if s >= 9.0 and self.criticals == 0:
            return "GREEN"
        elif s >= 7.0 and self.criticals == 0:
            return "YELLOW"
        elif s >= 5.0:
            return "ORANGE"
        else:
            return "RED"
    
    def summary(self) -> str:
        lines = [
            "=" * 60,
            f"  🛡️  KARMA SECURITY AUDIT — {self.status}",
            "=" * 60,
            f"  Version:    {self.version}",
            f"  Time:       {self.timestamp}",
            f"  Score:      {self.score}/10.0",
            f"  Checks:     {self.passed}/{self.total_checks} passed",
            f"  Critical:   {self.criticals}  |  High: {self.highs}  |  Failed: {self.failed}",
            "",
        ]
        
        by_standard = {}
        for f in self.findings:
            by_standard.setdefault(f.standard, []).append(f)
        
        for std in sorted(by_standard.keys()):
            findings = by_standard[std]
            p = sum(1 for f in findings if f.passed)
            lines.append(f"  {std}: {p}/{len(findings)}")
            for f in findings:
                lines.append(f"    {f}")
        
        lines.append("=" * 60)
        return "\n".join(lines)
    
    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "timestamp": self.timestamp,
            "score": self.score,
            "status": self.status,
            "total_checks": self.total_checks,
            "passed": self.passed,
            "failed": self.failed,
            "critical_failures": self.criticals,
            "high_failures": self.highs,
            "findings": [
                {
                    "standard": f.standard,
                    "rule": f.rule,
                    "severity": f.severity.value,
                    "description": f.description,
                    "passed": f.passed,
                    "detail": f.detail,
                }
                for f in self.findings
            ],
        }


class SecurityAuditor:
    """
    安全审计器 — 可执行的安全标准合规检查。

    Usage:
        auditor = SecurityAuditor()
        report = auditor.audit(
            receipts=task_receipts,
            state_history=state_transitions,
            anchor_logs=anchor_records,
            escrow_functions=["deposit", "release", "refund"],
            state_machine_class=ImmutableBillingStateMachine,
            transition_table=BILLING_STATE_TRANSITIONS,
            amount_usdc=50.00,
        )
        print(report.summary())
    """
    
    def audit(
        self,
        receipts: list[dict],
        state_history: Optional[list[dict]] = None,
        anchor_logs: Optional[list[dict]] = None,
        escrow_functions: Optional[list[str]] = None,
        state_machine_class: Optional[type] = None,
        transition_table: Optional[dict] = None,
        merkle_root: Optional[str] = None,
        amount_usdc: float = 0,
        verification_count: int = 1,
        settlement_timestamp: Optional[float] = None,
        metrics: Optional[list[dict]] = None,
        scenario_types: Optional[set[str]] = None,
    ) -> AuditReport:
        """运行所有安全标准检查"""
        
        findings = []
        
        # R1: 收据完整性
        findings.extend(ReceiptIntegrityCheck.run_all(receipts))
        
        # R2: 证据锚定
        findings.extend(EvidenceAnchoringCheck.run_all(
            receipts,
            state_history or [],
            anchor_logs or [],
            merkle_root,
        ))
        
        # R3: 状态机安全
        if state_machine_class and transition_table:
            findings.extend(StateMachineSecurityCheck.run_all(
                state_machine_class,
                state_history or [],
                transition_table,
            ))
        
        # R4: 结算安全
        findings.extend(SettlementSecurityCheck.run_all(
            escrow_functions or [],
            state_history or [],
            receipts,
            amount_usdc,
            verification_count,
            settlement_timestamp,
        ))
        
        # R5: 数据隐私
        findings.extend(DataPrivacyCheck.run_all(receipts))
        
        # R6: 可用性
        findings.extend(AvailabilityCheck.run_all(
            metrics or [],
            anchor_logs or [],
        ))
        
        # R7: 跨场景兼容性
        findings.extend(CrossScenarioCheck.run_all(
            receipts,
            scenario_types or set(),
        ))
        
        return AuditReport(findings=findings)
