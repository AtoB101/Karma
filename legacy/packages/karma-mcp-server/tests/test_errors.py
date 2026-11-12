from karma_mcp_server.errors import (
    ErrorClass,
    KarmaToolError,
    classify_http_status,
    is_retryable,
    ok,
)


def test_classify_basic_codes():
    assert classify_http_status(401) is ErrorClass.UNAUTHORIZED
    assert classify_http_status(409) is ErrorClass.CONFLICT
    assert classify_http_status(429) is ErrorClass.RATE_LIMITED
    assert classify_http_status(422) is ErrorClass.INVALID
    assert classify_http_status(500) is ErrorClass.BACKEND


def test_403_activation_becomes_not_activated():
    assert (
        classify_http_status(403, "key is not activated: enter the 8-character matching code")
        is ErrorClass.NOT_ACTIVATED
    )
    assert (
        classify_http_status(403, "amount exceeds runtime key daily_limit") is ErrorClass.FORBIDDEN
    )


def test_retryable_set():
    assert is_retryable(ErrorClass.TRANSPORT)
    assert is_retryable(ErrorClass.RATE_LIMITED)
    assert is_retryable(ErrorClass.BACKEND)
    assert not is_retryable(ErrorClass.FORBIDDEN)
    assert not is_retryable(ErrorClass.CONFLICT)
    assert not is_retryable(ErrorClass.NOT_ACTIVATED)


def test_error_dict_is_never_success():
    err = KarmaToolError(ErrorClass.FORBIDDEN, "out of bounds", http_status=403)
    d = err.as_dict()
    assert d["ok"] is False
    assert d["error"]["class"] == "forbidden"
    assert d["error"]["retryable"] is False
    assert d["error"]["http_status"] == 403
    assert "next_step" in d["error"]


def test_ok_helper():
    assert ok()["ok"] is True
    assert ok({"a": 1}) == {"ok": True, "a": 1}
