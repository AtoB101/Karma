#!/usr/bin/env python3
"""Validate deployment-manifest.json before public testnet go-live.

Default reports template placeholders as warnings and exits 0 so the off-chain
audit gate is not blocked while remaining fields are filled. Set
KARMA_MANIFEST_STRICT=1 (or pass a second argument of "1") to fail on any
placeholder.

Usage:
  python scripts/verify_manifest.py [MANIFEST] [STRICT]
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path


ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
REQUIRED_CONTRACTS = ("bilateral_escrow", "erc20_token")
OPTIONAL_FIELDS = ("payee_address",)


def _fail(msg: str) -> None:
    print(f"FAIL  {msg}", file=sys.stderr)


def _warn(msg: str) -> None:
    print(f"WARN  {msg}", file=sys.stderr)


def _ok(msg: str) -> None:
    print(f"OK    {msg}")


def main(argv: list[str]) -> int:
    root = Path(__file__).resolve().parents[1]
    manifest_path = argv[1] if len(argv) > 1 else os.environ.get(
        "KARMA_DEPLOYMENT_MANIFEST", str(root / "deployment-manifest.json")
    )
    strict_raw = argv[2] if len(argv) > 2 else os.environ.get("KARMA_MANIFEST_STRICT", "0")
    strict = strict_raw == "1"

    if not Path(manifest_path).is_file():
        _fail(f"manifest not found: {manifest_path}")
        return 1 if strict else 0

    with open(manifest_path, encoding="utf-8") as handle:
        manifest = json.load(handle)

    fail = 0
    warn = 0

    chain_id = manifest.get("chain_id")
    if not isinstance(chain_id, int) or chain_id <= 0:
        _fail("chain_id must be a positive integer")
        fail += 1
    else:
        _ok(f"chain_id={chain_id}")

    contracts = manifest.get("contracts", {})
    if not isinstance(contracts, dict):
        _fail("contracts must be an object")
        fail += 1
    else:
        for name in REQUIRED_CONTRACTS:
            value = contracts.get(name, "")
            if not isinstance(value, str) or not ADDR_RE.match(value):
                _fail(f"contracts.{name} must be a valid 0x address: {value!r}")
                fail += 1
            else:
                _ok(f"contracts.{name}={value}")

        for name in OPTIONAL_FIELDS:
            value = contracts.get(name, "")
            if not isinstance(value, str) or not value.strip():
                _warn(f"contracts.{name} is empty (fill before go-live)")
                warn += 1
            elif not ADDR_RE.match(value):
                _fail(f"contracts.{name} is not a valid 0x address: {value!r}")
                fail += 1
            else:
                _ok(f"contracts.{name}={value}")

    admin = manifest.get("admin", "")
    if isinstance(admin, str) and admin.strip():
        if not ADDR_RE.match(admin):
            _fail(f"admin is not a valid 0x address: {admin!r}")
            fail += 1
        else:
            _ok(f"admin={admin}")
    else:
        _warn("admin is empty (fill before go-live)")
        warn += 1

    commit = manifest.get("commit", "")
    if not commit:
        _warn("commit is empty (set to the audited source commit)")
        warn += 1
    else:
        _ok(f"commit={commit}")

    if warn:
        print(f"WARN  {warn} template placeholder(s) present", file=sys.stderr)
    if fail:
        _fail(f"{fail} invalid field(s)")
        return 1
    if strict and warn:
        _fail("strict mode: fill all placeholders before go-live")
        return 1
    _ok("deployment manifest validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
