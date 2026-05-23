"""
Karma Security Compliance Validator
====================================

Automated validation of Karma deployments against the 7 security standards:
  R1. Receipt Integrity
  R2. Evidence Anchoring
  R3. State Machine Security
  R4. Settlement Security
  R5. Data Privacy
  R6. Availability
  R7. Cross-Scenario Compatibility

Usage:
    from karma_security import SecurityAuditor
    auditor = SecurityAuditor()
    report = await auditor.audit(receipts, state_history, anchor_logs)
    print(report.score)  # 0.0 - 10.0
"""

from .auditor import SecurityAuditor, AuditReport, AuditFinding
from .standards import (
    ReceiptIntegrityCheck,
    EvidenceAnchoringCheck,
    StateMachineSecurityCheck,
    SettlementSecurityCheck,
    DataPrivacyCheck,
    AvailabilityCheck,
    CrossScenarioCheck,
)

__all__ = [
    "SecurityAuditor",
    "AuditReport",
    "AuditFinding",
    "ReceiptIntegrityCheck",
    "EvidenceAnchoringCheck",
    "StateMachineSecurityCheck",
    "SettlementSecurityCheck",
    "DataPrivacyCheck",
    "AvailabilityCheck",
    "CrossScenarioCheck",
]
