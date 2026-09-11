#!/usr/bin/env python3
"""Gate for Phase 2 public integration contracts (console + wallet payloads).

Checks:
1) required docs exist
2) wallet signature example fields are complete
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
        ROOT / "docs/integration-guide.md",
        ROOT / "apps/console/index.html",
        ROOT / "karma-core/contracts/core/KarmaBilateral.sol",
    ]
    missing = [str(p.relative_to(ROOT)) for p in required if not p.exists()]
    if missing:
        fail(f"missing required Phase2 files: {', '.join(missing)}")
    ok("required Phase2 files exist")


def require_wallet_payload_fields() -> None:
    examples_doc = read_json(ROOT / "docs/wallet-signature-payload-examples.json")

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

    ok("wallet signature payload fields are complete")


def require_doc_references() -> None:
    integration = (ROOT / "docs/integration-guide.md").read_text(encoding="utf-8")

    must_contain = [
        "docs/testnet-integration-checklist.md",
        "docs/wallet-signature-payload-examples.json",
        "apps/console",
        "KarmaBilateral",
    ]
    for token in must_contain:
        if token not in integration:
            fail(f"required reference missing from docs/integration-guide.md: {token}")

    ok("Phase2 doc references are present")


def require_payload_version() -> None:
    examples_doc = read_json(ROOT / "docs/wallet-signature-payload-examples.json")
    payload_version = examples_doc.get("version")
    if not payload_version or not isinstance(payload_version, str):
        fail("wallet-signature-payload-examples.json must include string `version`")

    integration = (ROOT / "docs/integration-guide.md").read_text(encoding="utf-8")
    plain = f"Payload Version: {payload_version}"
    quoted = f"Payload Version: `{payload_version}`"
    if plain not in integration and quoted not in integration:
        fail(
            "integration-guide.md must declare payload version in the format "
            f"`Payload Version: {payload_version}`"
        )

    ok("payload version sync present")


def main() -> None:
    print("==> Phase2 public contract gate")
    require_paths()
    require_wallet_payload_fields()
    require_doc_references()
    require_payload_version()
    ok("phase2 public contract gate passed")


if __name__ == "__main__":
    main()
