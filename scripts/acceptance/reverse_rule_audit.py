#!/usr/bin/env python3
"""
Reverse-rule audit — verify KSA / KSA2 / KSA-TL / KSA-X402 / KSA-AP2 mitigations
are present in code (static guards). Complements pytest attack regressions.

Exit 0 = all checks passed; 1 = one or more failures.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    p = ROOT / rel
    if not p.is_file():
        return ""
    return p.read_text(encoding="utf-8")


def _fail(msg: str, failures: list[str]) -> None:
    failures.append(msg)


def check_no_utcnow_in_trusted_agent(failures: list[str]) -> None:
    tar = ROOT / "trusted_agent_runtime"
    pat = re.compile(r"\butcnow\s*\(")
    for path in sorted(tar.rglob("*.py")):
        if pat.search(path.read_text(encoding="utf-8")):
            _fail(f"datetime.utcnow() in {path.relative_to(ROOT)}", failures)


def check_security_admin_always_auth(failures: list[str]) -> None:
    app = _read("api/app.py")
    if "_security_always_auth" not in app or "get_current_agent_id" not in app:
        _fail("api/app.py missing _security_always_auth / get_current_agent_id", failures)
    if 'prefix="/v1/security"' not in app or 'prefix="/v1/admin"' not in app:
        _fail("api/app.py missing security/admin routers", failures)


def check_receipt_task_guard(failures: list[str]) -> None:
    receipts = _read("api/routes/receipts.py")
    if "ensure_task_contract_exists" not in receipts:
        _fail("KSA-011: receipts route must call ensure_task_contract_exists", failures)


def check_settlement_guards(failures: list[str]) -> None:
    st = _read("api/routes/settlement.py")
    for needle in (
        "ensure_success_execution_receipt_before_seller_payout",
        "assert_lock_does_not_close_payment_cycle",
    ):
        if needle not in st:
            _fail(f"KSA2: settlement missing {needle}", failures)


def check_phase_routers(failures: list[str]) -> None:
    app = _read("api/app.py")
    for prefix in (
        "/v1/payment-intents",
        "/v1/evidence",
        "/v1/x402",
        "/v1/trade",
        "/v1/openclaw",
    ):
        if prefix not in app:
            _fail(f"api/app.py missing router {prefix}", failures)


def check_openapi_verify_external(failures: list[str]) -> None:
    oapi = _read("openapi/karma-v1.yaml")
    if "verify-external" not in oapi:
        _fail("openapi missing /verify-external", failures)


def check_migrations_head(failures: list[str]) -> None:
    mig = ROOT / "db/migrations"
    need = ("0027_phase3_payment_intents.py", "0028_human_not_present_policy.py", "0026_x402_funding_source.py")
    for name in need:
        if not (mig / name).is_file():
            _fail(f"missing migration {name}", failures)


def check_x402_url_safety(failures: list[str]) -> None:
    if "validate_x402_target_url" not in _read("sdk/x402/url_safety.py"):
        _fail("KSA-X402-003: missing validate_x402_target_url", failures)


def check_ap2_adapter(failures: list[str]) -> None:
    ap2 = _read("trusted_agent_runtime/ap2_adapter.py")
    for fn in ("to_ap2_mandate", "from_ap2_mandate", "evidence_digest"):
        if f"def {fn}" not in ap2:
            _fail(f"Phase 3: ap2_adapter missing {fn}", failures)


def check_openclaw_manus_packages(failures: list[str]) -> None:
    if not (ROOT / "packages/karma-openclaw/karma_openclaw/server.py").is_file():
        _fail("missing karma-openclaw package", failures)
    if not (ROOT / "packages/karma-openmanus/karma_openmanus/__init__.py").is_file():
        _fail("missing karma-openmanus package", failures)
    oc = _read("packages/karma-openclaw/karma_openclaw/server.py")
    if "phase2_tools" not in oc and "karma_x402" not in _read("packages/karma-openclaw/karma_openclaw/phase2_tools.py"):
        _fail("openclaw missing phase2 x402 tools module", failures)


def check_acceptance_scripts_executable(failures: list[str]) -> None:
    scripts = [
        "scripts/acceptance/phase1_open_wallet_gate.sh",
        "scripts/acceptance/phase2_x402_gate.sh",
        "scripts/acceptance/phase3_ap2_gate.sh",
        "scripts/acceptance/full_chain_audit_gate.sh",
        "scripts/acceptance/testnet_claw_manus_gate.sh",
    ]
    for rel in scripts:
        p = ROOT / rel
        if not p.is_file():
            _fail(f"missing acceptance script {rel}", failures)


def main() -> int:
    failures: list[str] = []
    checks = [
        check_no_utcnow_in_trusted_agent,
        check_security_admin_always_auth,
        check_receipt_task_guard,
        check_settlement_guards,
        check_phase_routers,
        check_openapi_verify_external,
        check_migrations_head,
        check_x402_url_safety,
        check_ap2_adapter,
        check_openclaw_manus_packages,
        check_acceptance_scripts_executable,
    ]
    for fn in checks:
        fn(failures)
    if failures:
        print("REVERSE RULE AUDIT: FAIL", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print("REVERSE RULE AUDIT: PASS (all static KSA/phase guards present)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
