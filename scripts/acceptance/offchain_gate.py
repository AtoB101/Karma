#!/usr/bin/env python3
"""Cross-platform off-chain audit gate (no bash, no live RPC).

Equivalent to scripts/acceptance/full_chain_audit_gate.sh for machines without
bash (Windows/macOS/Linux). Runs the reverse-rule audit, Phase 1-3 gates,
security regressions, public acceptance suite, production prelaunch settings,
manifest validation, and Console last-mile static checks.

Usage:
  python scripts/acceptance/offchain_gate.py [--skip-benchmark] [--skip-console]
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _run(cmd: list[str], *, label: str) -> bool:
    print(f"\n== {label} ==")
    print("  $ " + " ".join(cmd))
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        print(f"FAIL  {label} (exit {result.returncode})")
        return False
    print(f"OK    {label}")
    return True


def _pytest(*args: str, label: str) -> bool:
    return _run([sys.executable, "-m", "pytest", "-q", "--tb=line", *args], label=label)


def step_reverse_rule() -> bool:
    return _run(
        [sys.executable, "scripts/acceptance/reverse_rule_audit.py"],
        label="Reverse-rule static audit",
    )


def step_phase1() -> bool:
    return _pytest(
        "tests/unit/test_trade_launch_eip712.py",
        "tests/unit/test_voucher_buyer_commitment.py",
        "tests/unit/test_trade_launch_security.py",
        "tests/unit/test_spending_policy.py",
        "tests/unit/test_openclaw_delivery_signature_relax.py",
        "tests/integration/test_trade_launch_eip712_launch.py",
        "packages/karma-openclaw/tests/test_dev_delivery_signatures.py",
        label="Phase 1 Open Wallet gate",
    )


def step_phase2(skip_benchmark: bool) -> bool:
    if not _pytest(
        "tests/unit/test_x402_client.py",
        "tests/unit/test_x402_security.py",
        "tests/unit/test_x402_env_signing_executor.py",
        "tests/integration/test_x402_pay_and_fetch.py",
        label="Phase 2 x402 gate",
    ):
        return False
    if skip_benchmark:
        print("\nSKIP  x402 evidence benchmark (--skip-benchmark)")
        return True
    return _run(
        [sys.executable, "scripts/benchmark_x402_evidence_integrity.py", "--iterations", "5"],
        label="Phase 2 x402 evidence benchmark",
    )


def step_phase3() -> bool:
    return _pytest(
        "tests/unit/test_ap2_adapter.py",
        "tests/unit/test_evidence_export.py",
        "tests/unit/test_human_not_present_policy.py",
        "tests/integration/test_phase3_payment_intent.py",
        label="Phase 3 AP2 gate",
    )


def step_security_regressions() -> bool:
    return _pytest(
        "tests/unit/test_openclaw_webhook_retry.py",
        "tests/integration/test_payment_intent_expire_admin.py",
        "tests/unit/test_sentinel_nonblocking_regressions.py",
        "tests/unit/test_security_attack_mitigations.py",
        "tests/unit/test_level2_attack_mitigations.py",
        "tests/unit/test_trade_launch_security.py",
        "tests/unit/test_settlement_cycle_guard.py",
        "tests/unit/test_receipt_chronology.py",
        "tests/integration/test_triangle_settlement_cycle.py",
        "tests/unit/test_ap2_security.py",
        label="Security attack regressions",
    )


def step_public_acceptance() -> bool:
    return _pytest(
        "tests/",
        "packages/karma-openmanus/tests",
        "packages/karma-openclaw/tests",
        label="Public acceptance (monorepo + packages)",
    )


def step_production_prelaunch() -> bool:
    print("\n== Production prelaunch settings ==")
    defaults = {
        "AUTH_ENFORCE_PROTECTED_ROUTES": "true",
        "AUTH_ALLOW_DEV_KEY_FALLBACK": "false",
        "RATE_LIMIT_REDIS_FAIL_CLOSED": "true",
        "RECEIPT_REQUIRE_SIGNATURE": "true",
        "LEDGER_REQUIRE_PARTY_ACTOR": "true",
        "SETTLEMENT_REQUIRE_PARTY_ACTOR": "true",
        "RUNTIME_REQUIRE_SAVED_AUTOMATION_POLICY": "true",
        "RUNTIME_REQUIRE_TASK_AUTOMATION_READINESS": "true",
        "RUNTIME_REQUIRE_HANDOFF_ATTESTATION": "true",
        "RUNTIME_REQUIRE_WALLET_IDENTITY_BINDING": "true",
        "RUNTIME_DAILY_SPEND_PERSIST": "true",
        "TRADE_LAUNCH_REQUIRE_EIP712": "true",
        "KARMA_SIGNING_BACKEND": "client_only",
        "X402_PAYMENT_BACKEND": "sepolia",
        "ARBITRATOR_ACTOR_IDS": "gate-arbitrator",
        "CHAIN_ALLOW_HOT_WALLET_PAYER": "false",
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)
    os.environ.setdefault("APP_SECRET_KEY", "gate-check-secret-min-32-chars-long!!")
    os.environ.setdefault("AUTH_API_KEYS", "gate-agent:gate-secret-minimum")
    os.environ.setdefault("MINIO_ACCESS_KEY", "gate-check-minio-access")
    os.environ.setdefault("MINIO_SECRET_KEY", "gate-check-minio-secret")

    if not _pytest(
        "tests/unit/test_production_receipt_signature.py",
        "tests/unit/test_production_settings_gates.py",
        label="Production settings unit tests",
    ):
        return False

    from config.settings import Settings

    try:
        Settings()
    except ValueError as exc:
        print(f"FAIL  production settings rejected: {exc}")
        return False
    print("OK    Settings() accepts production configuration")
    return True


def step_manifest() -> bool:
    return _run(
        [sys.executable, "scripts/verify_manifest.py"],
        label="Testnet manifest sample",
    )


def _check_file(path: Path) -> bool:
    if not path.is_file():
        print(f"MISSING {path}")
        return False
    return True


def _check_page_hooks(skip_console: bool) -> bool:
    console = ROOT / "apps" / "console"
    required = [
        "scripts/console-bootstrap.js",
        "scripts/console-connect.js",
        "scripts/console-actions.js",
        "scripts/karma-public-api.js",
        "pages/payments/index.html",
        "pages/receiving/index.html",
        "pages/trade/index.html",
    ]
    ok = all(_check_file(console / rel) for rel in required)
    for rel in [
        "index.html",
        "pages/payments/index.html",
        "pages/receiving/index.html",
        "pages/disputes/index.html",
        "pages/evidence/index.html",
        "pages/trade/index.html",
    ]:
        path = console / rel
        if path.is_file() and "console-bootstrap.js" not in path.read_text(encoding="utf-8"):
            print(f"Page missing console-bootstrap.js: {path}")
            ok = False
    api_js = console / "scripts" / "karma-public-api.js"
    if api_js.is_file() and "settlementLock" not in api_js.read_text(encoding="utf-8"):
        print(f"karma-public-api.js missing settlementLock: {api_js}")
        ok = False
    for rel in ("pages/payments/index.html", "pages/receiving/index.html"):
        path = console / rel
        if path.is_file() and "data-console-action" not in path.read_text(encoding="utf-8"):
            print(f"Page missing data-console-action: {path}")
            ok = False
    return ok


def step_console(skip_console: bool) -> bool:
    if skip_console:
        print("\nSKIP  Console last-mile (--skip-console)")
        return True
    if not _check_page_hooks(skip_console):
        return False
    if not _pytest(
        "tests/unit/test_console_last_mile.py",
        "tests/unit/test_console_live_write_smoke.py",
        label="Console last-mile tests",
    ):
        return False
    node = shutil.which("node")
    if node:
        console = ROOT / "apps" / "console"
        for js in (
            "console-bootstrap.js",
            "console-connect.js",
            "console-actions.js",
            "karma-public-api.js",
        ):
            if not _run([node, "--check", str(console / "scripts" / js)], label=f"node --check {js}"):
                return False
    else:
        print("SKIP  node --check (node not found)")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-benchmark", action="store_true", help="skip x402 benchmark")
    parser.add_argument("--skip-console", action="store_true", help="skip Console last-mile checks")
    parser.add_argument("--only", help="run only the given steps (comma-separated keys or 1-9 numbers)")
    parser.add_argument("--list", action="store_true", help="list step keys and exit")
    args = parser.parse_args()

    steps = [
        ("reverse", "[1/9] Reverse-rule static audit", step_reverse_rule),
        ("phase1", "[2/9] Phase 1 Open Wallet gate", step_phase1),
        ("phase2", "[3/9] Phase 2 x402 gate", lambda: step_phase2(args.skip_benchmark)),
        ("phase3", "[4/9] Phase 3 AP2 gate", step_phase3),
        ("security", "[5/9] Security attack regressions", step_security_regressions),
        ("public", "[6/9] Public acceptance", step_public_acceptance),
        ("prelaunch", "[7/9] Production prelaunch settings", step_production_prelaunch),
        ("manifest", "[8/9] Testnet manifest sample", step_manifest),
        ("console", "[9/9] Console last-mile", lambda: step_console(args.skip_console)),
    ]

    if args.list:
        for idx, (key, name, _) in enumerate(steps, start=1):
            print(f"{idx}  {key:<10} {name}")
        return 0

    if args.only:
        tokens = [tok.strip().lower() for tok in args.only.split(",") if tok.strip()]
        selected: list[tuple[str, str, object]] = []
        for idx, (key, name, func) in enumerate(steps, start=1):
            if key in tokens or str(idx) in tokens or any(tok and tok in name.lower() for tok in tokens):
                selected.append((key, name, func))
        if not selected:
            print(f"FAIL  no steps match --only {args.only!r}; use --list to see keys")
            return 1
        steps = selected

    print("=" * 48)
    print(" Karma off-chain audit gate (cross-platform)")
    print("=" * 48)
    for _, name, func in steps:
        print(f"\n--- {name} ---")
        if not func():
            print(f"\nOFF-CHAIN GATE: FAIL at {name}")
            return 1
    print("\nOFF-CHAIN GATE: PASS")
    print(" Next: python scripts/acceptance/testnet gate requires live API + testnet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
