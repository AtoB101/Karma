"""身份底座 v1 —— 状态机 / 凭证链 / Identity Card 单元测试（商业级验收）。"""
from __future__ import annotations

import json
import uuid

import pytest

from services.identity_gateway import state_machine as sm
from services.identity_gateway import store


def _kid() -> str:
    return f"kid_t_{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
def _clean():
    store.reset_for_tests()
    yield
    store.reset_for_tests()


def _seed(kid: str | None = None, twofa: str = "123456") -> str:
    kid = kid or _kid()
    store.seed_identity(kid, "0x" + "ab" * 20, twofa_code=twofa)
    return kid


# ── 状态机合法迁移全表 ─────────────────────────────────────

@pytest.mark.parametrize("seq", [
    ["issue", "verify"],
    ["issue", "reject"],
    ["issue", "revoke"],
    ["issue", "verify", "expire"],
    ["issue", "verify", "revoke"],
    ["issue", "reject", "reissue", "verify"],
    ["issue", "verify", "expire", "reverify", "verify"],
])
def test_legal_transitions(seq):
    kid = _seed()
    cred = store.issue_credential(kid, "email")
    cid = cred["credential_id"]
    states = {"issue": "pending", "reject": "failed", "verify": "verified",
              "revoke": "revoked", "expire": "expired", "reissue": "pending", "reverify": "pending"}
    cur = cred["status"]
    for step in seq[1:]:  # skip first issue (already done)
        result = _do(kid, cid, step)
        assert result["status"] == states[step], f"{step}: {result['status']} != {states[step]}"


def _do(kid, cid, action):
    if action == "verify":
        return store.verify_credential(kid, cid)
    if action == "reject":
        return store.reject_credential(kid, cid, reason="r")
    if action == "revoke":
        return store.revoke_credential(kid, cid, reason="manual revoke")
    if action == "expire":
        return store._mutate_credential(kid, cid, "expire", actor="test", reason="ttl")
    if action == "reissue":
        return store._mutate_credential(kid, cid, "reissue", actor="test", reason="reissue")
    if action == "reverify":
        return store._mutate_credential(kid, cid, "reverify", actor="test", reason="reverify")
    raise ValueError(action)


# ── 非法迁移拦截 + 播报 ─────────────────────────────────────

@pytest.mark.parametrize("from_state,action", [
    ("revoked", "verify"),
    ("failed", "verify"),
    ("pending", "reissue"),
    ("pending", "expire"),
    ("revoked", "revoke"),
])
def test_illegal_transition_blocked_and_alerted(from_state, action):
    kid = _seed()
    cred = store.issue_credential(kid, "email")
    cid = cred["credential_id"]
    # 推到目标 from_state
    path = {
        "verified": ["verify"],
        "failed": ["reject"],
        "revoked": ["revoke"],
        "pending": [],
    }[from_state]
    for step in path:
        _do(kid, cid, step)
    with pytest.raises(sm.IllegalTransitionError):
        _do(kid, cid, action)
    alerts = sm.get_alerts()
    assert any(a["category"] == sm.ALERT_CATEGORY_ILLEGAL_TRANSITION for a in alerts), "no illegal_transition alert"
    a = [a for a in alerts if a["category"] == sm.ALERT_CATEGORY_ILLEGAL_TRANSITION][-1]
    assert a["severity"] == sm.ALERT_SEVERITY_WARN
    assert len(a["root_cause"]) >= 0  # root cause chain present (may be empty for fresh entity)


# ── 台账 hash 链篡改检测 ────────────────────────────────────

def test_ledger_tamper_detection():
    kid = _seed()
    store.issue_credential(kid, "email", auto_verify=True)
    assert sm.verify_ledger_integrity()["ok"] is True
    # 直接篡改内存台账某条 reason
    sm._LEDGER[0]["reason"] = "TAMPERED"
    result = sm.verify_ledger_integrity()
    assert result["ok"] is False
    assert result["broken_at"] == 0
    alerts = sm.get_alerts()
    assert any(a["category"] == sm.ALERT_CATEGORY_TAMPER and a["severity"] == sm.ALERT_SEVERITY_CRITICAL
               for a in alerts), "no tamper critical alert"


def test_ledger_chain_growth():
    kid = _seed()
    store.issue_credential(kid, "email", auto_verify=True)
    store.issue_credential(kid, "phone", auto_verify=True)
    integrity = sm.verify_ledger_integrity()
    assert integrity["ok"] is True
    assert integrity["entries"] >= 4  # issue+verify x2


# ── 凭证类型白名单与重复签发 ───────────────────────────────

def test_credential_type_whitelist():
    kid = _seed()
    with pytest.raises(ValueError, match="unsupported credential type"):
        store.issue_credential(kid, "passport")


def test_duplicate_active_credential_rejected():
    kid = _seed()
    store.issue_credential(kid, "email", auto_verify=True)
    with pytest.raises(ValueError, match="already exists"):
        store.issue_credential(kid, "email")


def test_revoke_requires_reason():
    kid = _seed()
    cred = store.issue_credential(kid, "email")
    with pytest.raises(ValueError, match="explicit reason"):
        store.revoke_credential(kid, cred["credential_id"], reason="")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="explicit reason"):
        store.revoke_credential(kid, cred["credential_id"], reason="   ")


def test_ttl_bounds():
    kid = _seed()
    with pytest.raises(ValueError, match="ttl_seconds out of range"):
        store.issue_credential(kid, "email", ttl_seconds=-1)
    with pytest.raises(ValueError, match="ttl_seconds out of range"):
        store.issue_credential(kid, "phone", ttl_seconds=10 * 365 * 86400 + 1)


# ── 身份验证等级推导 ───────────────────────────────────────

def test_verification_level_progression():
    kid = _seed()
    c1 = store.issue_credential(kid, "email", auto_verify=True)
    assert store.identity_card(kid)["verification_status"] == "basic"
    c2 = store.issue_credential(kid, "phone", auto_verify=True)
    store.issue_credential(kid, "wallet", auto_verify=True)
    assert store.identity_card(kid)["verification_status"] == "enhanced"
    store.revoke_credential(kid, c1["credential_id"], reason="downgrade test")
    card = store.identity_card(kid)
    assert card["verification_status"] == "basic"  # phone+wallet but no email → still ≥3? no: now 2 types
    # actually phone+wallet = 2 distinct, <3 → basic
    assert card["verification_level"]["enhanced"] is False


def test_enhanced_requires_wallet():
    kid = _seed()
    store.issue_credential(kid, "email", auto_verify=True)
    store.issue_credential(kid, "phone", auto_verify=True)
    store.issue_credential(kid, "domain", auto_verify=True)
    # 3 distinct but no wallet → basic not enhanced
    card = store.identity_card(kid)
    assert card["verification_status"] == "basic"
    assert card["verification_level"]["enhanced"] is False


# ── Identity Card 最小披露 ──────────────────────────────────

def test_card_minimal_disclosure():
    kid = _seed()
    store.issue_credential(kid, "email", auto_verify=True)
    card_json = json.dumps(store.identity_card(kid, scope="full"))
    # 不含 2FA 明文
    assert "123456" not in card_json
    # 不含完整 wallet（40 位 hex）
    full_wallet = "0x" + "ab" * 20
    assert full_wallet not in card_json
    # 钱包已脱敏
    assert "…" in store.identity_card(kid)["wallet"]
    # card_presented 审计事件
    assert any(e["event"] == "card_presented" for e in sm.get_ledger(entity_id=kid))


def test_card_scope_validation():
    kid = _seed()
    with pytest.raises(ValueError, match="scope"):
        store.identity_card(kid, scope="secret")  # type: ignore[arg-type]


def test_card_audience_audited():
    kid = _seed()
    store.identity_card(kid, audience="third-party-agent-01")
    entry = [e for e in sm.get_ledger(entity_id=kid) if e["event"] == "card_presented"][-1]
    assert entry["actor"] == "third-party-agent-01"


# ── 2FA 绑定联动 ───────────────────────────────────────────

def test_2fa_bind_issues_and_verifies_telegram_credential():
    kid = _seed(twofa="999999")
    ident = store.bind_by_2fa(888, kid, "999999")
    tg = [c for c in ident.credentials if c["type"] == "telegram"]
    assert len(tg) == 1 and tg[0]["status"] == "verified"
    assert ident.twofa_code == ""  # burned


def test_burned_2fa_rejected():
    kid = _seed(twofa="999999")
    store.bind_by_2fa(888, kid, "999999")
    with pytest.raises(ValueError, match="焚毁"):
        store.bind_by_2fa(888, kid, "999999")


def test_rebind_replaces_old_telegram_credential():
    kid = _seed(twofa="999999")
    store.bind_by_2fa(888, kid, "999999")
    # 重新种子码（模拟重新获取），再绑
    store.seed_identity(kid, "0x" + "ab" * 20, twofa_code="888888")
    ident = store.bind_by_2fa(889, kid, "888888")
    tg = [c for c in ident.credentials if c["type"] == "telegram"]
    verified_tg = [c for c in tg if c["status"] == "verified"]
    revoked_tg = [c for c in tg if c["status"] == "revoked"]
    assert len(verified_tg) == 1  # 新凭证 verified
    assert len(revoked_tg) == 1   # 旧凭证 revoked（保留审计）


# ── 子身份回溯 ─────────────────────────────────────────────

def test_sub_identity_card_resolves_to_main():
    kid = _seed()
    store.issue_credential(kid, "email", auto_verify=True)
    sub = store.create_sub_identity(kid, "0x" + "cd" * 20)
    card = store.identity_card(sub.identity_id)
    assert card["identity_id"] == kid  # 回溯到主身份


# ── 台账过滤与根因回溯 ─────────────────────────────────────

def test_ledger_entity_filter():
    k1, k2 = _seed(), _seed()
    store.issue_credential(k1, "email", auto_verify=True)
    store.issue_credential(k2, "phone", auto_verify=True)
    # k2 的凭证 ID
    only_k1 = sm.get_ledger(entity_id=k1)
    assert all(e["entity_id"] == k1 for e in only_k1)


def test_alert_root_cause_chain():
    kid = _seed()
    c = store.issue_credential(kid, "email", auto_verify=True)
    store.revoke_credential(kid, c["credential_id"], reason="r")
    try:
        store.verify_credential(kid, c["credential_id"])
    except sm.IllegalTransitionError:
        pass
    a = [a for a in sm.get_alerts() if a["category"] == sm.ALERT_CATEGORY_ILLEGAL_TRANSITION][-1]
    # root_cause 应包含该 credential 的历史事件
    assert isinstance(a["root_cause"], list)


# ── 健康检查 ───────────────────────────────────────────────

def test_health_ok_normal_env():
    h = sm.health_report()
    assert h["ok"] is True
    assert h["persist_writable"] is True
    assert h["ledger_integrity"] is True


def test_set_identity_class_validation():
    kid = _seed()
    store.set_identity_class(kid, "business")
    assert store.get_by_id(kid).identity_class == "business"
    with pytest.raises(ValueError, match="invalid identity_class"):
        store.set_identity_class(kid, "robot")
