#!/usr/bin/env python3
"""Gate for Phase 2 public integration contracts.

Checks:
1) required docs/templates exist
2) wallet signature example/template fields are complete
3) integration docs reference required artifacts/endpoints
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def fail(msg: str) -> None:
    print(f"ERR  {msg}")
    raise SystemExit(1)


def ok(msg: str) -> None:
    print(f"OK   {msg}")


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - fail-fast for CI
        fail(f"failed to parse JSON at {path}: {exc}")


def require_paths() -> None:
    required = [
        ROOT / "docs/testnet-integration-checklist.md",
        ROOT / "docs/wallet-signature-payload-examples.json",
        ROOT / "apps/agent-service-guard/templates/wallet-signature-payload-template.json",
        ROOT / "docs/integration-guide.md",
        ROOT / "apps/agent-service-guard/README.md",
    ]
    missing = [str(p.relative_to(ROOT)) for p in required if not p.exists()]
    if missing:
        fail(f"missing required Phase2 files: {', '.join(missing)}")
    ok("required Phase2 files exist")


def require_wallet_payload_fields() -> None:
    examples_doc = read_json(ROOT / "docs/wallet-signature-payload-examples.json")
    template_doc = read_json(ROOT / "apps/agent-service-guard/templates/wallet-signature-payload-template.json")

    examples = examples_doc.get("examples")
    if not isinstance(examples, dict):
        fail("wallet-signature-payload-examples.json must contain root `examples` object")

    for block in ["buyer_authorize_payment", "seller_delivery_attestation"]:
        if block not in examples:
            fail(f"wallet-signature-payload-examples.json missing examples.{block}")
        payload = examples[block]
        for field in ["domain", "types", "message"]:
            if field not in payload:
                fail(f"examples.{block} missing required field: {field}")

    order_context = template_doc.get("order_context", {})
    for field in ["order_id", "service_id", "chain_id", "amount", "currency"]:
        if field not in order_context:
            fail(f"wallet-signature-payload-template.json missing order_context.{field}")

    for block in ["buyer_authorization_payload", "seller_execution_payload"]:
        if block not in template_doc:
            fail(f"wallet-signature-payload-template.json missing {block}")
        payload = template_doc[block]
        for field in ["wallet", "action", "nonce", "deadline", "message_hash", "signature"]:
            if field not in payload:
                fail(f"wallet-signature-payload-template.json missing {block}.{field}")

    ok("wallet signature payload fields are complete")


def require_doc_references() -> None:
    integration = (ROOT / "docs/integration-guide.md").read_text(encoding="utf-8")
    app_readme = (ROOT / "apps/agent-service-guard/README.md").read_text(encoding="utf-8")

    must_contain = [
        "/risk/check",
        "/dispute/recommend-resolution",
        "/score/seller",
        "docs/testnet-integration-checklist.md",
        "docs/wallet-signature-payload-examples.json",
    ]
    for token in must_contain:
        if token not in integration and token not in app_readme:
            fail(f"required reference missing from docs: {token}")

    ok("Phase2 doc references are present")


def main() -> None:
    print("==> Phase2 public contract gate")
    require_paths()
    require_wallet_payload_fields()
    require_doc_references()
    ok("phase2 public contract gate passed")


if __name__ == "__main__":
    main()
