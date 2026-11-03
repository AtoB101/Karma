"""End-to-end self-verification for the owner spending-grant approval flow.

Runs the exact handshake a real owner performs against any deployment:

    agent requests approval  ->  owner opens approval page  ->  owner reads terms
    ->  owner wallet-signs the canonical message  ->  owner submits approval
    ->  grant is created active  ->  public view flips to approved

Usage (local server):
    export KARMA_BASE_URL=http://127.0.0.1:8000
    export AGENT_API_KEY=karma_<agent_id>_<secret>
    export OWNER_PRIVATE_KEY=0x...
    python scripts/verify_approval_e2e.py

Precondition: the owner wallet must already be bound to an identity profile
(``IdentityProfileModel.bound_wallet_address``). If the approve step fails with
403 "bound", bind the wallet first, then rerun. The script exits non-zero on any
failed assertion and writes a JSON record to ``outputs/``.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from eth_account import Account
from eth_account.messages import encode_defunct

BASE_URL = os.environ.get("KARMA_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
AGENT_API_KEY = os.environ.get("AGENT_API_KEY", "")
OWNER_PRIVATE_KEY = os.environ.get("OWNER_PRIVATE_KEY", "")
AGENT_NAME = os.environ.get("AGENT_NAME", "OpenClaw Purchase Assistant")
TOTAL_LIMIT = float(os.environ.get("TOTAL_LIMIT", "100"))
PER_TX_LIMIT = float(os.environ.get("PER_TX_LIMIT", "10"))
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "outputs"))

RECORD: dict = {"base_url": BASE_URL, "started_at": None, "steps": []}


def _iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _record(name: str, ok: bool, detail: str) -> None:
    RECORD["steps"].append({"step": name, "ok": ok, "detail": detail, "at": _iso()})
    mark = "ok " if ok else "ERR"
    print(f"[{mark}] {name}: {detail}")


def _fail(msg: str) -> int:
    _record("result", False, msg)
    RECORD["finished_at"] = _iso()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / f"approval-e2e-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    out.write_text(json.dumps(RECORD, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nFAILED: {msg}\nRecord: {out}")
    return 1


def main() -> int:
    RECORD["started_at"] = _iso()
    if not AGENT_API_KEY:
        return _fail("AGENT_API_KEY is required (agent bootstrap key, returned once at connect)")
    if not OWNER_PRIVATE_KEY:
        return _fail("OWNER_PRIVATE_KEY is required (owner wallet that approves the grant)")
    owner = Account.from_key(OWNER_PRIVATE_KEY)
    wallet = owner.address
    headers = {"X-Karma-Api-Key": AGENT_API_KEY}

    with httpx.Client(base_url=BASE_URL, timeout=30.0) as client:
        # 1. Agent opens the approval request.
        try:
            r = client.post(
                "/v1/spending-grants/approval-request",
                json={
                    "agent_name": AGENT_NAME,
                    "currency": "USDC",
                    "total_limit": TOTAL_LIMIT,
                    "per_tx_limit": PER_TX_LIMIT,
                    "purpose_scope": ["escrow", "ecommerce"],
                },
                headers=headers,
            )
        except httpx.HTTPError as exc:
            return _fail(f"approval-request unreachable: {exc}")
        if r.status_code != 200:
            return _fail(f"approval-request returned {r.status_code}: {r.text[:300]}")
        ch = r.json()
        challenge_id = ch.get("challenge_id")
        confirmation_code = ch.get("confirmation_code")
        approval_uri = ch.get("approval_uri", "")
        if not challenge_id or not confirmation_code:
            return _fail(f"approval-request missing challenge_id/confirmation_code: {r.text[:300]}")
        _record("approval-request", True, f"challenge={challenge_id} uri={approval_uri}")

        # 2. Owner opens the approval page (public view must never leak the code).
        r = client.get(f"/v1/spending-grants/approval/{challenge_id}")
        if r.status_code != 200:
            return _fail(f"public view returned {r.status_code}: {r.text[:300]}")
        view = r.json()
        if "confirmation_code" in view:
            return _fail("public view leaked confirmation_code")
        if view.get("status") != "pending":
            return _fail(f"expected pending challenge, got {view.get('status')}")
        if float(view.get("total_limit", 0)) != TOTAL_LIMIT:
            return _fail("public view total_limit mismatch")
        _record("public-view", True, f"agent={view.get('agent_name')} total={view.get('total_limit')} per_tx={view.get('per_tx_limit')}")

        # 3. Owner fetches the exact message to sign.
        r = client.get(
            f"/v1/spending-grants/approval/{challenge_id}/sign-message",
            params={"wallet_address": wallet},
        )
        if r.status_code != 200:
            return _fail(f"sign-message returned {r.status_code}: {r.text[:300]}")
        message = r.json().get("message", "")
        if "Karma Spending Grant" not in message or wallet.lower() not in message.lower():
            return _fail("sign-message content mismatch")
        _record("sign-message", True, f"wallet={wallet}")

        # 4. Owner signs (EIP-191 personal_sign) and approves.
        signature = "0x" + Account.sign_message(
            encode_defunct(text=message), private_key=owner.key
        ).signature.hex()
        r = client.post(
            f"/v1/spending-grants/approval/{challenge_id}/approve",
            json={
                "confirmation_code": confirmation_code,
                "wallet_address": wallet,
                "wallet_signature": signature,
            },
        )
        if r.status_code != 200:
            return _fail(f"approve returned {r.status_code}: {r.text[:400]}")
        grant = r.json()
        if grant.get("status") != "active":
            return _fail(f"grant not active after approve: {grant}")
        _record("approve", True, f"grant={grant.get('grant_id')} status={grant.get('status')}")

        # 5. Public view now reflects the approved state.
        r = client.get(f"/v1/spending-grants/approval/{challenge_id}")
        if r.status_code != 200 or r.json().get("status") != "approved":
            return _fail(f"public view not approved after approve: {r.text[:300]}")
        _record("post-approve-view", True, "status=approved")

    RECORD["finished_at"] = _iso()
    RECORD["result"] = "passed"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / f"approval-e2e-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    out.write_text(json.dumps(RECORD, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nPASSED: full approval handshake verified ({len(RECORD['steps'])} steps).\nRecord: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
