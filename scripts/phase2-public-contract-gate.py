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


def require_version_sync_and_changelog() -> None:
    examples_doc = read_json(ROOT / "docs/wallet-signature-payload-examples.json")
    payload_version = examples_doc.get("version")
    if not payload_version or not isinstance(payload_version, str):
        fail("wallet-signature-payload-examples.json must include string `version`")

    integration = (ROOT / "docs/integration-guide.md").read_text(encoding="utf-8")
    changelog_path = ROOT / "docs/agent-service-guard-changelog.md"
    changelog = changelog_path.read_text(encoding="utf-8") if changelog_path.exists() else ""

    plain = f"Payload Version: {payload_version}"
    quoted = f"Payload Version: `{payload_version}`"
    if plain not in integration and quoted not in integration:
        fail(
            "integration-guide.md must declare payload version in the format "
            f"`Payload Version: {payload_version}`"
        )

    if payload_version not in changelog:
        fail(
            "agent-service-guard-changelog.md must contain an entry for current "
            f"payload version: {payload_version}"
        )

    expected_heading = f"## Payload Contract {payload_version}"
    if expected_heading not in changelog:
        fail(
            "agent-service-guard-changelog.md must include heading: "
            f"`{expected_heading}`"
        )

    marker = changelog.find(expected_heading)
    next_heading = changelog.find("\n## ", marker + len(expected_heading))
    section = changelog[marker: next_heading if next_heading != -1 else len(changelog)]
    if "Change Type: Breaking" not in section and "Change Type: Non-breaking" not in section:
        fail(
            "changelog entry must include `Change Type: Breaking` or "
            "`Change Type: Non-breaking` under current payload section"
        )

    ok("payload version sync and changelog entry are present")


def main() -> None:
    print("==> Phase2 public contract gate")
    require_paths()
    require_wallet_payload_fields()
    require_doc_references()
    require_version_sync_and_changelog()
    ok("phase2 public contract gate passed")


if __name__ == "__main__":
    main()
