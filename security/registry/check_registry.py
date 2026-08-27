#!/usr/bin/env python3
"""Fail CI if a registered financial function is missing from its contract source."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
YAML = ROOT / "security" / "registry" / "financial_functions.yaml"
CONTRACT_DIR = ROOT / "karma-core" / "contracts" / "core"

CONTRACT_FILES = {
    "KarmaBilateral": CONTRACT_DIR / "KarmaBilateral.sol",
    "KarmaAttestationGateway": CONTRACT_DIR / "KarmaAttestationGateway.sol",
    "CircuitBreaker": CONTRACT_DIR / "CircuitBreaker.sol",
}

ENTRY_RE = re.compile(
    r"- contract:\s*(\S+)\s*\n\s*function:\s*(\S+)",
    re.MULTILINE,
)


def main() -> int:
    text = YAML.read_text(encoding="utf-8")
    missing: list[str] = []
    sources: dict[str, str] = {}
    for name, path in CONTRACT_FILES.items():
        if not path.exists():
            print(f"ERR  missing contract file {path}", file=sys.stderr)
            return 1
        sources[name] = path.read_text(encoding="utf-8")

    for contract, fn in ENTRY_RE.findall(text):
        src = sources.get(contract)
        if src is None:
            continue
        needle = f"function {fn}("
        if needle not in src:
            missing.append(f"{contract}.{fn}")

    if missing:
        print("ERR  registry functions missing from Solidity:", file=sys.stderr)
        for item in missing:
            print(f"  - {item}", file=sys.stderr)
        return 1
    print("OK   financial function registry matches contract sources")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
