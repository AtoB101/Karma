#!/usr/bin/env python3
"""Require PR body 'Migration Impact' when changelog gains Change Type: Breaking.

Runs in GitHub Actions on pull_request. Compares base..head on changelog and
checks for *added* lines containing `Change Type: Breaking`.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = "docs/agent-service-guard-changelog.md"
MIGRATION_HEADING = re.compile(r"^#{1,3}\s*Migration Impact\s*$", re.IGNORECASE | re.MULTILINE)


def fail(msg: str) -> None:
    print(f"ERR  {msg}", file=sys.stderr)
    raise SystemExit(1)


def ok(msg: str) -> None:
    print(f"OK   {msg}")


def read_pr_body() -> str:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if event_path and Path(event_path).exists():
        data = json.loads(Path(event_path).read_text(encoding="utf-8"))
        pr = data.get("pull_request") or {}
        return (pr.get("body") or "").strip()
    return (os.environ.get("PR_BODY") or "").strip()


def git_diff_changelog(base_sha: str, head_sha: str) -> str:
    r = subprocess.run(
        ["git", "diff", f"{base_sha}...{head_sha}", "--", CHANGELOG],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        fail(f"git diff failed: {r.stderr or r.stdout}")
    return r.stdout


def introduces_breaking(diff_text: str) -> bool:
    for line in diff_text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+") and not line.startswith("+++"):
            if "Change Type: Breaking" in line[1:]:
                return True
    return False


def main() -> None:
    base_sha = os.environ.get("GITHUB_BASE_SHA") or os.environ.get("PR_BASE_SHA")
    head_sha = os.environ.get("GITHUB_HEAD_SHA") or os.environ.get("PR_HEAD_SHA")

    if not base_sha or not head_sha:
        print("SKIP PR migration-impact check: GITHUB_BASE_SHA / GITHUB_HEAD_SHA not set")
        sys.exit(0)

    diff_text = git_diff_changelog(base_sha, head_sha)
    if not diff_text.strip():
        ok("changelog unchanged in this PR; no Breaking gate")
        sys.exit(0)

    if not introduces_breaking(diff_text):
        ok("no new Change Type: Breaking in changelog diff")
        sys.exit(0)

    body = read_pr_body()
    if not body:
        fail(
            "This PR adds `Change Type: Breaking` to the changelog. "
            "Add a PR description section: `## Migration Impact` (or `### Migration Impact`) "
            "with rollout and integrator impact."
        )

    if not MIGRATION_HEADING.search(body):
        fail(
            "Changelog introduces Breaking change. PR body must include a section "
            "heading exactly: `## Migration Impact` or `### Migration Impact` "
            "(describe integrator steps; link to docs/migrations/<version>.md if applicable)."
        )

    ok("PR body includes Migration Impact section for Breaking changelog change")


if __name__ == "__main__":
    main()
