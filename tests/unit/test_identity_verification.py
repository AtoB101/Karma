"""
Karma — 主身份认证（证件 + 扫脸）+ 子身份钱包绑定。

红线：服务端只收密文与摘要，任何证件 / 人脸明文都不许进库。

每个用例用自己的一套 identity id：路由会 commit，共用 id 会互相污染。
"""
from __future__ import annotations

import uuid

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from db.models.orm import IdentityRoleProfile, IdentityVerificationModel

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
CIPHER = "Q0lQSEVSVEVYVA" * 8  # >64 字符，且不带 data: 前缀
ENC = {
    "algo": "AES-GCM-256",
    "kdf": "PBKDF2-SHA256",
    "iterations": 250000,
    "salt_b64": "c2FsdHNhbHRzYWx0c2FsdA==",
    "iv_b64": "aXZpdml2aXZpdg==",
    "key_wrap": "wallet-signature-v1",
}
EXTRACTED = {
    "full_name": "张三",
    "doc_type": "ID_CARD",
    "doc_number_mask": "3301**********1234",
    "valid_until": "2030-01-01",
    "consent": True,
}


def _ids() -> tuple[str, str, str]:
    tag = uuid.uuid4().hex[:10]
    return f"kid_owner_{tag}", f"kid_other_{tag}", f"kid_verifier_{tag}"


def _body(**over):
    payload = {
        "level": "basic",
        "doc_digest": DIGEST_A,
        "face_digest": DIGEST_B,
        "package_digest": DIGEST_C,
        "package_cipher": CIPHER,
        "encryption": dict(ENC),
        "extracted": dict(EXTRACTED),
    }
    payload.update(over)
    return payload


def _h(identity: str) -> dict:
    return {"X-Karma-Identity-Id": identity}


def _add_verifier_profile(db_session, owner: str, profile_id: str) -> None:
    db_session.add(
        IdentityRoleProfile(
            profile_id=profile_id,
            owner_identity_id=owner,
            class_="verifier",
            kyc_status="verified",
            visibility="public",
            display_name="核验方",
        )
    )


@pytest.mark.asyncio
async def test_submit_rejects_document_plaintext(client, db_session):
    """夹带证件原图 / 明文字段必须被指名拒绝，不能被静默忽略。"""
    owner, _, _ = _ids()
    r = await client.post(
        f"/v1/identity/{owner}/verification/submit",
        json=_body(image="data:image/jpeg;base64,AAAA"),
        headers=_h(owner),
    )
    assert r.status_code == 400, r.text
    assert "plaintext" in r.json()["detail"]


@pytest.mark.asyncio
async def test_submit_rejects_inline_data_url_anywhere(client, db_session):
    owner, _, _ = _ids()
    r = await client.post(
        f"/v1/identity/{owner}/verification/submit",
        json=_body(preview="data:image/png;base64,AAAA"),
        headers=_h(owner),
    )
    assert r.status_code == 400, r.text


@pytest.mark.asyncio
async def test_submit_rejects_unencrypted_payload_fields(client, db_session):
    """摘要不是 sha256 / 没给加密参数 / 没勾同意，都不许进 pending。"""
    owner, _, _ = _ids()

    bad_digest = await client.post(
        f"/v1/identity/{owner}/verification/submit",
        json=_body(doc_digest="not-a-digest"),
        headers=_h(owner),
    )
    assert bad_digest.status_code == 400, bad_digest.text

    no_enc = await client.post(
        f"/v1/identity/{owner}/verification/submit",
        json=_body(encryption={"algo": "plaintext"}),
        headers=_h(owner),
    )
    assert no_enc.status_code == 400, no_enc.text

    no_consent = await client.post(
        f"/v1/identity/{owner}/verification/submit",
        json=_body(extracted={"full_name": "张三"}),
        headers=_h(owner),
    )
    assert no_consent.status_code == 400, no_consent.text
    assert "consent" in no_consent.json()["detail"]


@pytest.mark.asyncio
async def test_only_the_owner_can_submit(client, db_session):
    owner, other, _ = _ids()
    r = await client.post(
        f"/v1/identity/{owner}/verification/submit", json=_body(), headers=_h(other)
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_happy_path_keeps_ciphertext_off_the_wire_and_hides_it_from_strangers(
    client, db_session
):
    owner, other, _ = _ids()
    r = await client.post(
        f"/v1/identity/{owner}/verification/submit", json=_body(), headers=_h(owner)
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "pending"
    assert body["doc_digest"] == DIGEST_A
    assert body["has_package"] is True
    assert body["package_bytes"] == len(CIPHER)
    assert "package_cipher" not in body, "密文包不该原样回传"
    assert body["extracted"]["full_name"] == "张三"
    assert body["extracted"]["consent"] is True

    stored = await db_session.get(IdentityVerificationModel, owner)
    assert stored is not None and stored.package_cipher == CIPHER

    stranger = await client.get(f"/v1/identity/{owner}/verification", headers=_h(other))
    assert stranger.status_code == 200
    lean = stranger.json()
    assert lean["status"] == "pending"
    assert "extracted" not in lean
    assert "encryption" not in lean
    assert "package_bytes" not in lean

    mine = await client.get(f"/v1/identity/{owner}/verification", headers=_h(owner))
    assert mine.status_code == 200
    assert mine.json()["extracted"]["doc_number_mask"] == "3301**********1234"


@pytest.mark.asyncio
async def test_only_a_verifier_class_profile_can_verify(client, db_session):
    owner, other, verifier = _ids()
    await client.post(
        f"/v1/identity/{owner}/verification/submit", json=_body(), headers=_h(owner)
    )

    self_verify = await client.post(
        f"/v1/identity/{owner}/verification/verify",
        json={"decision": "verified"},
        headers=_h(owner),
    )
    assert self_verify.status_code == 403

    plain_actor = await client.post(
        f"/v1/identity/{owner}/verification/verify",
        json={"decision": "verified"},
        headers=_h(other),
    )
    assert plain_actor.status_code == 403

    _add_verifier_profile(db_session, verifier, f"verifier-profile-{uuid.uuid4().hex[:8]}")
    await db_session.flush()

    ok = await client.post(
        f"/v1/identity/{owner}/verification/verify",
        json={"decision": "verified", "reason": "证件清晰，人证一致"},
        headers=_h(verifier),
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "verified"
    assert ok.json()["reviewer_identity_id"] == verifier

    # 认证通过后不许再提交，避免把已验证状态刷掉。
    resubmit = await client.post(
        f"/v1/identity/{owner}/verification/submit", json=_body(), headers=_h(owner)
    )
    assert resubmit.status_code == 409


@pytest.mark.asyncio
async def test_rejected_can_resubmit(client, db_session):
    owner, _, verifier = _ids()
    await client.post(
        f"/v1/identity/{owner}/verification/submit", json=_body(), headers=_h(owner)
    )
    _add_verifier_profile(db_session, verifier, f"verifier-profile-{uuid.uuid4().hex[:8]}")
    await db_session.flush()

    rejected = await client.post(
        f"/v1/identity/{owner}/verification/verify",
        json={"decision": "rejected", "reason": "照片反光"},
        headers=_h(verifier),
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"

    again = await client.post(
        f"/v1/identity/{owner}/verification/submit", json=_body(), headers=_h(owner)
    )
    assert again.status_code == 200, again.text
    assert again.json()["status"] == "pending"


@pytest.mark.asyncio
async def test_sub_identity_wallet_binding_needs_the_wallets_signature(client, db_session):
    from services.identity_verification import build_bind_wallet_message

    owner, other, _ = _ids()
    profile_id = f"rp-bind-{uuid.uuid4().hex[:8]}"
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
    await db_session.flush()

    acct = Account.create()
    message = build_bind_wallet_message(
        profile_id=profile_id, owner_identity_id=owner, wallet_address=acct.address
    )
    sig = Account.sign_message(encode_defunct(text=message), acct.key).signature.hex()
    if not sig.startswith("0x"):
        sig = "0x" + sig

    ok = await client.post(
        f"/v1/identity/role-profiles/{profile_id}/bind-wallet",
        json={"wallet_address": acct.address, "wallet_signature": sig},
        headers=_h(owner),
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["bound_wallet_address"] == acct.address.lower()

    # 换一个钱包的签名必须失败（不能替别人绑钱包）。
    other_acct = Account.create()
    bad = await client.post(
        f"/v1/identity/role-profiles/{profile_id}/bind-wallet",
        json={"wallet_address": other_acct.address, "wallet_signature": sig},
        headers=_h(owner),
    )
    assert bad.status_code in (403, 400), bad.text

    stranger = await client.post(
        f"/v1/identity/role-profiles/{profile_id}/bind-wallet",
        json={"wallet_address": acct.address, "wallet_signature": sig},
        headers=_h(other),
    )
    assert stranger.status_code == 403


@pytest.mark.asyncio
async def test_sub_identity_spend_policy_is_stored_for_the_sdk_wizard(client, db_session):
    owner, _, _ = _ids()
    profile_id = f"rp-policy-{uuid.uuid4().hex[:8]}"
    db_session.add(
        IdentityRoleProfile(
            profile_id=profile_id,
            owner_identity_id=owner,
            class_="enterprise",
            kyc_status="none",
            visibility="public",
            display_name="企业商业助理",
        )
    )
    await db_session.flush()

    r = await client.put(
        f"/v1/identity/role-profiles/{profile_id}",
        json={
            "spend_policy": {
                "permissions": ["request_voucher", "place_order"],
                "single_limit": 12,
                "daily_limit": 40,
                "high_risk_mode": "above_single",
            }
        },
        headers=_h(owner),
    )
    assert r.status_code == 200, r.text
    assert r.json()["spend_policy"]["single_limit"] == 12

    read = await client.get(
        f"/v1/identity/role-profiles/{profile_id}", headers=_h(owner)
    )
    assert read.status_code == 200
    assert read.json()["spend_policy"]["permissions"] == ["request_voucher", "place_order"]
