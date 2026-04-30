#!/usr/bin/env python3
import argparse
import datetime as dt
import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

API_VERSION = "karma-api-v1"


def normalize_path(raw_path: str) -> str:
    # Canonicalize API paths so /v1/* and /api/v1/* are both accepted.
    if raw_path.startswith("/api/v1/"):
        return raw_path[len("/api") :]
    if raw_path == "/api/v1":
        return "/v1"
    return raw_path


@dataclass
class AppState:
    api_token: str
    payment_intents: dict
    idempotency_index: dict
    evidence_objects: dict
    risk_alerts: list


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_dumps(data) -> bytes:
    return (json.dumps(data, ensure_ascii=True) + "\n").encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    state: AppState = None

    def _request_id(self) -> str:
        return self.headers.get("X-Request-Id") or str(uuid.uuid4())

    def _send_json(self, status: int, payload: dict):
        body = json_dumps(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, code: str, message: str):
        self._send_json(
            status,
            {
                "error": {
                    "code": code,
                    "message": message,
                    "requestId": self._request_id(),
                }
            },
        )

    def _auth_ok(self) -> bool:
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return False
        token = auth.split(" ", 1)[1].strip()
        return token == self.state.api_token

    def _read_json_body(self):
        content_len = int(self.headers.get("Content-Length", "0"))
        if content_len <= 0:
            return {}
        raw = self.rfile.read(content_len)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return None

    def _require_auth(self) -> bool:
        if normalize_path(self.path).startswith("/v1/health"):
            return True
        if not self._auth_ok():
            self._error(401, "AUTH_UNAUTHORIZED", "Missing or invalid bearer token")
            return False
        return True

    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        if not self._require_auth():
            return

        parsed = urlparse(self.path)
        path = normalize_path(parsed.path)

        if path == "/v1/health":
            self._send_json(200, {"status": "ok", "version": API_VERSION})
            return

        if path.startswith("/v1/payment-intents/"):
            intent_id = path.split("/")[-1]
            obj = self.state.payment_intents.get(intent_id)
            if not obj:
                self._error(404, "PAYMENT_INTENT_NOT_FOUND", "payment intent not found")
                return
            self._send_json(200, obj)
            return

        if path.startswith("/v1/evidence/") and not path.endswith("/verify"):
            evidence_id = path.split("/")[-1]
            obj = self.state.evidence_objects.get(evidence_id)
            if not obj:
                self._error(404, "EVIDENCE_NOT_FOUND", "evidence not found")
                return
            self._send_json(200, obj)
            return

        if path == "/v1/risk/alerts":
            qs = parse_qs(parsed.query)
            since = qs.get("since", [None])[0]
            severity = qs.get("severity", [None])[0]

            alerts = self.state.risk_alerts
            if since:
                alerts = [a for a in alerts if a.get("createdAt", "") >= since]
            if severity:
                alerts = [a for a in alerts if a.get("severity") == severity]
            self._send_json(200, {"alerts": alerts})
            return

        self._error(404, "ROUTE_NOT_FOUND", "route not found")

    def do_POST(self):
        if not self._require_auth():
            return

        parsed = urlparse(self.path)
        path = normalize_path(parsed.path)
        body = self._read_json_body()
        if body is None:
            self._error(400, "INVALID_JSON", "request body is not valid JSON")
            return

        if path == "/v1/payment-intents":
            idem = self.headers.get("Idempotency-Key", "").strip()
            if len(idem) < 8:
                self._error(400, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key must be at least 8 chars")
                return

            required = ["merchantRef", "payer", "payee", "token", "amount", "chainId", "policyId", "expiresAt"]
            missing = [k for k in required if k not in body]
            if missing:
                self._error(400, "INVALID_REQUEST", f"missing fields: {','.join(missing)}")
                return
            try:
                int(str(body["amount"]))
                int(body["chainId"])
            except Exception:
                self._error(400, "INVALID_REQUEST", "amount/chainId must be numeric")
                return

            if idem in self.state.idempotency_index:
                existing_id = self.state.idempotency_index[idem]
                self._send_json(200, self.state.payment_intents[existing_id])
                return

            now = now_iso()
            intent_id = f"pi_{uuid.uuid4().hex[:16]}"
            intent = {
                "intentId": intent_id,
                "merchantRef": body["merchantRef"],
                "status": "created",
                "createdAt": now,
                "updatedAt": now,
                "payer": body["payer"],
                "payee": body["payee"],
                "token": body["token"],
                "amount": str(body["amount"]),
                "chainId": int(body["chainId"]),
                "policyId": body["policyId"],
                "expiresAt": body["expiresAt"],
            }
            self.state.payment_intents[intent_id] = intent
            self.state.idempotency_index[idem] = intent_id

            payload = {
                "intentId": intent_id,
                "schemaVersion": "evidence-v1",
                "evidenceVersion": "evidence-v1",
                "payload": {
                    "kind": "payment_intent_created",
                    "intent": intent,
                },
            }
            digest = sha256_hex(json.dumps(payload["payload"], sort_keys=True, separators=(",", ":")).encode("utf-8"))
            payload["digestSha256"] = digest
            self.state.evidence_objects[intent_id] = payload

            self.state.risk_alerts.append(
                {
                    "id": f"ra_{uuid.uuid4().hex[:12]}",
                    "createdAt": now,
                    "severity": "warning",
                    "code": "payment_intent_created",
                    "title": "Payment intent created",
                    "detail": f"intent {intent_id} created with policy {intent['policyId']}",
                    "source": "api.payment_intents",
                }
            )

            self._send_json(201, intent)
            return

        if path.startswith("/v1/evidence/") and path.endswith("/verify"):
            evidence_id = path.split("/")[-2]
            obj = self.state.evidence_objects.get(evidence_id)
            if not obj:
                self._error(404, "EVIDENCE_NOT_FOUND", "evidence not found")
                return

            expected_digest = body.get("expectedDigestSha256")
            expected_schema = body.get("expectedSchemaVersion")
            if not expected_digest or not expected_schema:
                self._error(400, "INVALID_REQUEST", "expectedDigestSha256 and expectedSchemaVersion are required")
                return

            digest_match = expected_digest == obj.get("digestSha256")
            schema_match = expected_schema == obj.get("schemaVersion")
            verified = digest_match and schema_match
            self._send_json(
                200,
                {
                    "evidenceId": evidence_id,
                    "verified": verified,
                    "checks": {
                        "digestMatch": digest_match,
                        "schemaVersionMatch": schema_match,
                    },
                },
            )
            return

        self._error(404, "ROUTE_NOT_FOUND", "route not found")


def load_alerts_from_guardian(results_dir: str):
    path = os.path.join(results_dir, "agent-safety-alarm-latest.json")
    if not os.path.isfile(path):
        return []
    try:
        data = json.loads(open(path, "r", encoding="utf-8").read())
        alarms = []
        for idx, row in enumerate(data.get("alarms") or []):
            alarms.append(
                {
                    "id": f"ga_{idx}_{uuid.uuid4().hex[:8]}",
                    "createdAt": data.get("generatedAt") or now_iso(),
                    "severity": row.get("severity", "warning"),
                    "code": row.get("ruleId") or row.get("kind") or "guardian_alarm",
                    "title": row.get("title") or "Guardian alarm",
                    "detail": row.get("detail") or "",
                    "source": "guardian.alarm",
                }
            )
        return alarms
    except Exception:
        return []


def main():
    parser = argparse.ArgumentParser(description="Karma API server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8811)
    parser.add_argument("--token", default=os.getenv("KARMA_API_TOKEN", "dev-token"))
    parser.add_argument("--results-dir", default="results")
    args = parser.parse_args()

    seed_alerts = load_alerts_from_guardian(args.results_dir)
    if not seed_alerts:
        seed_alerts = [
            {
                "id": f"ra_seed_{uuid.uuid4().hex[:8]}",
                "createdAt": now_iso(),
                "severity": "medium",
                "code": "guardian_not_initialized",
                "title": "Guardian artifacts not found",
                "detail": "Run make agent-safety-guardian to populate risk alert stream.",
                "source": "api.bootstrap",
            }
        ]

    state = AppState(
        api_token=args.token,
        payment_intents={},
        idempotency_index={},
        evidence_objects={},
        risk_alerts=seed_alerts,
    )

    Handler.state = state
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Karma API server running at http://{args.host}:{args.port} (token={args.token})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
