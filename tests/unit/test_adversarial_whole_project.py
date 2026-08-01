"""Whole-project adversarial tests — platform surfaces beyond P1–P8 commerce plates.

Attack IDs WP-* cover auth, admin, receipts, settlement, capacity, runtime, x402,
AP2, OpenClaw, path/injection, CORS, and router mount integrity.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from api.app import app
from api.middleware.auth import (
    create_access_token,
    decode_access_token,
    validate_api_key_for_agent,
)
from config.settings import settings
from core.schemas import CapacityState, ExecutionReceipt, ToolStatus
from db.session import get_db
from sdk.x402.client import assert_budget, assert_resource_matches_url
from sdk.x402.url_safety import UnsafeX402UrlError, validate_x402_target_url
from services.capacity_ledger import assert_can_release_locked_funds
from services.path_param_safety import validate_public_url_segment
from services.settlement_cycle_guard import worker_reaches_buyer_on_edges
from services.signing import signing_service
from services.text_safety import validate_json_strings_safe, validate_safe_storage_text


ROOT = Path(__file__).resolve().parents[2]


# ─── Auth / JWT / API keys ─────────────────────────────────────────────────


def test_wp_auth_wrong_api_key_rejected(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "auth_api_keys", "agent-a:correct-secret-xyz")
    monkeypatch.setattr(settings, "auth_enforce_protected_routes", True)
    monkeypatch.setattr(settings, "auth_allow_dev_key_fallback", False)
    assert not validate_api_key_for_agent("agent-a", "karma_agent-a_wrong-secret-xyz")
    assert validate_api_key_for_agent("agent-a", "karma_agent-a_correct-secret-xyz")


def test_wp_auth_dev_fallback_blocked_in_production(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "auth_api_keys", "")
    monkeypatch.setattr(settings, "auth_enforce_protected_routes", True)
    monkeypatch.setattr(settings, "auth_allow_dev_key_fallback", True)
    # Even with fallback flag, production+enforce must not accept arbitrary keys
    assert not validate_api_key_for_agent(
        "random-agent", "karma_random-agent_long-enough-secret"
    )


def test_wp_auth_jwt_tampered_rejected():
    token = create_access_token("agent-jwt")
    good = decode_access_token(token)
    assert good.get("sub") == "agent-jwt"
    parts = token.split(".")
    assert len(parts) == 3
    bad = parts[0] + "." + ("A" * len(parts[1])) + "." + parts[2]
    with pytest.raises(HTTPException) as exc:
        decode_access_token(bad)
    assert exc.value.status_code == 401


def test_wp_auth_malformed_api_key_format():
    assert not validate_api_key_for_agent("a", "not-a-karma-key")
    assert not validate_api_key_for_agent("a", "karma_onlyonepart")


# ─── Admin / security always-auth ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_wp_admin_unauth_blocked(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post(
                "/v1/admin/controls/safety-mode",
                json={"enabled": True, "reason": "adversarial"},
            )
            assert r.status_code == 401
            r2 = await client.get("/v1/admin/controls")
            assert r2.status_code == 401
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_wp_security_unauth_blocked(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post(
                "/v1/security/policies",
                json={"config": {"failed_auth_threshold": 1}, "note": "x", "rollout_percent": 100},
            )
            assert r.status_code == 401
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_wp_admin_non_whitelist_forbidden(db_session, monkeypatch):
    monkeypatch.setattr(settings, "admin_actor_ids", "true-admin")
    monkeypatch.setattr(settings, "auth_api_keys", "intruder:super-secret-value-123")
    monkeypatch.setattr(settings, "app_env", "test")
    monkeypatch.setattr(settings, "auth_enforce_protected_routes", False)
    monkeypatch.setattr(settings, "auth_allow_dev_key_fallback", True)

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post(
                "/v1/admin/controls/safety-mode",
                headers={"X-Karma-Api-Key": "karma_intruder_super-secret-value-123"},
                json={"enabled": True, "reason": "hijack"},
            )
            assert r.status_code == 403
    finally:
        app.dependency_overrides.clear()


# ─── Receipts / settlement cycle ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_wp_receipt_missing_contract_404(client):
    now = datetime.utcnow()
    r = ExecutionReceipt(
        task_id="wp-no-contract",
        agent_id="worker-wp",
        step_index=1,
        tool_name="t",
        input_hash="a" * 64,
        output_hash="b" * 64,
        started_at=now,
        ended_at=now + timedelta(milliseconds=50),
        duration_ms=50,
        status=ToolStatus.SUCCESS,
    )
    r.signature = signing_service.sign_receipt(r)
    resp = await client.post("/v1/receipts", json=r.model_dump(mode="json"))
    assert resp.status_code == 404


def test_wp_settlement_cycle_detection():
    # Edges are (buyer/client, worker). A→B and B→C active.
    # Locking buyer=C worker=A closes cycle iff worker A can reach buyer C.
    edges = [("A", "B"), ("B", "C")]
    assert worker_reaches_buyer_on_edges(edges, "A", "C") is True
    assert worker_reaches_buyer_on_edges(edges, "B", "C") is True
    assert worker_reaches_buyer_on_edges(edges, "C", "A") is False


# ─── Capacity ──────────────────────────────────────────────────────────────


def test_wp_capacity_release_blocked_with_responsibility():
    state = CapacityState(
        identity_id="id-1",
        total_locked_usdc=100.0,
        available_credits=50.0,
        reserved_credits=20.0,
        in_progress_credits=10.0,
        confirmed_progress_credits=0.0,
        disputed_credits=0.0,
        pending_settlement_credits=0.0,
        total_bill_credits=80.0,
    )
    with pytest.raises(ValueError, match="cannot release|responsibility"):
        assert_can_release_locked_funds(state, 10.0)


def test_wp_capacity_release_insufficient():
    state = CapacityState(
        identity_id="id-2",
        total_locked_usdc=10.0,
        available_credits=5.0,
        reserved_credits=0.0,
        in_progress_credits=0.0,
        confirmed_progress_credits=0.0,
        disputed_credits=0.0,
        pending_settlement_credits=0.0,
        total_bill_credits=5.0,
    )
    with pytest.raises(ValueError, match="insufficient"):
        assert_can_release_locked_funds(state, 9.0)


# ─── x402 SSRF / budget ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://127.0.0.1/secret",
        "http://10.0.0.8/x",
        "https://evil.com/a/../admin",
        "https://user:pass@evil.com/x",
    ],
)
def test_wp_x402_unsafe_urls_blocked(url):
    with pytest.raises(UnsafeX402UrlError):
        validate_x402_target_url(url, allow_private_hosts=False)


def test_wp_x402_budget_and_resource_guards():
    with pytest.raises(ValueError):
        assert_budget(50.0, 10.0)
    with pytest.raises(ValueError):
        assert_resource_matches_url("https://a.com/1", "https://b.com/1")


# ─── Path / injection ──────────────────────────────────────────────────────


def test_wp_path_traversal_rejected():
    with pytest.raises(HTTPException) as exc:
        validate_public_url_segment("task_id", "../etc/passwd")
    assert exc.value.status_code == 400
    with pytest.raises(HTTPException):
        validate_public_url_segment("task_id", "a/b")
    with pytest.raises(HTTPException):
        validate_public_url_segment("task_id", "x" * 400)


def test_wp_text_nul_and_rlo_rejected():
    with pytest.raises(ValueError, match="null"):
        validate_safe_storage_text("evil\x00name", field="name")
    with pytest.raises(ValueError, match="bidirectional|Unicode"):
        validate_safe_storage_text("spoof\u202Eexe", field="name")
    with pytest.raises(ValueError):
        validate_json_strings_safe({"note": "bad\x00"}, field="body")


# ─── OpenClaw / AP2 static presence ────────────────────────────────────────


def test_wp_openclaw_webhook_signs_body():
    text = (ROOT / "services/openclaw_webhook.py").read_text(encoding="utf-8")
    assert "_sign_body" in text
    assert "OPENCLAW_WEBHOOK" in text or "webhook_secret" in text or "hmac" in text.lower()


def test_wp_ap2_adapter_roundtrip_surface():
    from trusted_agent_runtime.ap2_adapter import (
        evidence_digest,
        from_ap2_mandate,
        to_ap2_mandate,
    )

    assert callable(to_ap2_mandate)
    assert callable(from_ap2_mandate)
    assert callable(evidence_digest)


# ─── CORS / router mounts / production secrets ─────────────────────────────


def test_wp_cors_production_never_wildcard(monkeypatch):
    # Dev may use *; production/staging must ignore wildcard misconfig.
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "cors_allow_origins", "")
    assert settings.cors_allow_origins_list() == []
    monkeypatch.setattr(settings, "cors_allow_origins", "*")
    assert settings.cors_allow_origins_list() == []
    monkeypatch.setattr(settings, "cors_allow_origins", "https://app.example.com,*")
    assert settings.cors_allow_origins_list() == []
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "cors_allow_origins", "")
    assert "*" in settings.cors_allow_origins_list()


def test_wp_app_critical_routers_mounted():
    text = (ROOT / "api/app.py").read_text(encoding="utf-8")
    for prefix in (
        'prefix="/v1/security"',
        'prefix="/v1/admin"',
        'prefix="/v1/settlement"',
        'prefix="/v1/receipts"',
        'prefix="/v1/x402"',
        'prefix="/v1/payment-intents"',
        'prefix="/v1/openclaw"',
        'prefix="/v1/trade"',
        'prefix="/runtime"',
        'prefix="/v1/capacity"',
        "_security_always_auth",
    ):
        assert prefix in text, f"missing mount/guard: {prefix}"


def test_wp_production_secret_validator_rejects_default():
    text = (ROOT / "config/settings.py").read_text(encoding="utf-8")
    assert "change-me-in-production" in text
    assert "_reject_default_secrets_in_production" in text
    assert "APP_SECRET_KEY must be set to a strong value" in text


def test_wp_standards_session_key_requires_auth_dependency():
    text = (ROOT / "api/routes/standards.py").read_text(encoding="utf-8")
    assert "get_current_agent_id" in text
    assert "get_capture_session_key" in text


def test_wp_settlement_payout_guard_wired():
    settle = (ROOT / "api/routes/settlement.py").read_text(encoding="utf-8")
    assert "ensure_success_execution_receipt_before_seller_payout" in settle
    assert "assert_lock_does_not_close_payment_cycle" in settle


def test_wp_x402_url_safety_wired_in_client():
    client = (ROOT / "sdk/x402/client.py").read_text(encoding="utf-8")
    assert "validate_x402_target_url" in client
    routes = (ROOT / "api/routes/x402.py").read_text(encoding="utf-8")
    assert "pay_and_fetch" in routes or "x402" in routes.lower()


def test_wp_runtime_replay_nonce_exists():
    text = (ROOT / "services/runtime_key_service.py").read_text(encoding="utf-8")
    assert "check_replay_nonce" in text
    assert "check_single_and_daily_limits" in text
