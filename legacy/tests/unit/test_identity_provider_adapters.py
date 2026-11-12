"""四个适配器：会话怎么开、回调怎么读、结论怎么归一化。

离线跑：出网的那几个函数（``post_form`` / ``post_json`` / ``get_json``）在测试里被换掉，
所以这里不碰任何真实服务商，也不会因为断网变红。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from types import SimpleNamespace

import pytest

from services.identity_provider import registry
from services.identity_provider.aliyun import (
    AliyunIdentityProvider,
    percent_encode,
    rpc_signature,
)
from services.identity_provider.base import (
    OUTCOME_PENDING,
    OUTCOME_REJECTED,
    OUTCOME_VERIFIED,
    ProviderError,
    ProviderNotConfigured,
    ProviderSignatureError,
)
from services.identity_provider.mock import MockIdentityProvider
from services.identity_provider.persona import PersonaIdentityProvider
from services.identity_provider.signature import sign_timestamped_hmac
from services.identity_provider.tencent import TencentIdentityProvider, tc3_authorization

# --------------------------------------------------------------------------- 阿里云


def test_aliyun_percent_encode_matches_the_documented_rules():
    assert percent_encode("a b") == "a%20b"      # 空格是 %20，不是 +
    assert percent_encode("a*b") == "a%2Ab"
    assert percent_encode("a~b") == "a~b"        # ~ 不被编码
    assert percent_encode("/") == "%2F"


def test_aliyun_rpc_signature_matches_the_official_example():
    """阿里云官方文档里的示例：密钥 testsecret + 这组参数 = 这个签名。

    这条是**外部已知向量**：只要百分号编码或拼接顺序改错一位，它就对不上。
    """
    params = {
        "AccessKeyId": "testid",
        "Action": "DescribeRegions",
        "Format": "XML",
        "SignatureMethod": "HMAC-SHA1",
        "SignatureNonce": "3ee8c1b8-83d3-44af-a94f-4e0ad82fd6cf",
        "SignatureVersion": "1.0",
        "Timestamp": "2016-02-23T12:46:24Z",
        "Version": "2014-05-26",
    }
    assert rpc_signature(params, "testsecret", method="GET") == "OLeaidS1JvxuMvnyHOwuJ+uX5qY="


def _aliyun_settings(**over):
    base = dict(
        identity_provider_aliyun_access_key_id="LTAI-test",
        identity_provider_aliyun_access_key_secret="secret-test",
        identity_provider_aliyun_scene_id="1000000123",
        identity_provider_aliyun_endpoint="cloudauth.aliyuncs.com",
        identity_provider_aliyun_region="cn-hangzhou",
        identity_provider_callback_tolerance_seconds=300,
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_aliyun_reports_exactly_what_is_missing():
    provider = AliyunIdentityProvider(_aliyun_settings(identity_provider_aliyun_scene_id=""))
    assert provider.missing_config() == ["IDENTITY_PROVIDER_ALIYUN_SCENE_ID"]
    assert provider.is_configured() is False
    assert AliyunIdentityProvider(_aliyun_settings()).is_configured() is True


@pytest.mark.asyncio
async def test_aliyun_create_session_returns_certify_id_and_url(monkeypatch):
    captured: dict = {}

    async def fake_post_form(url, data, **kw):
        captured["url"] = url
        captured["data"] = data
        return {"Code": "Success", "ResultObject": {"CertifyId": "cid-1", "CertifyUrl": "https://certify.example/1"}}

    monkeypatch.setattr("services.identity_provider.aliyun.post_form", fake_post_form)
    provider = AliyunIdentityProvider(_aliyun_settings())
    created = await provider.create_session(
        identity_id="kid_aaa", session_id="sess-1", callback_url="https://karma.example/cb"
    )
    assert created["provider_session_id"] == "cid-1"
    assert created["verify_url"] == "https://certify.example/1"
    assert created["mode"] == "both"
    # 出网请求必须带签名，且把 identity_id 塞进 MetaInfo（用来绑回身份）
    assert captured["data"]["Signature"]
    assert captured["data"]["AccessKeyId"] == "LTAI-test"
    assert "kid_aaa" in captured["data"]["MetaInfo"]
    assert captured["url"].startswith("https://cloudauth.aliyuncs.com")


@pytest.mark.asyncio
async def test_aliyun_create_session_fails_loudly_without_certify_id(monkeypatch):
    async def fake_post_form(url, data, **kw):
        return {"Code": "Success", "ResultObject": {}}

    monkeypatch.setattr("services.identity_provider.aliyun.post_form", fake_post_form)
    provider = AliyunIdentityProvider(_aliyun_settings())
    with pytest.raises(ProviderError):
        await provider.create_session(
            identity_id="kid_aaa", session_id="s", callback_url="https://k/cb"
        )


@pytest.mark.asyncio
async def test_aliyun_callback_only_asks_for_a_lookup():
    """回调本身不作定论：只取 CertifyId，标记 requires_pull。"""
    provider = AliyunIdentityProvider(_aliyun_settings())
    decision = await provider.parse_callback(
        headers={}, raw_body=json.dumps({"CertifyId": "cid-9", "OuterOrderNo": "sess-1"}).encode()
    )
    assert decision.requires_pull is True
    assert decision.outcome == OUTCOME_PENDING
    assert decision.provider_session_id == "cid-9"
    assert decision.raw_digest


@pytest.mark.asyncio
async def test_aliyun_callback_without_certify_id_is_rejected():
    provider = AliyunIdentityProvider(_aliyun_settings())
    with pytest.raises(ProviderError) as exc:
        await provider.parse_callback(headers={}, raw_body=b'{"foo":"bar"}')
    assert exc.value.status == 400


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "passed,expected",
    [("T", OUTCOME_VERIFIED), ("F", OUTCOME_REJECTED), ("", OUTCOME_PENDING)],
)
async def test_aliyun_pull_maps_passed_flag(monkeypatch, passed, expected):
    async def fake_post_form(url, data, **kw):
        return {"Code": "Success", "ResultObject": {"Passed": passed, "SubCode": "OK"}}

    monkeypatch.setattr("services.identity_provider.aliyun.post_form", fake_post_form)
    provider = AliyunIdentityProvider(_aliyun_settings())
    decision = await provider.fetch_result(provider_session_id="cid-1")
    assert decision.outcome == expected
    assert decision.source == "poll"


# --------------------------------------------------------------------------- 腾讯云


def test_tencent_tc3_signature_is_a_real_signed_header():
    """按官方步骤独立算一遍，和适配器里的实现对得上（任何一步写错都会露出来）。"""
    secret_id, secret_key = "AKIDtest", "Gu5t9xGARNpq86cd98joQYCN3test"
    payload = "{\"Limit\":1}"
    timestamp = 1551113065
    region = "ap-guangzhou"
    # 独立实现：不复用适配器里的任何函数
    date = "2019-02-25"
    host, service = "faceid.tencentcloudapi.com", "faceid"
    canonical_headers = "content-type:application/json; charset=utf-8\nhost:%s\n" % host
    signed_headers = "content-type;host"
    hashed_payload = hashlib.sha256(payload.encode()).hexdigest()
    canonical_request = "\n".join(["POST", "/", "", canonical_headers, signed_headers, hashed_payload])
    scope = "%s/%s/tc3_request" % (date, service)
    sts = "\n".join(
        ["TC3-HMAC-SHA256", str(timestamp), scope, hashlib.sha256(canonical_request.encode()).hexdigest()]
    )
    def _h(key, msg):
        return hmac.new(key, msg.encode(), hashlib.sha256).digest()
    k_date = _h(("TC3" + secret_key).encode(), date)
    k_service = _h(k_date, service)
    k_signing = _h(k_service, "tc3_request")
    expected_sig = hmac.new(k_signing, sts.encode(), hashlib.sha256).hexdigest()

    header = tc3_authorization(
        secret_id=secret_id, secret_key=secret_key, action="DetectAuth",
        payload=payload, timestamp=timestamp, region=region,
    )
    assert header == (
        "TC3-HMAC-SHA256 Credential=%s/%s, SignedHeaders=%s, Signature=%s"
        % (secret_id, scope, signed_headers, expected_sig)
    )


def test_tencent_different_payload_gives_different_signature():
    args = dict(secret_id="a", secret_key="b", action="DetectAuth", timestamp=1551113065, region="ap-guangzhou")
    assert tc3_authorization(payload="{\"x\":1}", **args) != tc3_authorization(payload="{\"x\":2}", **args)


def _tencent_settings(**over):
    base = dict(
        identity_provider_tencent_secret_id="AKIDtest",
        identity_provider_tencent_secret_key="SECRET",
        identity_provider_tencent_rule_id="1",
        identity_provider_tencent_region="ap-guangzhou",
        identity_provider_callback_tolerance_seconds=300,
    )
    base.update(over)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_tencent_create_session_returns_biz_token(monkeypatch):
    seen: dict = {}

    async def fake_post_json(url, payload, headers=None, **kw):
        seen["url"] = url
        seen["headers"] = headers or {}
        seen["payload"] = payload
        return {"Response": {"BizToken": "tok-1", "Url": "https://faceid.example/1"}}

    monkeypatch.setattr("services.identity_provider.tencent.post_json", fake_post_json)
    provider = TencentIdentityProvider(_tencent_settings())
    created = await provider.create_session(
        identity_id="kid_bbb", session_id="sess-2", callback_url="https://karma.example/cb"
    )
    assert created["provider_session_id"] == "tok-1"
    assert created["verify_url"] == "https://faceid.example/1"
    assert seen["headers"]["X-TC-Action"] == "DetectAuth"
    assert "kid_bbb" in seen["payload"]["Extra"]
    assert seen["url"] == "https://faceid.tencentcloudapi.com"


@pytest.mark.asyncio
async def test_tencent_api_error_is_translated_and_hides_message(monkeypatch):
    async def fake_post_json(url, payload, headers=None, **kw):
        return {"Response": {"Error": {"Code": "AuthFailure.SignatureFailure", "Message": "uid 12345"}}}

    monkeypatch.setattr("services.identity_provider.tencent.post_json", fake_post_json)
    provider = TencentIdentityProvider(_tencent_settings())
    with pytest.raises(ProviderError) as exc:
        await provider.create_session(identity_id="k", session_id="s", callback_url="https://k/cb")
    assert "AuthFailure" in exc.value.message
    assert "12345" not in exc.value.message      # 服务商信息里可能带用户标识，不透传


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "err_code,expected", [(0, OUTCOME_VERIFIED), (1001, OUTCOME_REJECTED)]
)
async def test_tencent_pull_maps_err_code(monkeypatch, err_code, expected):
    async def fake_post_json(url, payload, headers=None, **kw):
        return {"Response": {"Text": {"ErrCode": err_code}}}

    monkeypatch.setattr("services.identity_provider.tencent.post_json", fake_post_json)
    provider = TencentIdentityProvider(_tencent_settings())
    decision = await provider.fetch_result(provider_session_id="tok-1")
    assert decision.outcome == expected


@pytest.mark.asyncio
async def test_tencent_callback_requires_a_lookup():
    provider = TencentIdentityProvider(_tencent_settings())
    decision = await provider.parse_callback(headers={}, raw_body=b'{"BizToken":"tok-9"}')
    assert decision.requires_pull is True
    assert decision.provider_session_id == "tok-9"
    with pytest.raises(ProviderError):
        await provider.parse_callback(headers={}, raw_body=b'{"nothing":1}')


# --------------------------------------------------------------------------- Persona


def _persona_settings(**over):
    base = dict(
        identity_provider_persona_api_key="persona_test_key",
        identity_provider_persona_template_id="itmpl_test",
        identity_provider_persona_webhook_secret="whsec_test",
        identity_provider_callback_tolerance_seconds=300,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _persona_event(status: str, ref: str = "sess-3", inquiry_id: str = "inq-1") -> bytes:
    return json.dumps(
        {
            "data": {
                "type": "event",
                "attributes": {
                    "name": "inquiry.completed",
                    "payload": {
                        "data": {
                            "type": "inquiry",
                            "id": inquiry_id,
                            "attributes": {"status": status, "reference-id": ref},
                        }
                    },
                },
            }
        }
    ).encode()


async def _persona_callback(settings, body: bytes):
    provider = PersonaIdentityProvider(settings)
    signature = sign_timestamped_hmac(
        secret=settings.identity_provider_persona_webhook_secret, raw_body=body
    )
    return await provider.parse_callback(
        headers={"Persona-Signature": signature}, raw_body=body
    )


@pytest.mark.asyncio
async def test_persona_webhook_is_signature_verified():
    settings = _persona_settings()
    body = _persona_event("completed")
    decision = await _persona_callback(settings, body)
    assert decision.outcome == OUTCOME_VERIFIED
    assert decision.session_id == "sess-3"
    assert decision.provider_session_id == "inq-1"

    provider = PersonaIdentityProvider(settings)
    with pytest.raises(ProviderSignatureError):
        await provider.parse_callback(
            headers={"Persona-Signature": "t=1,v1=deadbeef"}, raw_body=body
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,expected",
    [
        ("completed", OUTCOME_VERIFIED),
        ("declined", OUTCOME_REJECTED),
        ("expired", OUTCOME_REJECTED),
        ("pending", OUTCOME_PENDING),
        ("needs_review", OUTCOME_PENDING),
    ],
)
async def test_persona_status_mapping(status, expected):
    decision = await _persona_callback(_persona_settings(), _persona_event(status))
    assert decision.outcome == expected


@pytest.mark.asyncio
async def test_persona_unknown_status_never_passes():
    with pytest.raises(ProviderError):
        await _persona_callback(_persona_settings(), _persona_event("something-new"))


@pytest.mark.asyncio
async def test_persona_accepts_a_bare_inquiry_body():
    settings = _persona_settings()
    body = json.dumps(
        {"data": {"type": "inquiry", "id": "inq-7", "attributes": {"status": "completed", "reference-id": "sess-7"}}}
    ).encode()
    decision = await _persona_callback(settings, body)
    assert decision.outcome == OUTCOME_VERIFIED
    assert decision.provider_session_id == "inq-7"


@pytest.mark.asyncio
async def test_persona_create_session_and_pull(monkeypatch):
    async def fake_post_json(url, payload, headers=None, **kw):
        assert headers["Authorization"].startswith("Bearer ")
        assert payload["data"]["attributes"]["reference-id"] == "sess-9"
        return {"data": {"id": "inq-9", "attributes": {"status": "created"}}}

    async def fake_get_json(url, headers=None, **kw):
        return {"data": {"id": "inq-9", "attributes": {"status": "completed", "reference-id": "sess-9"}}}

    monkeypatch.setattr("services.identity_provider.persona.post_json", fake_post_json)
    monkeypatch.setattr("services.identity_provider.persona.get_json", fake_get_json)
    provider = PersonaIdentityProvider(_persona_settings())
    created = await provider.create_session(
        identity_id="kid_c", session_id="sess-9", callback_url="https://karma.example/cb"
    )
    assert created["provider_session_id"] == "inq-9"
    assert created["verify_url"].endswith("inquiry-id=inq-9")
    decision = await provider.fetch_result(provider_session_id="inq-9")
    assert decision.outcome == OUTCOME_VERIFIED


# --------------------------------------------------------------------------- mock


def _mock_settings(**over):
    base = dict(
        identity_provider_callback_secret="mock-secret", identity_provider_callback_tolerance_seconds=300
    )
    base.update(over)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_mock_round_trip_and_signature_enforcement():
    settings = _mock_settings()
    provider = MockIdentityProvider(settings)
    created = await provider.create_session(
        identity_id="kid_d", session_id="sess-m", callback_url="https://karma.example/cb"
    )
    assert created["provider_session_id"] == "mock-sess-m"

    body = json.dumps({"session_id": "sess-m", "identity_id": "kid_d", "outcome": "verified"}).encode()
    good = sign_timestamped_hmac(secret="mock-secret", raw_body=body)
    decision = await provider.parse_callback(
        headers={"x-karma-provider-signature": good}, raw_body=body
    )
    assert decision.outcome == OUTCOME_VERIFIED
    assert decision.identity_id == "kid_d"

    with pytest.raises(ProviderSignatureError):
        await provider.parse_callback(headers={}, raw_body=body)
    with pytest.raises(ProviderSignatureError):
        await provider.parse_callback(
            headers={"x-karma-provider-signature": sign_timestamped_hmac(secret="wrong", raw_body=body)},
            raw_body=body,
        )


@pytest.mark.asyncio
async def test_mock_rejects_unknown_outcome_and_is_unconfigured_without_secret():
    provider = MockIdentityProvider(_mock_settings(identity_provider_callback_secret=""))
    assert provider.is_configured() is False
    assert provider.missing_config() == ["IDENTITY_PROVIDER_CALLBACK_SECRET"]
    with pytest.raises(ProviderNotConfigured):
        await provider.create_session(identity_id="k", session_id="s", callback_url="https://k/cb")

    provider2 = MockIdentityProvider(_mock_settings())
    body = json.dumps({"session_id": "s", "outcome": "maybe"}).encode()
    sig = sign_timestamped_hmac(secret="mock-secret", raw_body=body)
    with pytest.raises(ProviderError):
        await provider2.parse_callback(headers={"x-karma-provider-signature": sig}, raw_body=body)


# --------------------------------------------------------------------------- registry


def test_registry_refuses_to_pretend(monkeypatch):
    from config.settings import settings as live_settings

    monkeypatch.setattr(live_settings, "identity_provider", "none")
    with pytest.raises(ProviderNotConfigured):
        registry.resolve_provider()
    status = registry.provider_status()
    assert status["provider"] == "none"
    assert status["configured"] is False

    monkeypatch.setattr(live_settings, "identity_provider", "aliyun")
    monkeypatch.setattr(live_settings, "identity_provider_aliyun_access_key_id", "")
    monkeypatch.setattr(live_settings, "identity_provider_aliyun_access_key_secret", "")
    monkeypatch.setattr(live_settings, "identity_provider_aliyun_scene_id", "")
    with pytest.raises(ProviderNotConfigured):
        registry.resolve_provider()
    status = registry.provider_status()
    assert status["usable"] is False
    assert "IDENTITY_PROVIDER_ALIYUN_SCENE_ID" in status["missing"]

    monkeypatch.setattr(live_settings, "identity_provider", "not-a-provider")
    with pytest.raises(ProviderNotConfigured):
        registry.resolve_provider()


def test_registry_rejects_mock_in_production_guard_exists():
    """生产禁止 mock：这条守卫在 settings 的校验里（见 config/settings.py）。"""
    import pathlib
    import re

    source = pathlib.Path("config/settings.py").read_text(encoding="utf-8")
    assert re.search(r'identity_provider\"\)\s*\.strip\(\)\.lower\(\)\s*==\s*\"mock\"', source) or "== \"mock\"" in source
    assert "IDENTITY_PROVIDER=mock is not allowed" in source
