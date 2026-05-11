"""Smoke tests for Karma BFF (requires fastapi + httpx)."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
import time
import unittest

try:
    from fastapi.testclient import TestClient
except ImportError:
    TestClient = None  # type: ignore[misc, assignment]


def _sign(secret: str, body: dict) -> tuple[str, str, bytes]:
    raw = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ts = str(int(time.time()))
    sig = hmac.new(secret.encode("utf-8"), ts.encode("utf-8") + b"\n" + raw, hashlib.sha256).hexdigest()
    return ts, sig, raw


@unittest.skipUnless(TestClient is not None, "fastapi not installed")
class KarmaBffSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        fd, cls.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.environ["BFF_DATABASE_PATH"] = cls.db
        os.environ["BFF_INTEGRATION_SECRET"] = "unit-test-secret-min-32-characters-long!!"
        os.environ["BFF_PUBLIC_BASE_URL"] = "http://test"

        from apps.karma_bff.app.main import app

        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            os.unlink(cls.db)
        except OSError:
            pass

    def test_health(self) -> None:
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")

    def test_hmac_create_and_webhook_flow(self) -> None:
        secret = os.environ["BFF_INTEGRATION_SECRET"]
        body = {"trace_id": "tr-smoke-1", "task_id": "task-1", "agent_id": "ag", "runtime_id": "om", "description": "d"}
        ts, sig, raw = _sign(secret, body)
        r = self.client.post(
            "/v1/integration/tasks",
            content=raw,
            headers={
                "Content-Type": "application/json",
                "X-Karma-Timestamp": ts,
                "X-Karma-Signature": sig,
                "Idempotency-Key": "idem-create-1",
            },
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["ok"])

        body2 = {"foo": "bar"}
        ts2, sig2, raw2 = _sign(secret, body2)
        r2 = self.client.post(
            "/v1/integration/tasks/tr-smoke-1/order-snapshot",
            content=raw2,
            headers={
                "Content-Type": "application/json",
                "X-Karma-Timestamp": ts2,
                "X-Karma-Signature": sig2,
                "Idempotency-Key": "idem-snap-1",
            },
        )
        self.assertEqual(r2.status_code, 200, r2.text)
        self.assertEqual(r2.json()["task"]["state"], "SNAPSHOT_RECORDED")

        ts3, sig3, raw3 = _sign(secret, {})
        r3 = self.client.post(
            "/v1/integration/tasks/tr-smoke-1/buyer-lock-intent",
            content=raw3,
            headers={
                "Content-Type": "application/json",
                "X-Karma-Timestamp": ts3,
                "X-Karma-Signature": sig3,
                "Idempotency-Key": "idem-lock-1",
            },
        )
        self.assertEqual(r3.status_code, 200, r3.text)
        self.assertEqual(r3.json()["state"], "LOCK_PENDING")

        wh = {"trace_id": "tr-smoke-1", "event": "LOCK_CONFIRMED", "bill_id": 42, "tx_hash": "0xabc"}
        ts4, sig4, raw4 = _sign(secret, wh)
        r4 = self.client.post(
            "/v1/webhooks/chain",
            content=raw4,
            headers={"Content-Type": "application/json", "X-Karma-Timestamp": ts4, "X-Karma-Signature": sig4},
        )
        self.assertEqual(r4.status_code, 200, r4.text)
        self.assertEqual(r4.json()["state"], "EXECUTE_ALLOWED")


if __name__ == "__main__":
    unittest.main()
