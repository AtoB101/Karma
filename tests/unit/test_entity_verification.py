"""主体资质认证（数据 API 提供方）：官网控制权 + 密文资质 + verifier 复核。

红线与自然人认证一致：服务端只收密文与摘要，任何资质原件明文都不许进库。
每个用例用自己的 identity id —— 路由会 commit，共用 id 会互相污染。
"""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

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
DOMAIN = "data-example-{tag}.com"


def _ids() -> tuple[str, str, str, str]:
    tag = uuid.uuid4().hex[:10]
    return (
        f"kid_entity_{tag}",
        f"kid_entity_other_{tag}",
        f"kid_entity_reviewer_{tag}",
        f"data-example-{tag}.com",
    )


def _certs() -> list[dict[str, str]]:
    return [
        {"kind": "BUSINESS_LICENSE", "name": "营业执照", "digest": DIGEST_A},
        {"kind": "ICP_FILING", "name": "ICP 备案", "digest": DIGEST_B},
    ]


def _body(domain: str, **over):
    payload = {
        "subject_type": "business",
        "legal_name": "示例数据科技有限公司",
        "registration_no": "91330100MA2ABCDE12",
        "jurisdiction": "CN-ZJ",
        "legal_rep": "张三",
        "official_domain": domain,
        "contact_email": "ops@example.com",
        "service_category": "data_api",
        "service_scope": "交易所行情与地址风控数据接口，分钟级更新，按次计费",
        "certifications": _certs(),
        "doc_digest": DIGEST_A,
        "package_digest": DIGEST_C,
        "package_cipher": CIPHER,
        "encryption": dict(ENC),
        "extracted": {"consent": True, "legal_name": "示例数据科技有限公司"},
    }
    payload.update(over)
    return payload


def _h(identity: str) -> dict:
    return {"X-Karma-Identity-Id": identity}


async def _challenge(client: AsyncClient, identity: str, domain: str) -> dict:
    r = await client.post(
        f"/v1/identity/{identity}/entity-verification/website-challenge",
        json={"official_domain": domain},
        headers=_h(identity),
    )
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.asyncio
async def test_full_entity_verification_flow(client: AsyncClient, monkeypatch):
    owner, other, reviewer, domain = _ids()

    r = await client.get(f"/v1/identity/{owner}/entity-verification", headers=_h(owner))
    assert r.status_code == 200 and r.json()["status"] == "none"

    # 1) 生成官网校验文件内容
    ch = await _challenge(client, owner, domain)
    assert ch["official_domain"] == domain
    assert ch["challenge"]["url"] == f"https://{domain}/.well-known/karma-entity-verify.txt"
    token = ch["challenge"]["token"]

    # 2) 没做官网回读就提交 -> 拒
    r = await client.post(
        f"/v1/identity/{owner}/entity-verification/submit",
        json=_body(domain),
        headers=_h(owner),
    )
    assert r.status_code == 409 and "官网" in r.json()["detail"]

    # 3) 回读到的 token 不对 -> 400
    from api.routes import entity_verification as route

    async def _wrong(domain_: str, **kwargs) -> str:
        return "karma-entity-verify=deadbeef" + token

    monkeypatch.setattr(route, "fetch_website_proof", _wrong)
    r = await client.post(
        f"/v1/identity/{owner}/entity-verification/website-verify", headers=_h(owner)
    )
    assert r.status_code == 400, r.text

    # 4) 正确 token -> 通过
    async def _right(domain_: str, **kwargs) -> str:
        return f"# karma proof\nkarma-entity-verify={token}\n"

    monkeypatch.setattr(route, "fetch_website_proof", _right)
    r = await client.post(
        f"/v1/identity/{owner}/entity-verification/website-verify", headers=_h(owner)
    )
    assert r.status_code == 200, r.text
    assert r.json()["website_verified"] is True

    # 5) 提交审核
    r = await client.post(
        f"/v1/identity/{owner}/entity-verification/submit",
        json=_body(domain),
        headers=_h(owner),
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending"
    assert r.json()["package_bytes"] == len(CIPHER)
    assert r.json()["has_package"] is True

    # 6) 别的身份不能提交/复核自己的
    r = await client.post(
        f"/v1/identity/{owner}/entity-verification/submit",
        json=_body(domain),
        headers=_h(other),
    )
    assert r.status_code == 403

    # 7) 没有 verifier 类档案 -> 403
    r = await client.post(
        f"/v1/identity/{owner}/entity-verification/verify",
        json={"decision": "verified"},
        headers=_h(reviewer),
    )
    assert r.status_code == 403

    # 8) 建一个 verifier 档案后可以复核
    # verifier 是治理角色，默认不许自助开通（要运维白名单）；这里把复核方放进白名单，
    # 「不给白名单就 403」这件事在 tests/integration/test_developer_api.py 覆盖。
    from config.settings import settings

    monkeypatch.setattr(settings, "governance_verifier_ids", reviewer)
    r = await client.post(
        "/v1/identity/role-profiles",
        json={"owner_identity_id": reviewer, "class": "verifier", "display_name": "审" },
        headers=_h(reviewer),
    )
    assert r.status_code == 201, r.text
    r = await client.post(
        f"/v1/identity/{owner}/entity-verification/verify",
        json={"decision": "verified", "reason": "营业执照与官网一致"},
        headers=_h(reviewer),
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "verified"
    assert r.json()["verified_at"]

    # 9) 公开视图：给尽调看的工商信息，不含联系方式、不含密文
    r = await client.get(f"/v1/entities/{owner}")
    assert r.status_code == 200
    public = r.json()
    assert public["legal_name"] == "示例数据科技有限公司"
    assert public["website_verified"] is True
    assert "contact_email" not in public
    assert "package_cipher" not in public


@pytest.mark.asyncio
async def test_plaintext_certificate_is_rejected(client: AsyncClient):
    owner, _other, _reviewer, domain = _ids()
    await _challenge(client, owner, domain)

    body = _body(domain)
    body["photo"] = "data:image/png;base64,AAAA"  # 有人想把证件原图直接传上来
    r = await client.post(
        f"/v1/identity/{owner}/entity-verification/submit", json=body, headers=_h(owner)
    )
    assert r.status_code == 400, r.text
    assert "plaintext" in r.json()["detail"]


@pytest.mark.asyncio
async def test_business_license_is_mandatory(client: AsyncClient):
    owner, _other, _reviewer, domain = _ids()
    await _challenge(client, owner, domain)
    body = _body(domain, certifications=[{"kind": "ICP_FILING", "name": "ICP", "digest": DIGEST_B}])
    r = await client.post(
        f"/v1/identity/{owner}/entity-verification/submit", json=body, headers=_h(owner)
    )
    assert r.status_code == 400
    assert "BUSINESS_LICENSE" in r.json()["detail"]


@pytest.mark.asyncio
async def test_private_domain_is_refused(client: AsyncClient):
    owner, *_ = _ids()
    r = await client.post(
        f"/v1/identity/{owner}/entity-verification/website-challenge",
        json={"official_domain": "127.0.0.1"},
        headers=_h(owner),
    )
    assert r.status_code == 400, r.text