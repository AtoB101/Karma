"""技能上架核验：主体已认证 + endpoint 落在官网域名下 + 本人钱包签名。

上架是"钱从哪来"的起点，所以三条硬约束一条都不能松：
没有主体认证不能上架；endpoint 不在自己认证过的域名下不能上架；
签名不是本人在册钱包签的不能上架。
"""
from __future__ import annotations

import uuid

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.orm import EntityVerificationModel, IdentityProfileModel, SkillDeveloperModel
from services import skill_registry
from services.developer_registry import AGREEMENT_VERSION, agreement_digest

ACCOUNT = Account.create()
KEY = ACCOUNT.key.hex()
WALLET = ACCOUNT.address.lower()


def _tag() -> str:
    return uuid.uuid4().hex[:10]


async def _entity(
    db: AsyncSession, identity_id: str, *, domain: str, status: str = "verified"
) -> None:
    db.add(
        EntityVerificationModel(
            identity_id=identity_id,
            status=status,
            subject_type="business",
            legal_name="示例数据科技有限公司",
            official_domain=domain,
            service_category="data_api",
        )
    )
    await db.flush()


async def _bind_wallet(db: AsyncSession, identity_id: str) -> None:
    db.add(
        IdentityProfileModel(
            identity_id=identity_id,
            display_id="Karma-ID-SKILL1",
            legal_identity_status="unbound",
            status="active",
            bound_wallet_address=WALLET,
        )
    )
    await db.flush()


async def _developer(db: AsyncSession, identity_id: str) -> None:
    """上架还要过「开发者实名」：主体已认证 + 这个人签过协议 + 同一个钱包签名。"""
    db.add(
        SkillDeveloperModel(
            identity_id=identity_id,
            legal_name="示例数据科技有限公司",
            real_name="张三",
            role_title="数据平台负责人",
            contact_email="zhangsan@example.com",
            developer_role="api_owner",
            agreement_version=AGREEMENT_VERSION,
            agreement_digest=agreement_digest(),
            signer_wallet=WALLET,
            status="verified",
        )
    )
    await db.flush()


def _payload(domain: str, slug: str, **over) -> dict:
    data = {
        "slug": slug,
        "name": "行情快照 API",
        "category": "data_api",
        "summary": "按次计费的交易所行情快照，毫秒级返回",
        "description": "支持 20+ 交易所，单次 0.001 USDC，累计到 0.05 出账",
        "endpoint_url": f"https://{domain}/v1/ticker",
        "method": "POST",
        "unit": "call",
        "unit_price_usdc": 0.001,
        "settlement_threshold_usdc": 0.05,
        "default_cap_usdc": 5.0,
    }
    data.update(over)
    return data


def _prep(identity_id: str, payload: dict, domain: str, *, version: int = 1) -> tuple[dict, str, str]:
    normalized = skill_registry.normalize_payload(payload, official_domain=domain)
    manifest = skill_registry.build_manifest(normalized, version=version)
    digest = skill_registry.manifest_digest(manifest)
    message = skill_registry.build_publish_message(
        identity_id=identity_id, manifest=manifest, digest=digest
    )
    return normalized, digest, message


def _sign(message: str, key: str = KEY) -> str:
    return Account.sign_message(encode_defunct(text=message), private_key=key).signature.hex()


def test_slug_shape_is_enforced():
    assert skill_registry.normalize_slug("Ticker-Snapshot") == "ticker-snapshot"
    for bad in ("ab", "-leading", "trailing-", "has_underscore", "a" * 41, "with space"):
        with pytest.raises(skill_registry.SkillError):
            skill_registry.normalize_slug(bad)


def test_endpoint_must_live_under_the_verified_domain():
    ok = skill_registry.validate_endpoint_under_domain(
        "https://api.data-example.com/v1/ticker", "data-example.com"
    )
    assert ok == "https://api.data-example.com/v1/ticker"
    for bad, expect in (
        ("https://evil.com/v1/ticker", "不在你认证过的官网域名"),
        ("http://data-example.com/v1/ticker", "https"),
        ("https://data-example.com:9000/v1/ticker", "端口"),
    ):
        with pytest.raises(skill_registry.SkillError) as exc:
            skill_registry.validate_endpoint_under_domain(bad, "data-example.com")
        assert expect in exc.value.message


def test_manifest_digest_is_reproducible():
    payload = _payload("data-example.com", "ticker-snapshot")
    _, digest_a, message_a = _prep("kid_x", payload, "data-example.com")
    _, digest_b, message_b = _prep("kid_x", payload, "data-example.com")
    assert digest_a == digest_b
    assert message_a == message_b
    # 改一个字节，摘要和签名串都要变 —— 这就是"服务端不用审批价格"的依据
    _, digest_c, _ = _prep("kid_x", payload, "data-example.com", version=2)
    assert digest_c != digest_a


@pytest.mark.asyncio
async def test_publish_requires_verified_entity(db_session: AsyncSession):
    identity = f"kid_skill_{_tag()}"
    payload = _payload("data-example.com", f"ticker-{_tag()}")
    _, _, message = _prep(identity, payload, "data-example.com")
    with pytest.raises(skill_registry.SkillError) as exc:
        await skill_registry.publish(
            db_session, identity_id=identity, payload=payload, signature=_sign(message)
        )
    assert exc.value.status == 409
    assert "主体认证" in exc.value.message


@pytest.mark.asyncio
async def test_publish_requires_the_owners_own_signature(
    db_session: AsyncSession, monkeypatch
):
    identity = f"kid_skill_{_tag()}"
    slug = f"ticker-{_tag()}"
    await _entity(db_session, identity, domain="data-example.com")

    # 还没绑定钱包 -> 409
    payload = _payload("data-example.com", slug)
    _, _, message = _prep(identity, payload, "data-example.com")
    with pytest.raises(skill_registry.SkillError) as exc:
        await skill_registry.publish(
            db_session, identity_id=identity, payload=payload, signature=_sign(message)
        )
    assert exc.value.status == 409 and "钱包" in exc.value.message

    await _bind_wallet(db_session, identity)
    await _developer(db_session, identity)

    # 别人拿自己的私钥签 -> 403
    stranger = Account.create()
    with pytest.raises(skill_registry.SkillError) as exc:
        await skill_registry.publish(
            db_session,
            identity_id=identity,
            payload=payload,
            signature=_sign(message, key=stranger.key.hex()),
        )
    assert exc.value.status == 403

    # 本人签 -> 上架成功，版本号与摘要都落库
    row = await skill_registry.publish(
        db_session, identity_id=identity, payload=payload, signature=_sign(message)
    )
    assert row.status == "published"
    assert row.publisher_wallet == WALLET
    assert row.verified_domain == "data-example.com"
    assert row.version == 1
    assert row.manifest_digest == skill_registry.manifest_digest(
        skill_registry.build_manifest(
            skill_registry.normalize_payload(payload, official_domain="data-example.com"),
            version=1,
        )
    )

    # 重新上架 -> 版本 +1，签名必须跟着新版本号重签
    _, _, message_v1 = _prep(identity, payload, "data-example.com", version=1)
    with pytest.raises(skill_registry.SkillError) as exc:
        await skill_registry.publish(
            db_session, identity_id=identity, payload=payload, signature=_sign(message_v1)
        )
    assert exc.value.status == 403  # v1 的签名验不过 v2 的串

    _, _, message_v2 = _prep(identity, payload, "data-example.com", version=2)
    row = await skill_registry.publish(
        db_session, identity_id=identity, payload=payload, signature=_sign(message_v2)
    )
    assert row.version == 2


@pytest.mark.asyncio
async def test_foreign_domain_endpoint_is_refused(db_session: AsyncSession):
    identity = f"kid_skill_{_tag()}"
    await _entity(db_session, identity, domain="data-example.com")
    await _bind_wallet(db_session, identity)
    payload = _payload("data-example.com", f"ticker-{_tag()}", endpoint_url="https://evil.com/steal")
    # 连签名串都拼不出来：校验发生在上架之前，客户端自己也过不去。
    with pytest.raises(skill_registry.SkillError) as exc:
        _prep(identity, payload, "data-example.com")
    assert exc.value.status == 400 and "官网域名" in exc.value.message

    with pytest.raises(skill_registry.SkillError) as exc:
        await skill_registry.publish(
            db_session, identity_id=identity, payload=payload, signature="0x" + "00" * 65
        )
    assert exc.value.status == 400 and "官网域名" in exc.value.message


@pytest.mark.asyncio
async def test_catalog_only_lists_published(db_session: AsyncSession):
    identity = f"kid_skill_{_tag()}"
    slug = f"ticker-{_tag()}"
    await _entity(db_session, identity, domain="data-example.com")
    await _bind_wallet(db_session, identity)
    await _developer(db_session, identity)
    payload = _payload("data-example.com", slug)
    _, _, message = _prep(identity, payload, "data-example.com")
    row = await skill_registry.publish(
        db_session, identity_id=identity, payload=payload, signature=_sign(message)
    )

    listed = await skill_registry.list_published(db_session, query=slug)
    assert [s.slug for s in listed] == [slug]

    await skill_registry.pause(db_session, identity_id=identity, slug=slug)
    assert await skill_registry.list_published(db_session, query=slug) == []
    assert str(row.status) == "paused"