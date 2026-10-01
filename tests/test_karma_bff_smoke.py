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


def _sign_empty(secret: str) -> tuple[str, str]:
    ts = str(int(time.time()))
    sig = hmac.new(secret.encode("utf-8"), ts.encode("utf-8") + b"\n", hashlib.sha256).hexdigest()
    return ts, sig


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

        ts5, sig5 = _sign_empty(secret)
        r5 = self.client.get(
            "/v1/integration/tasks/tr-smoke-1/status",
            headers={"X-Karma-Timestamp": ts5, "X-Karma-Signature": sig5},
        )
        self.assertEqual(r5.status_code, 200, r5.text)
        j5 = r5.json()
        self.assertEqual(j5["trace_id"], "tr-smoke-1")
        self.assertEqual(j5["state"], "EXECUTE_ALLOWED")
        self.assertIn("buyer_lock_page_url", j5)
        self.assertIn("/public/lock/", j5["buyer_lock_page_url"])

        r6 = self.client.get("/public/status/tr-smoke-1")
        self.assertEqual(r6.status_code, 200, r6.text)
        j6 = r6.json()
        self.assertEqual(j6["receipt_count"], 0)
        self.assertIn("buyer_lock_page_url", j6)
        self.assertTrue(j6["buyer_lock_page_url"].endswith("/public/lock/tr-smoke-1"))

        r7 = self.client.get("/public/status/not%20valid!!")
        self.assertEqual(r7.status_code, 400)

        r8 = self.client.get("/public/lock/tr-smoke-1")
        self.assertEqual(r8.status_code, 200)
        self.assertIn(b"<!doctype html", r8.content.lower())
        self.assertIn(b"EXECUTE_ALLOWED", r8.content)
        self.assertIn(b"tr-smoke-1", r8.content)

    # -- terminal exits (failure / cancel) --------------------------------

    def _post(self, path: str, body: dict, idem: str):
        secret = os.environ["BFF_INTEGRATION_SECRET"]
        ts, sig, raw = _sign(secret, body)
        return self.client.post(
            path,
            content=raw,
            headers={
                "Content-Type": "application/json",
                "X-Karma-Timestamp": ts,
                "X-Karma-Signature": sig,
                "Idempotency-Key": idem,
            },
        )

    def _create(self, trace_id: str, task_id: str):
        r = self._post(
            "/v1/integration/tasks",
            {"trace_id": trace_id, "task_id": task_id, "agent_id": "ag", "runtime_id": "om", "description": "d"},
            f"idem-{trace_id}-create",
        )
        self.assertEqual(r.status_code, 200, r.text)

    def _drive_to_executing(self, trace_id: str, task_id: str) -> None:
        secret = os.environ["BFF_INTEGRATION_SECRET"]
        self._create(trace_id, task_id)
        r = self._post(f"/v1/integration/tasks/{trace_id}/order-snapshot", {"foo": "bar"}, f"idem-{trace_id}-snap")
        self.assertEqual(r.status_code, 200, r.text)
        r = self._post(f"/v1/integration/tasks/{trace_id}/buyer-lock-intent", {}, f"idem-{trace_id}-lock")
        self.assertEqual(r.status_code, 200, r.text)
        wh = {"trace_id": trace_id, "event": "LOCK_CONFIRMED", "bill_id": 7, "tx_hash": "0xabc"}
        ts, sig, raw = _sign(secret, wh)
        r = self.client.post(
            "/v1/webhooks/chain",
            content=raw,
            headers={"Content-Type": "application/json", "X-Karma-Timestamp": ts, "X-Karma-Signature": sig},
        )
        self.assertEqual(r.status_code, 200, r.text)
        r = self._post(
            f"/v1/integration/tasks/{trace_id}/receipts",
            {"receipt_id": f"{task_id}-r1", "step_index": 0, "tool_name": "t", "status": "success"},
            f"idem-{trace_id}-r1",
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["state"], "EXECUTING")

    def test_cancel_exit_is_legal_before_funds_move(self) -> None:
        self._create("tr-smoke-cancel", "task-cancel")
        r = self._post("/v1/integration/tasks/tr-smoke-cancel/cancel", {"reason": "buyer aborted"}, "idem-cancel-1")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["state"], "CANCELLED")

        # CANCELLED is final: the forward path is closed.
        r2 = self._post("/v1/integration/tasks/tr-smoke-cancel/order-snapshot", {}, "idem-cancel-snap")
        self.assertEqual(r2.status_code, 409, r2.text)

        # A replay with a fresh idempotency key reports the outcome, not a 409.
        r3 = self._post("/v1/integration/tasks/tr-smoke-cancel/cancel", {"reason": "buyer aborted"}, "idem-cancel-2")
        self.assertEqual(r3.status_code, 200, r3.text)
        self.assertTrue(r3.json()["already"])
        self.assertEqual(r3.json()["reason"], "buyer aborted")

    def test_cancel_is_refused_once_funds_are_locked(self) -> None:
        self._drive_to_executing("tr-smoke-nodead", "task-nodead")
        r = self._post("/v1/integration/tasks/tr-smoke-nodead/cancel", {"reason": "oops"}, "idem-nodead-cancel")
        self.assertEqual(r.status_code, 409, r.text)
        r2 = self.client.get("/public/status/tr-smoke-nodead")
        self.assertEqual(r2.status_code, 200, r2.text)
        self.assertEqual(r2.json()["state"], "EXECUTING")

    def test_fail_exit_is_reachable_and_terminal(self) -> None:
        self._drive_to_executing("tr-smoke-fail", "task-fail")
        r = self._post("/v1/integration/tasks/tr-smoke-fail/fail", {"reason": "tool crashed"}, "idem-fail-1")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["state"], "FAILED")

        # Terminal: no more execution evidence can be attached.
        r2 = self._post(
            "/v1/integration/tasks/tr-smoke-fail/receipts",
            {"receipt_id": "task-fail-r2", "step_index": 1, "tool_name": "t", "status": "success"},
            "idem-fail-r2",
        )
        self.assertEqual(r2.status_code, 409, r2.text)

        # Replay keeps the recorded reason.
        r3 = self._post("/v1/integration/tasks/tr-smoke-fail/fail", {"reason": "tool crashed"}, "idem-fail-2")
        self.assertEqual(r3.status_code, 200, r3.text)
        self.assertTrue(r3.json()["already"])
        self.assertEqual(r3.json()["reason"], "tool crashed")

        # The reason is readable from the public status page.
        r4 = self.client.get("/public/status/tr-smoke-fail")
        self.assertEqual(r4.json()["state"], "FAILED")

    def test_terminal_exits_require_a_reason(self) -> None:
        self._create("tr-smoke-noreason", "task-noreason")
        for path in ("fail", "cancel"):
            r = self._post(f"/v1/integration/tasks/tr-smoke-noreason/{path}", {"reason": "   "}, f"idem-nr-{path}")
            self.assertEqual(r.status_code, 400, (path, r.text))

    def test_chain_event_for_a_closed_task_raises_an_alert(self) -> None:
        secret = os.environ["BFF_INTEGRATION_SECRET"]
        self._create("tr-smoke-alert", "task-alert")
        r = self._post("/v1/integration/tasks/tr-smoke-alert/cancel", {"reason": "buyer aborted"}, "idem-alert-cancel")
        self.assertEqual(r.status_code, 200, r.text)
        wh = {"trace_id": "tr-smoke-alert", "event": "LOCK_CONFIRMED", "bill_id": 9, "tx_hash": "0xdead"}
        ts, sig, raw = _sign(secret, wh)
        r2 = self.client.post(
            "/v1/webhooks/chain",
            content=raw,
            headers={"Content-Type": "application/json", "X-Karma-Timestamp": ts, "X-Karma-Signature": sig},
        )
        self.assertEqual(r2.status_code, 200, r2.text)
        self.assertTrue(r2.json()["ignored"])
        self.assertTrue(r2.json()["alert"])
        # It must not resurrect the trace.
        r3 = self.client.get("/public/status/tr-smoke-alert")
        self.assertEqual(r3.json()["state"], "CANCELLED")


class BffStateGraphTests(unittest.TestCase):
    """Graph invariants -- pure, so they run even where FastAPI is absent."""

    def test_every_non_terminal_state_has_a_failure_exit(self) -> None:
        from apps.karma_bff.app import state_machine

        for state, edges in state_machine.VALID_TRANSITIONS.items():
            if state in state_machine.TERMINAL_STATES:
                continue
            self.assertIn(
                state_machine.FAILURE_STATE,
                edges,
                f"{state} has no way out when the orchestrator gives up",
            )

    def test_terminal_states_have_no_out_edges(self) -> None:
        from apps.karma_bff.app import state_machine

        for state in state_machine.TERMINAL_STATES:
            self.assertEqual(state_machine.VALID_TRANSITIONS[state], set(), state)

    def test_terminal_set_matches_the_empty_edge_rows(self) -> None:
        from apps.karma_bff.app import state_machine

        empty = {s for s, e in state_machine.VALID_TRANSITIONS.items() if not e}
        self.assertEqual(empty, set(state_machine.TERMINAL_STATES))

    def test_cancel_is_only_reachable_before_funds_are_locked(self) -> None:
        from apps.karma_bff.app import state_machine

        cancel = state_machine.CANCEL_STATE
        for state in ("PLANNED", "SNAPSHOT_RECORDED", "LOCK_PENDING"):
            self.assertTrue(state_machine.can_transition(state, cancel), state)
        for state in (
            "LOCKED",
            state_machine.EXECUTE_STATE,
            "EXECUTING",
            "EVIDENCE_BUILT",
            "AWAIT_ONCHAIN",
        ):
            self.assertFalse(state_machine.can_transition(state, cancel), state)

    def test_is_terminal_agrees_with_the_table(self) -> None:
        from apps.karma_bff.app import state_machine

        for state in state_machine.VALID_TRANSITIONS:
            self.assertEqual(
                state_machine.is_terminal(state),
                not state_machine.VALID_TRANSITIONS[state],
                state,
            )


if __name__ == "__main__":
    unittest.main()
