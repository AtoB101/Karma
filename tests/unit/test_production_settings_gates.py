"""Production APP_ENV validator — gates must not be disabled."""

from __future__ import annotations

import pytest

from config.settings import Settings


def _prod_kwargs(**overrides):
    base = dict(
        app_env="production",
        app_secret_key="x" * 40,
        auth_enforce_protected_routes=True,
        auth_api_keys="agent-1:secret-1",
        auth_allow_dev_key_fallback=False,
        rate_limit_redis_fail_closed=True,
        runtime_require_saved_automation_policy=True,
        runtime_require_task_automation_readiness=True,
        runtime_require_handoff_attestation=True,
        runtime_require_wallet_identity_binding=True,
        runtime_daily_spend_persist=True,
        receipt_require_signature=True,
        ledger_require_party_actor=True,
        settlement_require_party_actor=True,
        trade_launch_require_eip712=True,
        karma_signing_backend="client_only",
    )
    base.update(overrides)
    return base


def test_production_accepts_full_gates():
    Settings(**_prod_kwargs())


@pytest.mark.parametrize(
    "field,value",
    [
        ("receipt_require_signature", False),
        ("ledger_require_party_actor", False),
        ("settlement_require_party_actor", False),
        ("runtime_require_handoff_attestation", False),
        ("auth_enforce_protected_routes", False),
        ("trade_launch_require_eip712", False),
        ("karma_signing_backend", "local"),
    ],
)
def test_production_rejects_disabled_gate(field, value):
    kw = _prod_kwargs(**{field: value})
    with pytest.raises(ValueError, match="production"):
        Settings(**kw)
