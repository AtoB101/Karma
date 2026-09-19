"""第 10 条：仲裁池对真人开放（2026-09-20）。

旧行为：线上 ARBITRATOR_ACTOR_IDS=admin 且 ARBITRATION_POOL_OPEN_JOIN=false，
于是 require_pool_join_allowed 只放白名单里的 actor —— 任何真实身份都进不了池，
池永远是空的，仲裁庭凑不出人，争议立案之后就走不下去了。

这一条的正确开关就是 ARBITRATION_POOL_OPEN_JOIN（代码里的报错文案也是这么写的）。
这个用例把开关的两个状态钉住，免得以后有人把「封闭池」当成默认。
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from config.settings import settings
from services import actor_guards
from services import arbitration_rules as arb_rules


@pytest.fixture(autouse=True)
def _pin_pool_settings(monkeypatch):
    monkeypatch.setattr(settings, "arbitrator_actor_ids", "admin")
    monkeypatch.setattr(actor_guards, "caller_actor_id", lambda request: "kid_real_user")
    yield


def test_closed_pool_rejects_a_real_identity(monkeypatch):
    monkeypatch.setattr(settings, "arbitration_pool_open_join", False)
    with pytest.raises(HTTPException) as exc:
        arb_rules.require_pool_join_allowed(None)
    assert exc.value.status_code == 403
    assert "ARBITRATION_POOL_OPEN_JOIN=true" in str(exc.value.detail)


def test_closed_pool_still_allows_the_whitelisted_actor(monkeypatch):
    monkeypatch.setattr(settings, "arbitration_pool_open_join", False)
    monkeypatch.setattr(actor_guards, "caller_actor_id", lambda request: "admin")
    arb_rules.require_pool_join_allowed(None)


def test_open_pool_lets_a_real_identity_in(monkeypatch):
    monkeypatch.setattr(settings, "arbitration_pool_open_join", True)
    arb_rules.require_pool_join_allowed(None)
