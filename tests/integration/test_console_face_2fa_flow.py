# -*- coding: utf-8 -*-
"""操作台 L3-3 的 HTTP 端到端（ASGI in-process，真路由、真状态机）：

1. **刷脸即激活**：活体 + 多角度 → 模板密文 + 摘要 → 当场置「已激活」（不进复核队）；
2. **追加身份同人比对**：建卡 → 现采的脸与首次模板比一个分数 → 过线就开通；
   分数不够 / 重放旧采集 / 还没激活，三种都必须拒；
3. **动额度前过 2FA**：绑了验证器之后，加额 / 减额不带码一律 401，带码才动得了；
   恢复码一次性；停用运行时钥匙同样被这道闸拦。

每个用例用一把自己的身份（哈希测试名派生私钥）—— 测试库是会话级共享的，
共用身份会让「先激活 / 后加身份」这类前置条件互相污染。
"""
from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from httpx import AsyncClient

from config.settings import settings
from services import console_2fa as totp
from services.face_activation import (
    build_face_activation_message,
    build_face_consistency_message,
)
from services.runtime_wallet import build_create_key_message, build_revoke_key_message

CAPTURE = "a" * 64
TEMPLATE = "b" * 64
FRESH_CAPTURE = "c" * 64
CIPHER = base64.b64encode(b"karma-face-template-descriptor" * 8).decode()
#: 形状与操作台 cyber-face-vault.js 里 encryptTemplate() 输出一致（服务端按同一套白名单收）。
ENCRYPTION = {
    "algo": "AES-GCM-256",
    "kdf": "PBKDF2-SHA256",
    "iterations": 250000,
    "salt_b64": "AAAAAAAAAAAAAAAAAAAAAA==",
    "iv_b64": "AAAAAAAAAAAAAAAA",
    "key_wrap": "wallet-signature-v1",
}
LIVENESS = {"angles": 5, "frames": 5, "source": "camera", "challenges": ["center", "left", "right"]}


class Who:
    """一把测试身份：私钥 → 地址 → 身份号（身份号 = 小写地址）。"""

    def __init__(self, key: str) -> None:
        self.account = Account.from_key(key)
        self.identity = self.account.address.lower()

    def headers(self) -> dict:
        return {"X-Karma-Identity-Id": self.identity}

    def sign(self, message: str) -> str:
        return self.account.sign_message(encode_defunct(text=message)).signature.hex()


@pytest.fixture
def who(request) -> Who:
    seed = hashlib.sha256(request.node.name.encode("utf-8")).hexdigest()
    return Who("0x" + seed)


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    monkeypatch.setattr(settings, "face_activation_enabled", True)
    monkeypatch.setattr(settings, "face_activation_min_angles", 3)
    monkeypatch.setattr(settings, "face_consistency_min_score", 0.35)
    monkeypatch.setattr(settings, "console_2fa_required_for_funds", False)


async def _activate(client: AsyncClient, me: Who) -> dict:
    body = {
        "wallet_address": me.account.address,
        "wallet_signature": me.sign(
            build_face_activation_message(
                identity_id=me.identity,
                wallet_address=me.account.address,
                capture_digest=CAPTURE,
                template_digest=TEMPLATE,
            )
        ),
        "capture_digest": CAPTURE,
        "template_digest": TEMPLATE,
        "template_cipher": CIPHER,
        "algorithm": "KFC-GRAY32-NCC-v1",
        "encryption": ENCRYPTION,
        "liveness": LIVENESS,
    }
    r = await client.post(
        f"/v1/identity/{me.identity}/verification/face-activate", json=body, headers=me.headers()
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _new_profile(client: AsyncClient, me: Who, name: str = "采购助理") -> str:
    r = await client.post(
        "/v1/identity/role-profiles",
        json={"owner_identity_id": me.identity, "class": "individual", "display_name": name},
        headers=me.headers(),
    )
    assert r.status_code == 201, r.text
    return r.json()["profile_id"]


async def _consistency(
    client: AsyncClient, me: Who, profile_id: str, *, score: float, capture: str = FRESH_CAPTURE
):
    body = {
        "wallet_address": me.account.address,
        "wallet_signature": me.sign(
            build_face_consistency_message(
                owner_identity_id=me.identity,
                profile_id=profile_id,
                class_="individual",
                wallet_address=me.account.address,
                reference_digest=TEMPLATE,
                capture_digest=capture,
                score=score,
            )
        ),
        "reference_digest": TEMPLATE,
        "capture_digest": capture,
        "score": score,
        "liveness": LIVENESS,
        "encryption": ENCRYPTION,
    }
    return await client.post(
        f"/v1/identity/role-profiles/{profile_id}/face-consistency", json=body, headers=me.headers()
    )


async def _bind_two_factor(client: AsyncClient, me: Who) -> str:
    """绑一把验证器，返回密钥（后续自己算 TOTP）。"""
    r = await client.post("/v1/console/2fa/enroll", json={}, headers=me.headers())
    assert r.status_code == 201, r.text
    secret = r.json()["secret"]
    assert r.json()["otpauth_uri"].startswith("otpauth://totp/")
    bad = await client.post(
        "/v1/console/2fa/activate", json={"code": "000000"}, headers=me.headers()
    )
    assert bad.status_code == 400, bad.text
    ok = await client.post(
        "/v1/console/2fa/activate", json={"code": totp.totp(secret)}, headers=me.headers()
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["enabled"] is True
    assert len(ok.json()["recovery_codes"]) >= 5, "绑上要发一次性恢复码"
    return secret


# ------------------------------------------------------------------ 刷脸激活


async def test_face_activation_activates_on_the_spot(client: AsyncClient, who: Who):
    payload = await _activate(client, who)
    assert payload["status"] == "verified" and payload["activated"] is True
    assert payload["reviewer_identity_id"] == "platform:face-liveness:v1", "盖章人写明是刷脸活的，不是人工"
    assert payload["wallet_address"] == who.identity

    # 模板回给本人一份（本机解密后才能跟下次采集比），密文不是照片。
    tpl = await client.get(
        f"/v1/identity/{who.identity}/verification/face-template", headers=who.headers()
    )
    assert tpl.status_code == 200, tpl.text
    assert tpl.json()["enrolled"] is True and tpl.json()["template_digest"] == TEMPLATE


async def test_a_forged_signature_cannot_activate(client: AsyncClient, who: Who):
    """拿到身份号也激活不了：签名必须是这个身份绑定钱包的私钥签的。"""
    stranger = Account.from_key("0x" + "44" * 32)
    body = {
        "wallet_address": who.account.address,
        "wallet_signature": stranger.sign_message(
            encode_defunct(
                text=build_face_activation_message(
                    identity_id=who.identity,
                    wallet_address=who.account.address,
                    capture_digest="d" * 64,
                    template_digest="e" * 64,
                )
            )
        ).signature.hex(),
        "capture_digest": "d" * 64,
        "template_digest": "e" * 64,
        "template_cipher": CIPHER,
        "algorithm": "KFC-GRAY32-NCC-v1",
        "encryption": ENCRYPTION,
        "liveness": LIVENESS,
    }
    r = await client.post(
        f"/v1/identity/{who.identity}/verification/face-activate", json=body, headers=who.headers()
    )
    assert r.status_code == 401, r.text


async def test_face_activation_needs_a_real_camera_liveness(client: AsyncClient, who: Who):
    """照片通道不算「本人在场」：连验签都不用走到就该拒。"""
    body = {
        "wallet_address": who.account.address,
        "wallet_signature": who.sign("nonsense"),
        "capture_digest": "f" * 64,
        "template_digest": "g" * 64,
        "template_cipher": CIPHER,
        "algorithm": "KFC-GRAY32-NCC-v1",
        "encryption": ENCRYPTION,
        "liveness": dict(LIVENESS, source="photo"),
    }
    r = await client.post(
        f"/v1/identity/{who.identity}/verification/face-activate", json=body, headers=who.headers()
    )
    assert r.status_code == 400, r.text


# ------------------------------------------------------------------ 追加身份


async def test_second_identity_opens_when_it_is_the_same_person(client: AsyncClient, who: Who):
    await _activate(client, who)
    profile_id = await _new_profile(client, who)

    r = await _consistency(client, who, profile_id, score=0.91)
    assert r.status_code == 200, r.text
    assert r.json()["kyc_status"] == "verified", "过线当场开通，不进复核队"
    check = r.json()["kyc_payload"]["face_consistency"]
    assert check["mode"] == "device_template"
    assert float(check["score"]) >= float(check["threshold"])


async def test_a_different_face_cannot_open_a_second_identity(client: AsyncClient, who: Who):
    await _activate(client, who)
    profile_id = await _new_profile(client, who)
    low = await _consistency(client, who, profile_id, score=0.05)
    assert low.status_code == 422, low.text
    # 拒了就不该盖上已核验的章。
    r = await client.get(f"/v1/identity/role-profiles/{profile_id}", headers=who.headers())
    assert r.status_code == 200, r.text
    assert r.json()["kyc_status"] != "verified"


async def test_a_replayed_enrollment_capture_is_refused(client: AsyncClient, who: Who):
    await _activate(client, who)
    profile_id = await _new_profile(client, who)
    replay = await _consistency(client, who, profile_id, score=0.99, capture=CAPTURE)
    assert replay.status_code == 409, replay.text
    assert "replay" in replay.json()["detail"].lower()


async def test_adding_an_identity_before_activation_is_explained(client: AsyncClient, who: Who):
    """还没刷脸激活：拿不到模板，要说清「先激活主身份」。"""
    profile_id = await _new_profile(client, who)
    r = await _consistency(client, who, profile_id, score=0.99)
    assert r.status_code == 409, r.text
    assert "face template" in r.json()["detail"]


# ------------------------------------------------------------------ 2FA 闸门


async def test_moving_a_limit_needs_the_code(client: AsyncClient, who: Who):
    await client.post(f"/v1/capacity/{who.identity}/lock", json={"amount": 100.0})
    profile_id = await _new_profile(client, who)
    secret = await _bind_two_factor(client, who)

    # 绑了 2FA：不带码 / 带错码都动不了额度。
    no_code = await client.put(
        f"/v1/capacity/{who.identity}/allocations",
        json={"allocations": {profile_id: 40.0}},
        headers=who.headers(),
    )
    assert no_code.status_code == 401, no_code.text
    wrong = await client.put(
        f"/v1/capacity/{who.identity}/allocations",
        json={"allocations": {profile_id: 40.0}},
        headers={**who.headers(), "X-Karma-2FA-Code": "000000"},
    )
    assert wrong.status_code == 401, wrong.text

    good = await client.put(
        f"/v1/capacity/{who.identity}/allocations",
        json={"allocations": {profile_id: 40.0}},
        headers={**who.headers(), "X-Karma-2FA-Code": totp.totp(secret)},
    )
    assert good.status_code == 200, good.text
    assert good.json()["allocations"][0]["allocated_credits"] == 40.0


async def test_unbound_identity_still_moves_limits(client: AsyncClient, who: Who):
    """没绑 2FA 的身份：默认只有钱包签名那道锁，照旧能授权（旋钮未开时）。"""
    await client.post(f"/v1/capacity/{who.identity}/lock", json={"amount": 50.0})
    profile_id = await _new_profile(client, who)
    r = await client.put(
        f"/v1/capacity/{who.identity}/allocations",
        json={"allocations": {profile_id: 30.0}},
        headers=who.headers(),
    )
    assert r.status_code == 200, r.text


async def test_recovery_code_works_once_then_is_gone(client: AsyncClient, who: Who):
    await client.post(f"/v1/capacity/{who.identity}/lock", json={"amount": 100.0})
    profile_id = await _new_profile(client, who)
    enroll = await client.post("/v1/console/2fa/enroll", json={}, headers=who.headers())
    secret = enroll.json()["secret"]
    activated = await client.post(
        "/v1/console/2fa/activate", json={"code": totp.totp(secret)}, headers=who.headers()
    )
    codes = activated.json()["recovery_codes"]
    before = activated.json()["recovery_left"]

    first = await client.put(
        f"/v1/capacity/{who.identity}/allocations",
        json={"allocations": {profile_id: 20.0}},
        headers={**who.headers(), "X-Karma-2FA-Code": codes[0]},
    )
    assert first.status_code == 200, first.text

    again = await client.put(
        f"/v1/capacity/{who.identity}/allocations",
        json={"allocations": {profile_id: 21.0}},
        headers={**who.headers(), "X-Karma-2FA-Code": codes[0]},
    )
    assert again.status_code == 401, "恢复码用掉即焚，不能再用第二次"

    status = await client.get("/v1/console/2fa", headers=who.headers())
    assert status.json()["recovery_left"] == before - 1


async def test_stopping_a_runtime_key_needs_the_code(client: AsyncClient, who: Who):
    """停用钥匙也是收支配权：绑了 2FA 就必须带码。"""
    secret = await _bind_two_factor(client, who)
    expire = datetime.utcnow() + timedelta(days=7)
    created = await client.post(
        "/runtime/create-key",
        json={
            "wallet_address": who.account.address,
            "karma_identity_id": who.identity,
            "wallet_signature": who.sign(
                build_create_key_message(
                    karma_identity_id=who.identity,
                    wallet_address=who.account.address,
                    permissions=["discover_agents"],
                    single_limit=50.0,
                    daily_limit=200.0,
                    expire_time=expire,
                    agent_name="l33-agent",
                    agent_binding=None,
                )
            ),
            "permissions": ["discover_agents"],
            "single_limit": 50.0,
            "daily_limit": 200.0,
            "expire_time": expire.isoformat(),
            "agent_name": "l33-agent",
        },
    )
    assert created.status_code == 201, created.text
    key_id = str(created.json()["key_id"])

    def _revoke_body(code=None):
        body = {
            "key_id": key_id,
            "wallet_address": who.account.address,
            "karma_identity_id": who.identity,
            "wallet_signature": who.sign(
                build_revoke_key_message(
                    key_id=key_id, karma_identity_id=who.identity, wallet_address=who.account.address
                )
            ),
        }
        if code is not None:
            body["twofa_code"] = code
        return body

    blocked = await client.post("/runtime/revoke-key", json=_revoke_body())
    assert blocked.status_code == 401, blocked.text

    done = await client.post("/runtime/revoke-key", json=_revoke_body(totp.totp(secret)))
    assert done.status_code == 200, done.text
    assert "revoked" in done.text
