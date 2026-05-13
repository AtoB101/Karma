from karma_openmanus.hmac_auth import hmac_hex_signature


def test_hmac_matches_integration_canonical():
    secret = "test-secret"
    ts = "1700000000"
    body = '{"trace_id":"t1"}'
    sig = hmac_hex_signature(secret, ts, body)
    assert len(sig) == 64
    assert sig == hmac_hex_signature(secret, ts, body)
    assert sig != hmac_hex_signature(secret, ts, body + "x")


def test_hmac_empty_body():
    secret = "x"
    ts = "1"
    assert len(hmac_hex_signature(secret, ts, "")) == 64
