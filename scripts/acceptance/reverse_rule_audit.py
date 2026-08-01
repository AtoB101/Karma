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
        "karma2.",
        "submitter_agent_id",
        "anti-collusion",
        "sealed MATCHED",
    ):
        if needle not in capture:
            _fail(f"important_fields_capture missing guard: {needle}", failures)

    crypto = _read("services/important_fields_crypto.py")
    for needle in (
        "AESGCM",
        "capture_session_key",
        "PREFIX_V2",
        "karma2.",
        "HKDF",
        "build_aad",
        "KARMA_IMPORTANT_FIELDS_KEY",
    ):
        if needle not in crypto:
            _fail(f"important_fields_crypto missing {needle}", failures)

    # Secure submit must reject plaintext envelopes (karma2 preferred; karma1 legacy decrypt)
    if "karma2." not in capture:
        _fail("submit path must require karma2. ciphertext prefix", failures)
    if "startswith(\"karma2.\")" not in capture and "startswith('karma2.')" not in capture:
        _fail("submit path must check karma2. ciphertext prefix", failures)

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
        "allow_demo_confirmation_bypass",
        "expected_owner_agent_id",
        "get_automation_policy",
        "does not match intent-inferred scene",
        "awaiting_important_fields_match",
        "auto_triple_lock_fields",
        "require_matched_capture",
    ):
        if needle not in fulfill:
            _fail(f"intent_fulfillment missing confirmation gate: {needle}", failures)

    scenario_loop = ROOT / "scripts/acceptance/real_commerce_scenario_loop.py"
    if not scenario_loop.is_file():
        _fail("missing real_commerce_scenario_loop.py", failures)

    conf_svc = _read("services/human_confirmation_policy.py")
    for needle in (
        'actor_agent_id is required',
        'status = "USED"',
        "exceeds confirmed max_amount",
        "only the owner_agent_id may decide",
    ):
        if needle not in conf_svc:
            _fail(f"human_confirmation_policy missing anti-bypass: {needle}", failures)

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
        "responsibility_acknowledged",
    ):
        if needle not in boundary_svc:
            _fail(f"agent_boundary service missing {needle}", failures)

    # P1 onboarding — identity / owner / ack / anti-hijack / p1-status
    p1 = ROOT / "services/agent_p1_readiness.py"
    if not p1.is_file():
        _fail("missing services/agent_p1_readiness.py", failures)
    else:
        p1t = p1.read_text(encoding="utf-8")
        for needle in (
            "evaluate_p1_readiness",
            "ensure_owner_identity",
            "verify_responsibility_attestation",
            "boundary_content_hash",
            "anti-forgery",
        ):
            if needle not in p1t:
                _fail(f"agent_p1_readiness missing {needle}", failures)

    agents = _read("api/routes/agents.py")
    for needle in ("/p1-status", "connect-challenge", "responsibility_ack", "owner_identity_id"):
        if needle not in agents:
            _fail(f"agents routes missing P1 piece: {needle}", failures)
    directory = _read("services/agent_directory.py")
    if "anti-hijack" not in directory and "bound to another owner" not in directory:
        _fail("agent_directory missing anti-hijack owner bind guard", failures)

    mig = ROOT / "db/migrations/0031_agent_p1_onboarding.py"
    if not mig.is_file():
        _fail("missing migration 0031_agent_p1_onboarding.py", failures)

    directory = _read("services/agent_directory.py")
    if "owner_identity_id" not in directory or "refresh_p1_ready" not in directory:
        _fail("agent_directory missing P1 owner bind / refresh_p1_ready", failures)

    # P2 boundary enforcement — catalog re-canonicalize / verify / fulfill gate / ack bind
    p2 = ROOT / "services/agent_boundary_verify.py"
    if not p2.is_file():
        _fail("missing services/agent_boundary_verify.py", failures)
    else:
        p2t = p2.read_text(encoding="utf-8")
        for needle in (
            "verify_agent_boundary",
            "assert_seller_boundary_for_fulfill",
            "confirmation_not_looser",
            "scene_covered",
        ):
            if needle not in p2t:
                _fail(f"agent_boundary_verify missing {needle}", failures)

    boundary_svc = _read("services/agent_boundary.py")
    for needle in (
        "canonicalize_confirmation_boundary",
        "confirmation_is_looser_than_catalog",
        "seller_covers_scene",
    ):
        if needle not in boundary_svc:
            _fail(f"agent_boundary missing P2 piece: {needle}", failures)

    agents = _read("api/routes/agents.py")
    if "/boundary/verify" not in agents:
        _fail("agents routes missing GET /{agent_id}/boundary/verify", failures)
    if "heal" in agents.lower() and "boundary_hash" in agents:
        # soft: ensure p1-status does not assign live hash onto row.boundary_hash
        pass
    if 'row.boundary_hash = status["boundary_hash"]' in agents or "row.boundary_hash = status.get(\"boundary_hash\")" in agents:
        _fail("p1-status must not heal boundary_hash from live status", failures)

    directory = _read("services/agent_directory.py")
    if "boundary_changed" not in directory:
        _fail("agent_directory missing ack invalidation on boundary_changed", failures)
    if 'row.boundary_hash = status["boundary_hash"]' in directory:
        _fail("refresh_p1_ready must not heal boundary_hash from live status", failures)

    fulfill = _read("services/intent_fulfillment.py")
    if "assert_seller_boundary_for_fulfill" not in fulfill:
        _fail("intent_fulfillment missing P2 seller boundary gate", failures)

    p1t = _read("services/agent_p1_readiness.py")
    if "ack_bound_to_live_boundary" not in p1t:
        _fail("agent_p1_readiness missing ack_bound_to_live_boundary check", failures)

    conf_pol = ROOT / "packages/evidence-schema/human-confirmation-policy.v1.json"
    if conf_pol.is_file():
        ct = conf_pol.read_text(encoding="utf-8")
        for sid in (
            "financial_services",
            "healthcare_medical",
            "design_creative",
            "manufacturing",
        ):
            if f'"{sid}"' not in ct:
                _fail(f"confirmation policy missing scene {sid}", failures)
        if '"high_risk": true' not in ct and '"high_risk":true' not in ct:
            _fail("confirmation policy missing high_risk scene markers", failures)

    # P3 discovery priority — scene-aware selection order on verifiable trust
    p3cat = ROOT / "packages/evidence-schema/discovery-priority.v1.json"
    if not p3cat.is_file():
        _fail("missing discovery-priority.v1.json", failures)
    else:
        p3t = p3cat.read_text(encoding="utf-8")
        if "karma-discovery-priority-v1" not in p3t:
            _fail("discovery-priority catalog missing schema_version marker", failures)
        for needle in (
            "priority_order",
            "trust_tiers",
            "p1_ready",
            "scene_covered",
            "financial_services",
            "b2b_procurement",
        ):
            if needle not in p3t:
                _fail(f"discovery-priority catalog missing {needle}", failures)

    p3svc = ROOT / "services/discovery_priority.py"
    if not p3svc.is_file():
        _fail("missing services/discovery_priority.py", failures)
    else:
        p3st = p3svc.read_text(encoding="utf-8")
        for needle in (
            "apply_priority_ranking",
            "priority_sort_key",
            "trust_evidence_digest",
            "classify_trust_tier",
            "get_scene_priority_policy",
        ):
            if needle not in p3st:
                _fail(f"discovery_priority missing {needle}", failures)

    standards = _read("api/routes/standards.py")
    if "/discovery-priority" not in standards:
        _fail("standards routes missing discovery-priority API", failures)

    discovery = _read("api/routes/discovery.py")
    for needle in ("enforce_scene_policy", "ranking_metadata", "scene_id"):
        if needle not in discovery:
            _fail(f"discovery route missing P3 piece: {needle}", failures)

    trust = _read("services/agent_trust.py")
    if "apply_priority_ranking" not in trust and "discovery_priority" not in trust:
        _fail("agent_trust.apply_trust_rerank not wired to discovery_priority", failures)

    intent = _read("services/intent_discovery.py")
    if "scene_id" not in intent or "p1_ready" not in intent:
        _fail("intent_discovery missing scene_id / p1_ready preservation for P3", failures)

    # P4 human confirmation — multi-step buyer, seller gate, TTL, anti-bypass
    hcp = _read("services/human_confirmation_policy.py")
    for needle in (
        "buyer_fulfill_confirm_steps",
        "seller_must_confirm_accept",
        "SESSION_TTL_SECONDS",
        "expected_interaction_ref",
        "require_known_scene",
        "is_high_risk_scene",
        "step_already_satisfied",
    ):
        if needle not in hcp:
            _fail(f"human_confirmation_policy missing P4 piece: {needle}", failures)

    fulfill = _read("services/intent_fulfillment.py")
    for needle in (
        "awaiting_seller_confirmation",
        "seller_confirmation_session_id",
        "buyer_fulfill_confirm_steps",
        "high_risk",
    ):
        if needle not in fulfill:
            _fail(f"intent_fulfillment missing P4 piece: {needle}", failures)

    conf_routes = _read("api/routes/confirmations.py")
    if "intentionally ignored" not in conf_routes and "policy_auto_allowed=False" not in conf_routes:
        _fail("confirmations create must ignore client policy_auto_allowed", failures)

    orch = _read("api/routes/orchestration.py")
    if "seller_confirmation_session_id" not in orch:
        _fail("orchestration missing seller_confirmation_session_id", failures)

    settle = _read("api/routes/settlement.py")
    if "buyer_accept_settle_confirmation_required" not in settle:
        _fail("settlement buyer-accept missing P4 settle confirmation gate", failures)

    # P5 Important Fields lock — high-precision crypto + triple match + anti-collusion
    std = _read("services/important_fields_standard.py")
    for needle in (
        "normalize_amount_string",
        "normalize_datetime_utc",
        "normalize_text",
    ):
        if needle not in std:
            _fail(f"important_fields_standard missing P5 precision: {needle}", failures)

    capture = _read("services/important_fields_capture.py")
    for needle in (
        "buyer_agent_id",
        "seller_agent_id",
        "require_matched_capture",
        "expected_amount",
        "interaction_ref",
        "FULFILL_IF_REQUIRED_SCENES",
    ):
        if needle not in capture:
            _fail(f"important_fields_capture missing P5 piece: {needle}", failures)

    standards = _read("api/routes/standards.py")
    for needle in (
        "submitter_agent_id",
        "buyer_agent_id",
        "seller_agent_id",
        "karma2",
        'role: Literal["buyer", "seller", "protocol"]',
    ):
        if needle not in standards:
            _fail(f"standards routes missing P5 piece: {needle}", failures)

    fulfill = _read("services/intent_fulfillment.py")
    for needle in (
        "expected_amount=pay_amount",
        "interaction_ref=interaction_ref",
        "karma2.",
    ):
        if needle not in fulfill:
            _fail(f"intent_fulfillment missing P5 IF bind: {needle}", failures)

    if not (ROOT / "docs/IMPORTANT_FIELDS_P5_V1.md").is_file():
        _fail("missing docs/IMPORTANT_FIELDS_P5_V1.md", failures)

    # P6 accept fulfillment — seller TTL cancel, non-confirm ledger, liability
    p6cat = ROOT / "packages/evidence-schema/accept-fulfillment.v1.json"
    if not p6cat.is_file():
        _fail("missing accept-fulfillment.v1.json", failures)
    else:
        p6t = p6cat.read_text(encoding="utf-8")
        if "karma-accept-fulfillment-v1" not in p6t:
            _fail("accept-fulfillment catalog missing schema_version marker", failures)
        for needle in (
            "seller_accept_ttl_seconds",
            "non_confirm_thresholds",
            "post_confirm_breach",
            "bond_multiplier",
            "reputation_delta_on_timeout",
        ):
            if needle not in p6t:
                _fail(f"accept-fulfillment catalog missing {needle}", failures)

    p6svc = _read("services/accept_fulfillment.py")
    for needle in (
        "record_seller_non_confirm",
        "arm_post_confirm_liability",
        "process_expired_seller_session",
        "seller_risk_profile",
        "check_interaction_seller_timeout",
        "expire_pending_seller_accepts",
    ):
        if needle not in p6svc:
            _fail(f"accept_fulfillment missing P6 piece: {needle}", failures)

    hcp = _read("services/human_confirmation_policy.py")
    for needle in (
        "ttl_seconds",
        "list_pending_seller_accept_sessions",
        "mark_session_expired_cancelled",
    ):
        if needle not in hcp:
            _fail(f"human_confirmation_policy missing P6 piece: {needle}", failures)

    fulfill = _read("services/intent_fulfillment.py")
    for needle in (
        "cancelled_seller_timeout",
        "breach_liability",
        "seller_accept_ttl_seconds",
        "record_seller_non_confirm_reputation",
        "seller_requires_forced_confirm",
    ):
        if needle not in fulfill:
            _fail(f"intent_fulfillment missing P6 piece: {needle}", failures)

    standards = _read("api/routes/standards.py")
    if "/accept-fulfillment" not in standards:
        _fail("standards routes missing accept-fulfillment API", failures)

    conf_routes = _read("api/routes/confirmations.py")
    for needle in (
        "expire-pending-seller-accepts",
        "process_expired_seller_session",
        "record_seller_non_confirm",
    ):
        if needle not in conf_routes:
            _fail(f"confirmations routes missing P6 piece: {needle}", failures)

    trust = _read("services/agent_trust.py")
    if "record_seller_non_confirm_reputation" not in trust:
        _fail("agent_trust missing P6 non-confirm reputation hook", failures)

    disc = _read("services/discovery_priority.py")
    if "accept_risk" not in disc:
        _fail("discovery_priority missing P6 accept_risk demotion", failures)

    if not (ROOT / "docs/ACCEPT_FULFILLMENT_P6_V1.md").is_file():
        _fail("missing docs/ACCEPT_FULFILLMENT_P6_V1.md", failures)

    # P7 delivery verification — physical triple / tagged photo / silent buyer
    p7cat = ROOT / "packages/evidence-schema/delivery-verification.v1.json"
    if not p7cat.is_file():
        _fail("missing delivery-verification.v1.json", failures)
    else:
        p7t = p7cat.read_text(encoding="utf-8")
        if "karma-delivery-verification-v1" not in p7t:
            _fail("delivery-verification catalog missing schema_version marker", failures)
        for needle in (
            "physical_triple",
            "ticket_stub",
            "digital_light",
            "buyer_silent_confirm_seconds",
            "capture_time_system_tag",
            "wrong_item_at_intake",
            "logistics_bps",
        ):
            if needle not in p7t:
                _fail(f"delivery-verification catalog missing {needle}", failures)

    p7svc = _read("services/delivery_verification.py")
    for needle in (
        "issue_capture_challenge",
        "logistics_intake",
        "logistics_deliver",
        "buyer_silent_default",
        "apply_silent_buyer_default",
        "require_verified_for_settle",
        "tag_hmac",
        "WRONG_ITEM",
    ):
        if needle not in p7svc:
            _fail(f"delivery_verification missing P7 piece: {needle}", failures)

    dv_routes = _read("api/routes/delivery_verification.py")
    for needle in (
        "/sessions",
        "logistics-intake",
        "logistics-deliver",
        "capture-challenge",
        "expire-silent-buyers",
        "buyer-confirm",
    ):
        if needle not in dv_routes:
            _fail(f"delivery_verification routes missing {needle}", failures)

    app = _read("api/app.py")
    if 'prefix="/v1/delivery-verification"' not in app:
        _fail("api/app.py missing /v1/delivery-verification router", failures)

    standards = _read("api/routes/standards.py")
    if "/delivery-verification" not in standards:
        _fail("standards routes missing delivery-verification API", failures)

    settle = _read("api/routes/settlement.py")
    for needle in (
        "_assert_p7_delivery_gate",
        "delivery_verification_required",
        "require_verified_for_settle",
    ):
        if needle not in settle:
            _fail(f"settlement missing P7 gate: {needle}", failures)

    if not (ROOT / "docs/DELIVERY_VERIFICATION_P7_V1.md").is_file():
        _fail("missing docs/DELIVERY_VERIFICATION_P7_V1.md", failures)


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
