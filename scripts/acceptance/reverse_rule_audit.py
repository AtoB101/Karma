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


def check_testnet_stack_files(failures: list[str]) -> None:
    for rel in (
        "deploy/docker-compose.testnet.yml",
        "deploy/.env.testnet-stack.example",
        "deploy/TESTNET_STACK-zh.md",
        "scripts/maintenance/expire_payment_intents.py",
    ):
        if not (ROOT / rel).is_file():
            _fail(f"missing {rel}", failures)


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


def check_important_fields_secure_path(failures: list[str]) -> None:
    """KSA-IF: protocol capture + encrypted submit + triple match must stay wired."""
    catalog = ROOT / "packages/evidence-schema/important-fields-standard.v1.json"
    if not catalog.is_file():
        _fail("missing important-fields-standard.v1.json", failures)
    else:
        text = catalog.read_text(encoding="utf-8")
        if "karma-important-fields-v1" not in text:
            _fail("important-fields catalog missing schema_version marker", failures)
        for scene in (
            "ride_hailing",
            "hotel_booking",
            "food_delivery",
            "flight_booking",
            "b2b_procurement",
            "data_api_billing",
        ):
            if f'"scene_id": "{scene}"' not in text and f'"scene_id":"{scene}"' not in text:
                _fail(f"important-fields catalog missing scene {scene}", failures)

    app = _read("api/app.py")
    if 'prefix="/v1/standards"' not in app:
        _fail("api/app.py missing /v1/standards router", failures)

    standards = _read("api/routes/standards.py")
    for needle in (
        "match-secure",
        "submit-encrypted",
        "/important-fields/captures",
        "finalize_triple_match",
    ):
        if needle not in standards:
            _fail(f"standards route missing secure path piece: {needle}", failures)

    capture = _read("services/important_fields_capture.py")
    for needle in (
        "finalize_triple_match",
        "submit_encrypted",
        "MAX_ATTEMPTS_PER_CAPTURE",
        "nonce already used",
        "karma1.",
    ):
        if needle not in capture:
            _fail(f"important_fields_capture missing guard: {needle}", failures)

    crypto = _read("services/important_fields_crypto.py")
    for needle in ("AESGCM", "capture_session_key", "PREFIX", "karma1."):
        if needle not in crypto:
            _fail(f"important_fields_crypto missing {needle}", failures)

    # Secure submit must reject plaintext envelopes
    if 'startswith("karma1.")' not in capture and "startswith('karma1.')" not in capture:
        _fail("submit path must require karma1. ciphertext prefix", failures)

    onboarding = ROOT / "packages/evidence-schema/agent-onboarding-template.v1.json"
    if not onboarding.is_file():
        _fail("missing agent-onboarding-template.v1.json", failures)
    else:
        ob = onboarding.read_text(encoding="utf-8")
        if "karma-agent-onboarding-v1" not in ob:
            _fail("onboarding catalog missing schema_version marker", failures)
        for profile in ("user", "merchant", "enterprise"):
            if f'"{profile}"' not in ob:
                _fail(f"onboarding catalog missing profile {profile}", failures)
    standards = _read("api/routes/standards.py")
    if "/onboarding" not in standards or "materialize_onboarding" not in standards:
        _fail("standards routes missing onboarding template APIs", failures)
    agents = _read("api/routes/agents.py")
    if "connect-from-template" not in agents:
        _fail("agents routes missing connect-from-template", failures)

    # Human confirmation policy — real-scene AUTO vs OWNER_CONFIRM split
    conf_catalog = ROOT / "packages/evidence-schema/human-confirmation-policy.v1.json"
    if not conf_catalog.is_file():
        _fail("missing human-confirmation-policy.v1.json", failures)
    else:
        conf_text = conf_catalog.read_text(encoding="utf-8")
        if "karma-human-confirmation-v1" not in conf_text:
            _fail("confirmation policy missing schema_version marker", failures)
        for scene in (
            "ride_hailing",
            "food_delivery",
            "hotel_booking",
            "flight_booking",
            "b2b_procurement",
        ):
            if f'"{scene}"' not in conf_text:
                _fail(f"confirmation policy missing scene {scene}", failures)
        for mode in ("AUTO", "OWNER_CONFIRM", "POLICY_AUTO"):
            if mode not in conf_text:
                _fail(f"confirmation policy missing gate mode {mode}", failures)

    standards = _read("api/routes/standards.py")
    if "/confirmation-policy" not in standards:
        _fail("standards routes missing confirmation-policy APIs", failures)

    conf_routes = _read("api/routes/confirmations.py")
    for needle in ("/plan", "/sessions", "/decide", "assert_step_allowed"):
        if needle not in conf_routes:
            _fail(f"confirmations routes missing {needle}", failures)

    app = _read("api/app.py")
    if 'prefix="/v1/confirmations"' not in app:
        _fail("api/app.py missing /v1/confirmations router", failures)

    fulfill = _read("services/intent_fulfillment.py")
    for needle in (
        "awaiting_owner_confirmation",
        "require_owner_confirmation",
        "assert_step_allowed",
        "task_type_to_scene_id",
    ):
        if needle not in fulfill:
            _fail(f"intent_fulfillment missing confirmation gate: {needle}", failures)

    # Agent boundary — every connected agent publishes capability/responsibility/confirmation
    boundary_cat = ROOT / "packages/evidence-schema/agent-boundary.v1.json"
    if not boundary_cat.is_file():
        _fail("missing agent-boundary.v1.json", failures)
    else:
        bt = boundary_cat.read_text(encoding="utf-8")
        if "karma-agent-boundary-v1" not in bt:
            _fail("agent-boundary catalog missing schema_version marker", failures)
        for part in ("capability_boundary", "responsibility_boundary", "confirmation_boundary"):
            if part not in bt:
                _fail(f"agent-boundary catalog missing {part}", failures)

    standards = _read("api/routes/standards.py")
    if "/agent-boundary" not in standards:
        _fail("standards routes missing agent-boundary API", failures)

    agents = _read("api/routes/agents.py")
    if "/boundary" not in agents and '"{agent_id}/boundary"' not in agents:
        if '/{agent_id}/boundary' not in agents:
            _fail("agents routes missing GET /{agent_id}/boundary", failures)

    directory = _read("services/agent_directory.py")
    for needle in ("ensure_boundary", "agent_boundary", "boundary_digest"):
        if needle not in directory:
            _fail(f"agent_directory missing boundary wiring: {needle}", failures)

    boundary_svc = _read("services/agent_boundary.py")
    for needle in (
        "materialize_agent_boundary",
        "capability_boundary",
        "responsibility_boundary",
        "confirmation_boundary",
        "boundary_complete",
    ):
        if needle not in boundary_svc:
            _fail(f"agent_boundary service missing {needle}", failures)


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
        check_testnet_stack_files,
        check_acceptance_scripts_executable,
        check_important_fields_secure_path,
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
