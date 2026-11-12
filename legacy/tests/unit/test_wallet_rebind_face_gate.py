# -*- coding: utf-8 -*-
"""换绑操作钱包的「本人刷脸」闸门（2026-10-08 审计 G6）。

换钱包 = 换「谁可以代表这张子身份签名」。以前的实现只要求 owner + 新钱包的
personal_sign，**已绑过再绑就是直接覆盖** —— 不刷脸、不触发应急、不留回执。
口径是「修改 / 更换钱包地址要触发应急或锁定，只有本人刷脸通过才能更换」。

这个文件钉住：
  1. 首次绑定不受影响（仍然只需要新钱包签名）；
  2. 换绑不带刷脸材料 → 409，钱包不动；
  3. 换绑带本人刷脸（签名的钱包 = 身份的绑定钱包）→ 200 + 站内回执 + 安全事件。
"""
from __future__ import annotations

import uuid

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from sqlalchemy import select

from config.settings import settings
from db.models.orm import (
    ConsoleNoticeModel,
    IdentityFaceTemplateModel,
    IdentityProfileModel,
    IdentityRoleProfile,
)
from services import face_activation as face
from services import security_monitoring as sm
from services.identity_verification import build_bind_wallet_message

WALLET_KEY = "0x" + "11" * 32
SIGNER = Account.from_key(WALLET_KEY)
W1_KEY = "0x" + "33" * 32
W1 = Account.from_key(W1_KEY)
W2_KEY = "0x" + "44" * 32
W2 = Account.from_key(W2_KEY)

CAPTURE = "a" * 64
TEMPLATE = "b" * 64
FRESH_CAPTURE = "c" * 64
CIPHER = "Q0lQSEVSVEVYVA" * 8
ENC = {
    "algo": "AES-GCM-256",
    "kdf": "PBKDF2-SHA256",
    "iterations": 200_000,
    "salt_b64": "c2FsdHNhbHRzYWx0c2FsdA==",
    "iv_b64": "aXZpdml2aXZpdg==",
    "key_wrap": "wallet-signature-v1",
}


def _h(identity: str) -> dict:
    return {"X-Karma-Identity-Id": identity}


def _sig(message: str, key: str) -> str:
    sig = Account.from_key(key).sign_message(encode_defunct(text=message)).signature.hex()
    return sig if sig.startswith("0x") else "0x" + sig


def _liveness() -> dict:
    return {"angles": 5, "frames": 5, "source": "camera", "challenges": ["center", "left", "right"]}


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    monkeypatch.setattr(settings, "face_activation_enabled", True)
    monkeypatch.setattr(settings, "face_activation_min_angles", 3)
    monkeypatch.setattr(settings, "face_consistency_min_score", 0.35)


def _seed(db_session, owner: str, profile_id: str) -> None:
    """一个已激活身份（绑定钱包 + 脸模板）名下的一张子身份卡。"""
    db_session.add(
        IdentityProfileModel(
            identity_id=owner, display_id="Karma-ID-TEST", bound_wallet_address=SIGNER.address
        )
    )
    db_session.add(
        IdentityFaceTemplateModel(
            identity_id=owner,
            template_cipher=CIPHER,
            template_digest=TEMPLATE,
            algorithm="KFC-GRAY32-NCC-v1",
            capture_digest=CAPTURE,
            wallet_address=SIGNER.address,
            liveness=_liveness(),
        )
    )
    db_session.add(
        IdentityRoleProfile(
            profile_id=profile_id,
            owner_identity_id=owner,
            class_="individual",
            kyc_status="none",
            visibility="public",
            display_name="生活助理",
        )
    )


def _face_payload(owner: str, profile_id: str, score: float = 0.62) -> dict:
    message = face.build_face_consistency_message(
        owner_identity_id=owner,
        profile_id=profile_id,
        class_="individual",
        wallet_address=SIGNER.address,
        reference_digest=TEMPLATE,
        capture_digest=FRESH_CAPTURE,
        score=score,
    )
    return {
        "face_wallet_address": SIGNER.address,
        "face_wallet_signature": _sig(message, WALLET_KEY),
        "face_reference_digest": TEMPLATE,
        "face_capture_digest": FRESH_CAPTURE,
        "face_score": score,
        "face_liveness": _liveness(),
        "face_encryption": dict(ENC),
    }


async def _bind(client, owner, profile_id, wallet, key, **extra):
    body = {
        "wallet_address": wallet.address,
        "wallet_signature": _sig(
            build_bind_wallet_message(
                profile_id=profile_id, owner_identity_id=owner, wallet_address=wallet.address
            ),
            key,
        ),
    }
    body.update(extra)
    return await client.post(
        "/v1/identity/role-profiles/%s/bind-wallet" % profile_id,
        json=body,
        headers=_h(owner),
    )


@pytest.mark.asyncio
async def test_first_bind_still_only_needs_the_new_wallets_signature(client, db_session):
    tag = uuid.uuid4().hex[:8]
    owner = "kid_rebind_first_" + tag
    profile_id = "rp-rebind-first-" + tag
    _seed(db_session, owner, profile_id)
    await db_session.flush()

    ok = await _bind(client, owner, profile_id, W1, W1_KEY)
    assert ok.status_code == 200, ok.text
    assert ok.json()["bound_wallet_address"] == W1.address.lower()


@pytest.mark.asyncio
async def test_rebind_without_a_face_check_is_refused(client, db_session):
    tag = uuid.uuid4().hex[:8]
    owner = "kid_rebind_noface_" + tag
    profile_id = "rp-rebind-noface-" + tag
    _seed(db_session, owner, profile_id)
    await db_session.flush()

    assert (await _bind(client, owner, profile_id, W1, W1_KEY)).status_code == 200

    blocked = await _bind(client, owner, profile_id, W2, W2_KEY)
    assert blocked.status_code == 409, blocked.text

    row = await db_session.get(IdentityRoleProfile, profile_id)
    assert row.bound_wallet_address == W1.address.lower(), "被拒的换绑不能动到已绑钱包"


@pytest.mark.asyncio
async def test_rebind_with_a_same_person_check_succeeds_and_leaves_a_trail(client, db_session):
    tag = uuid.uuid4().hex[:8]
    owner = "kid_rebind_face_" + tag
    profile_id = "rp-rebind-face-" + tag
    _seed(db_session, owner, profile_id)
    await db_session.flush()

    assert (await _bind(client, owner, profile_id, W1, W1_KEY)).status_code == 200

    ok = await _bind(client, owner, profile_id, W2, W2_KEY, **_face_payload(owner, profile_id))
    assert ok.status_code == 200, ok.text
    assert ok.json()["bound_wallet_address"] == W2.address.lower()

    row = await db_session.get(IdentityRoleProfile, profile_id)
    assert row.bound_wallet_address == W2.address.lower()

    # 站内回执：换绑是不可逆动作，主人事后必须看得见。
    notices = (
        await db_session.execute(
            select(ConsoleNoticeModel).where(
                ConsoleNoticeModel.karma_identity_id == owner,
                ConsoleNoticeModel.kind == "wallet_rebound",
            )
        )
    ).scalars().all()
    assert notices, "换绑必须留一条站内回执"
    payload = notices[-1].payload or {}
    assert payload.get("previous_wallet") == W1.address.lower()
    assert payload.get("new_wallet") == W2.address.lower()

    # 安全事件：可追溯、可告警。
    events = [
        e
        for e in sm._list_recent_events(120)
        if e.event_type == sm.SecurityMonitoringEventType.IDENTITY_WALLET_REBIND
        and e.metadata.get("profile_id") == profile_id
    ]
    assert events, "换绑必须落一条安全事件"
    assert events[-1].metadata["new_wallet"] == W2.address.lower()


@pytest.mark.asyncio
async def test_rebind_refuses_a_face_check_signed_by_a_non_root_wallet(client, db_session):
    """刷脸结论必须来自身份的绑定钱包（身份根）—— 换个钱包签一律不成立。"""
    tag = uuid.uuid4().hex[:8]
    owner = "kid_rebind_wrongroot_" + tag
    profile_id = "rp-rebind-wrongroot-" + tag
    _seed(db_session, owner, profile_id)
    await db_session.flush()

    assert (await _bind(client, owner, profile_id, W1, W1_KEY)).status_code == 200

    message = face.build_face_consistency_message(
        owner_identity_id=owner,
        profile_id=profile_id,
        class_="individual",
        wallet_address=W1.address,
        reference_digest=TEMPLATE,
        capture_digest=FRESH_CAPTURE,
        score=0.62,
    )
    blocked = await _bind(
        client,
        owner,
        profile_id,
        W2,
        W2_KEY,
        face_wallet_address=W1.address,
        face_wallet_signature=_sig(message, W1_KEY),
        face_reference_digest=TEMPLATE,
        face_capture_digest=FRESH_CAPTURE,
        face_score=0.62,
        face_liveness=_liveness(),
        face_encryption=dict(ENC),
    )
    assert blocked.status_code == 403, blocked.text
