import httpx
import pytest
from karma_mcp_server.backend_client import KarmaBackend
from karma_mcp_server.config import McpConfig
from karma_mcp_server.errors import ErrorClass, KarmaToolError


def _backend(handler, *, runtime_key="KRM_RT_kid_secret", agent_seed=""):
    return KarmaBackend(
        McpConfig(runtime_base_url="http://karma.test"),
        runtime_key=runtime_key,
        agent_private_key_seed=agent_seed,
        transport=httpx.MockTransport(handler),
        credential_fn=lambda name: "",
    )


async def test_no_runtime_key_is_unauthorized():
    be = _backend(lambda r: httpx.Response(200, json={}), runtime_key="")
    with pytest.raises(KarmaToolError) as exc:
        await be.runtime_get("/runtime/permissions")
    assert exc.value.error_class is ErrorClass.UNAUTHORIZED


async def test_success_returns_json():
    be = _backend(lambda r: httpx.Response(200, json={"key_id": "kid"}))
    assert await be.runtime_get("/runtime/permissions") == {"key_id": "kid"}


async def test_403_activation_maps_to_not_activated():
    be = _backend(
        lambda r: httpx.Response(
            403, json={"detail": "runtime key is not activated yet; enter the matching code"}
        )
    )
    with pytest.raises(KarmaToolError) as exc:
        await be.runtime_get("/runtime/permissions")
    assert exc.value.error_class is ErrorClass.NOT_ACTIVATED
    assert exc.value.info.http_status == 403
    assert "配对码" in (exc.value.info.next_step or "")


async def test_403_policy_maps_to_forbidden():
    be = _backend(
        lambda r: httpx.Response(403, json={"detail": "amount exceeds runtime key daily_limit"})
    )
    with pytest.raises(KarmaToolError) as exc:
        await be.runtime_post("/runtime/place-order", {"amount": 999})
    assert exc.value.error_class is ErrorClass.FORBIDDEN


async def test_409_conflict_404_invalid_500_backend():
    for status, expected in (
        (409, ErrorClass.CONFLICT),
        (404, ErrorClass.INVALID),
        (500, ErrorClass.BACKEND),
    ):
        be = _backend(lambda r, s=status: httpx.Response(s, json={"detail": "x"}))
        with pytest.raises(KarmaToolError) as exc:
            await be.runtime_get("/runtime/permissions")
        assert exc.value.error_class is expected


async def test_network_error_maps_to_transport():
    def boom(request):
        raise httpx.ConnectError("refused", request=request)

    be = _backend(boom)
    with pytest.raises(KarmaToolError) as exc:
        await be.runtime_get("/runtime/permissions")
    assert exc.value.error_class is ErrorClass.TRANSPORT
    assert exc.value.info.retryable is True


async def test_signing_mode_turns_on_after_probe_and_signs_request():
    seen = {}

    def handler(request):
        if request.url.path == "/runtime/permissions" and request.method == "GET":
            seen.setdefault("probe", []).append(dict(request.headers))
            return httpx.Response(
                401, json={"detail": "X-Karma-Agent-Signature header is required"}
            )
        seen["signed_headers"] = request.headers
        return httpx.Response(200, json={"ok": True})

    import base64

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    seed = base64.b64encode(Ed25519PrivateKey.generate().private_bytes_raw()).decode()
    be = _backend(handler, agent_seed=seed)
    out = await be.runtime_post(
        "/runtime/place-order", {"amount": 1}, extra_headers={"Idempotency-Key": "abc"}
    )
    assert out == {"ok": True}
    hdrs = seen["signed_headers"]
    assert "X-Karma-Agent-Signature" in hdrs
    assert "X-Karma-Runtime-Timestamp" in hdrs
    assert "X-Karma-Runtime-Nonce" in hdrs
    assert hdrs["Idempotency-Key"] == "abc"
    assert hdrs["X-Karma-Runtime-Key"] == "KRM_RT_kid_secret"


async def test_unbound_key_is_not_signed():
    seen = {}

    def handler(request):
        seen["headers"] = request.headers
        return httpx.Response(200, json={"key_id": "kid"})

    be = _backend(handler, agent_seed="")
    await be.runtime_get("/runtime/permissions")
    assert "x-karma-agent-signature" not in seen["headers"]
