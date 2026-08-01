#!/usr/bin/env python3
"""
Adversarial full-chain suite — P1–P8 stress / security / rule-gap tests.

Runs pytest adversarial + reverse_rule_audit + existing plate unit packs.
Exit 0 only if all hard gates pass. Writes a markdown report under docs/.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "docs" / "ADVERSARIAL_FULLCHAIN_AUDIT_V1.md"


def _run(cmd: list[str], *, label: str) -> dict:
    t0 = time.time()
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    elapsed = time.time() - t0
    return {
        "label": label,
        "cmd": " ".join(cmd),
        "returncode": proc.returncode,
        "elapsed_s": round(elapsed, 2),
        "stdout_tail": (proc.stdout or "")[-4000:],
        "stderr_tail": (proc.stderr or "")[-2000:],
        "ok": proc.returncode == 0,
    }


def main() -> int:
    suites = [
        _run(
            [sys.executable, "scripts/acceptance/reverse_rule_audit.py"],
            label="reverse_rule_audit (static P1–P8)",
        ),
        _run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "tests/unit/test_adversarial_p1_p8.py",
                "--tb=line",
            ],
            label="adversarial_p1_p8 (crypto/collusion/bypass/race/privacy)",
        ),
        _run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "tests/unit/test_important_fields_secure.py",
                "tests/unit/test_accept_fulfillment.py",
                "tests/unit/test_delivery_verification.py",
                "tests/unit/test_settlement_reputation.py",
                "tests/unit/test_human_confirmation_policy.py",
                "tests/unit/test_p4_fulfill_confirmation.py",
                "tests/unit/test_discovery_priority.py",
                "tests/unit/test_agent_boundary.py",
                "tests/unit/test_agent_p1_readiness.py",
                "--tb=line",
            ],
            label="plate_unit_pack P1–P8",
        ),
    ]

    # Stress: 200 parallel nonce races across 25 captures
    stress = _run(
        [
            sys.executable,
            "-c",
            r"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from services import important_fields_capture as c
from services.important_fields_capture import capture_from_interaction, encrypt_for_capture, submit_encrypted, CaptureError
from services.important_fields_standard import example_for_scene
c.reset_capture_store()
fields = example_for_scene('ride_hailing')['fields']
ok = err = 0
def one(i):
    global ok, err
    cid = capture_from_interaction(
        scene_id='ride_hailing', interaction_ref=f'a2a:stress-{i}',
        extracted_fields=fields, buyer_agent_id=f'b{i}', seller_agent_id=f's{i}',
    )['capture_id']
    ct = encrypt_for_capture(cid, fields, role='buyer')['ciphertext']
    local_ok = local_err = 0
    def try_sub(j):
        nonlocal local_ok, local_err
        try:
            submit_encrypted(capture_id=cid, role='buyer', ciphertext=ct,
                             nonce=f'nonce-stress-{i:04d}', submitter_agent_id=f'b{i}')
            local_ok += 1
        except CaptureError:
            local_err += 1
    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = [pool.submit(try_sub, j) for j in range(8)]
        for f in as_completed(futs):
            f.result()
    assert local_ok == 1 and local_err == 7, (local_ok, local_err)
    return local_ok, local_err
with ThreadPoolExecutor(max_workers=8) as pool:
    futs = [pool.submit(one, i) for i in range(25)]
    for f in as_completed(futs):
        o, e = f.result()
        ok += o; err += e
print(f'STRESS_OK captures=25 nonce_ok={ok} nonce_rej={err}')
assert ok == 25 and err == 175
""",
        ],
        label="stress_nonce_races (25×8)",
    )
    suites.append(stress)

    failed = [s for s in suites if not s["ok"]]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        "# Adversarial Full-Chain Audit V1",
        "",
        f"Generated: `{now}`",
        "",
        "## Verdict",
        "",
        (
            "**HARD FAIL** — one or more adversarial gates failed."
            if failed
            else "**HARD PASS** — static audit + adversarial + plate units + nonce stress green."
        ),
        "",
        "## Scope",
        "",
        "Attack posture: overthrow the commerce loop (P1–P8) via crypto splice, collusion,",
        "gate bypass, race/replay, silent-TTL abuse, discovery demote evasion, settlement",
        "privacy scrape, and production soft-path (`auto_complete` / omitted `scene_id`).",
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
            "## Hardenings applied this pass",
            "",
            "1. `buyer-accept` P4 gate uses settlement scene hint — omitting `scene_id` no longer bypasses OWNER_CONFIRM.",
            "2. `auto_complete=true` refused outside development/test (`auto_complete_forbidden`).",
            "3. P8 attestation disk store strips plaintext party ids / amount (ciphertext-only persist).",
            "4. Public reputation omits raw `agent_id` by default (`include_agent_id` opt-in).",
            "5. `/settlement-reputation/.../decrypt` and `/attestations/seal` always require auth.",
            "6. Important-fields `session-key` + `encrypt` helpers always require auth.",
            "",
            "## Residual risk (honest)",
            "",
            "- Demo env still allows `auto_complete` / `auto_lock` (test/local only).",
            "- Agent-id rotation to reset non-confirm ledger is not yet owner-bound inheritance.",
            "- Decrypt auth proves actor identity but does not yet bind role keys to party membership.",
            "- Multi-instance race safety still depends on single-process locks / local JSON ledgers.",
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
