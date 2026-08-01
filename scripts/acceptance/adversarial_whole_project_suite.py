#!/usr/bin/env python3
"""
Whole-project adversarial suite — not limited to P1–P8 commerce plates.

Runs static security baselines, reverse-rule audit, platform WP-* adversarial
tests, existing KSA/KSA2/TL/X402/AP2 attack regressions, plate adversarial pack,
trusted-agent structural stress, and (optionally) the off-chain full_chain_audit_gate.

Env:
  KARMA_WHOLE_PROJECT_SKIP_FULL_GATE=1  skip scripts/acceptance/full_chain_audit_gate.sh
  KARMA_LIVE_ADVERSARIAL=1             also run live attack scripts if API is up
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "docs" / "ADVERSARIAL_WHOLE_PROJECT_AUDIT_V1.md"


def _run(cmd: list[str], *, label: str, env: dict | None = None) -> dict:
    t0 = time.time()
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
    )
    return {
        "label": label,
        "cmd": " ".join(cmd),
        "returncode": proc.returncode,
        "elapsed_s": round(time.time() - t0, 2),
        "stdout_tail": (proc.stdout or "")[-5000:],
        "stderr_tail": (proc.stderr or "")[-3000:],
        "ok": proc.returncode == 0,
    }


def _api_up(url: str) -> bool:
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/health", timeout=2) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, TimeoutError, ValueError):
        return False


def main() -> int:
    suites: list[dict] = []

    # A) Static baselines
    suites.append(
        _run(["bash", "scripts/security-baseline-guard.sh"], label="A1 security-baseline-guard")
    )
    suites.append(_run(["bash", "scripts/ci-proof-gates.sh"], label="A2 ci-proof-gates"))
    if (ROOT / "scripts/agent-guard-security-gate.py").is_file():
        suites.append(
            _run(
                [sys.executable, "scripts/agent-guard-security-gate.py"],
                label="A3 agent-guard-security-gate",
            )
        )
    suites.append(
        _run(
            [sys.executable, "scripts/acceptance/reverse_rule_audit.py"],
            label="A4 reverse_rule_audit",
        )
    )

    # B) Whole-project WP-* adversarial + platform security packs
    suites.append(
        _run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "tests/unit/test_adversarial_whole_project.py",
                "--tb=line",
            ],
            label="B1 adversarial_whole_project (WP-*)",
        )
    )
    suites.append(
        _run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "tests/unit/test_auth_security.py",
                "tests/unit/test_security_attack_mitigations.py",
                "tests/unit/test_level2_attack_mitigations.py",
                "tests/unit/test_trade_launch_security.py",
                "tests/unit/test_settlement_cycle_guard.py",
                "tests/unit/test_receipt_chronology.py",
                "tests/unit/test_x402_security.py",
                "tests/unit/test_ap2_security.py",
                "tests/unit/test_path_param_safety.py",
                "tests/unit/test_openclaw_webhook.py",
                "tests/unit/test_openclaw_webhook_retry.py",
                "tests/unit/test_runtime_gateway.py",
                "tests/unit/test_runtime_daily_spend.py",
                "tests/unit/test_runtime_automation_readiness_gate.py",
                "tests/unit/test_production_receipt_signature.py",
                "--tb=line",
            ],
            label="B2 platform KSA/KSA2/TL/X402/AP2/runtime packs",
        )
    )

    # C) Commerce plates (subset of whole project, still included)
    suites.append(
        _run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "tests/unit/test_adversarial_p1_p8.py",
                "--tb=line",
            ],
            label="C1 adversarial_p1_p8 (commerce plates)",
        )
    )

    # D) Structural stress (no live API)
    if (ROOT / "scripts/stress_trusted_agent_runtime.py").is_file():
        suites.append(
            _run(
                [
                    sys.executable,
                    "scripts/stress_trusted_agent_runtime.py",
                    "--agents",
                    "30",
                ],
                label="D1 stress_trusted_agent_runtime --agents 30",
            )
        )

    # E) Full off-chain audit gate (phase1–3 + public acceptance) — default ON
    if os.environ.get("KARMA_WHOLE_PROJECT_SKIP_FULL_GATE", "").strip() not in {
        "1",
        "true",
        "yes",
    }:
        suites.append(
            _run(
                ["bash", "scripts/acceptance/full_chain_audit_gate.sh"],
                label="E1 full_chain_audit_gate (off-chain)",
            )
        )

    # F) Optional live API attacks
    live = os.environ.get("KARMA_LIVE_ADVERSARIAL", "").strip() in {"1", "true", "yes"}
    runtime = os.environ.get("KARMA_RUNTIME_URL", "http://127.0.0.1:8000")
    if live:
        if _api_up(runtime):
            for script, label in (
                ("scripts/stress_attack_test.py", "F1 live stress_attack_test"),
                ("scripts/attack_simulation.py", "F2 live attack_simulation"),
            ):
                if (ROOT / script).is_file():
                    suites.append(
                        _run(
                            [sys.executable, script],
                            label=label,
                            env={"KARMA_RUNTIME_URL": runtime},
                        )
                    )
        else:
            suites.append(
                {
                    "label": "F0 live API unavailable (skipped)",
                    "cmd": f"GET {runtime}/health",
                    "returncode": 0,
                    "elapsed_s": 0,
                    "stdout_tail": f"API not up at {runtime}; live attacks skipped",
                    "stderr_tail": "",
                    "ok": True,
                }
            )

    failed = [s for s in suites if not s["ok"]]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        "# Adversarial Whole-Project Audit V1",
        "",
        f"Generated: `{now}`",
        "",
        "## Verdict",
        "",
        (
            "**HARD FAIL** — one or more whole-project gates failed."
            if failed
            else "**HARD PASS** — whole-project static + WP adversarial + platform security packs green."
        ),
        "",
        "## Scope (entire repo, not only P1–P8)",
        "",
        "Surfaces covered:",
        "",
        "- Auth / JWT / API keys / admin whitelist / security always-auth",
        "- Receipts, settlement cycle guards, capacity release, runtime keys/spend",
        "- x402 URL SSRF + budget, AP2 adapter surface, OpenClaw webhook signing",
        "- Path traversal, NUL/RLO injection, CORS default, production secret validator",
        "- Router mount integrity (security/admin/settlement/receipts/x402/trade/runtime/…)",
        "- Commerce plates P1–P8 adversarial pack (included as a subset)",
        "- Public security baseline / proof gates / reverse-rule audit",
        "- Trusted-agent structural stress",
        "",
        "## Suite results",
        "",
        "| Suite | OK | Seconds |",
        "|-------|----|---------|",
    ]
    for s in suites:
        lines.append(
            f"| {s['label']} | {'PASS' if s['ok'] else 'FAIL'} | {s['elapsed_s']} |"
        )

    lines.extend(
        [
            "",
            "## How to re-run",
            "",
            "```bash",
            "python3 scripts/acceptance/adversarial_whole_project_suite.py",
            "# faster: KARMA_WHOLE_PROJECT_SKIP_FULL_GATE=1 python3 scripts/acceptance/adversarial_whole_project_suite.py",
            "# live:   KARMA_LIVE_ADVERSARIAL=1 KARMA_RUNTIME_URL=http://127.0.0.1:8000 \\",
            "#         python3 scripts/acceptance/adversarial_whole_project_suite.py",
            "```",
            "",
            "## Residual risk (honest)",
            "",
            "- Live `attack_simulation.py` / `attack_lv2.py` / high-concurrency HTTP stress require a running API (optional here).",
            "- On-chain Sepolia / forge formal proofs are covered by separate CI (`security-ci`, `forge-ci`), not this offline suite.",
            "- Multi-instance Redis/DB races and DNS-rebinding SSRF need staging soak.",
            "- Demo env soft-paths (`auto_complete`, auth enforce off) remain for local loops.",
            "",
            "## Fail detail",
            "",
        ]
    )
    if not failed:
        lines.append("_none_")
    else:
        for s in failed:
            lines.append(f"### {s['label']}")
            lines.append("```")
            lines.append(s["stderr_tail"] or s["stdout_tail"] or "(no output)")
            lines.append("```")
            lines.append("")

    lines.extend(
        [
            "",
            "## Machine summary",
            "",
            "```json",
            json.dumps(
                {
                    "generated_at": now,
                    "hard_pass": not failed,
                    "scope": "whole_project",
                    "suites": [
                        {
                            "label": s["label"],
                            "ok": s["ok"],
                            "elapsed_s": s["elapsed_s"],
                            "returncode": s["returncode"],
                        }
                        for s in suites
                    ],
                },
                indent=2,
            ),
            "```",
            "",
        ]
    )
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(REPORT.read_text(encoding="utf-8"))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
