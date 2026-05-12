"""Core helpers for one-click ecosystem integrations."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


@dataclass(slots=True)
class KarmaEcosystemConfig:
    runtime_url: str
    agent_id: str
    api_key: str
    framework: str
    workspace_dir: Path

    @classmethod
    def from_env(
        cls,
        *,
        framework: str,
        workspace_dir: Path | None = None,
        runtime_url: str | None = None,
        agent_id: str | None = None,
        api_key: str | None = None,
    ) -> "KarmaEcosystemConfig":
        resolved_workspace = workspace_dir or Path.cwd()
        return cls(
            runtime_url=(runtime_url or os.getenv("KARMA_RUNTIME_URL", "http://localhost:8000")).rstrip("/"),
            agent_id=agent_id or os.getenv("KARMA_AGENT_ID", ""),
            api_key=api_key or os.getenv("KARMA_API_KEY", ""),
            framework=framework,
            workspace_dir=resolved_workspace,
        )


class KarmaEcosystemDeployer:
    """Shared deploy/init/verify routines for ecosystem adapters."""

    def __init__(self, config: KarmaEcosystemConfig):
        self.config = config

    def _write_file(self, relative_path: str, content: str, *, overwrite: bool) -> str:
        file_path = self.config.workspace_dir / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        if file_path.exists() and not overwrite:
            return f"SKIPPED:{file_path}"
        file_path.write_text(content, encoding="utf-8")
        return str(file_path)

    def write_common_scaffold(self, *, overwrite: bool = False) -> list[str]:
        env_template = (
            f"KARMA_RUNTIME_URL={self.config.runtime_url}\n"
            f"KARMA_AGENT_ID={self.config.agent_id or 'agent-001'}\n"
            "KARMA_API_KEY=karma_agent-001_replace-with-real-key\n"
            f"KARMA_FRAMEWORK={self.config.framework}\n"
        )
        metadata = {
            "framework": self.config.framework,
            "runtime_url": self.config.runtime_url,
            "agent_id": self.config.agent_id or "agent-001",
            "generated_by": "karma-ecosystem-cli",
        }
        created = [
            self._write_file(".env.karma.example", env_template, overwrite=overwrite),
            self._write_file("karma.ecosystem.json", json.dumps(metadata, indent=2) + "\n", overwrite=overwrite),
        ]
        return created

    def write_release_templates(self, *, framework: str, overwrite: bool = False) -> list[str]:
        compose_template = f"""version: "3.9"
services:
  karma-ecosystem-check:
    image: python:3.11-slim
    working_dir: /workspace
    env_file:
      - .env.karma
    volumes:
      - .:/workspace
    command: >
      bash -lc "python -m pip install --upgrade pip && python -m pip install -e . && \\
      karma-ecosystem --framework {framework} verify --workspace-dir /workspace --skip-runtime-check"
"""
        env_inject_script = """#!/usr/bin/env bash
set -euo pipefail

WORKSPACE_DIR="${1:-.}"
EXAMPLE_PATH="${WORKSPACE_DIR}/.env.karma.example"
TARGET_PATH="${WORKSPACE_DIR}/.env.karma"

if [[ ! -f "${EXAMPLE_PATH}" ]]; then
  echo "missing ${EXAMPLE_PATH}; run karma-ecosystem ... init first"
  exit 1
fi

if [[ -f "${TARGET_PATH}" ]]; then
  echo "${TARGET_PATH} already exists; skipping"
  exit 0
fi

cp "${EXAMPLE_PATH}" "${TARGET_PATH}"
echo "generated ${TARGET_PATH}"
echo "edit KARMA_API_KEY and KARMA_AGENT_ID before deployment"
"""
        workflow_template = f"""name: Karma Ecosystem Verify

on:
  workflow_dispatch:
  pull_request:
    branches: ["**"]

jobs:
  karma-ecosystem-verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install package
        run: |
          python -m pip install --upgrade pip
          python -m pip install -e ".[dev]"
      - name: Generate scaffold
        run: |
          karma-ecosystem --framework {framework} init --workspace-dir .
          bash scripts/karma-ecosystem-inject-env.sh .
      - name: Doctor
        run: |
          karma-ecosystem --framework {framework} doctor --workspace-dir . --skip-runtime-check
"""
        created = [
            self._write_file(
                f"deploy/karma-ecosystem/docker-compose.{framework}.yml",
                compose_template,
                overwrite=overwrite,
            ),
            self._write_file(
                "scripts/karma-ecosystem-inject-env.sh",
                env_inject_script,
                overwrite=overwrite,
            ),
            self._write_file(
                ".github/workflows/karma-ecosystem-verify.template.yml",
                workflow_template,
                overwrite=overwrite,
            ),
        ]
        return created

    async def verify_runtime(self, *, skip_runtime_check: bool = False) -> dict[str, Any]:
        if skip_runtime_check:
            return {"reachable": None, "status_code": None, "detail": "runtime health check skipped"}
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.config.runtime_url}/health")
            return {
                "reachable": resp.status_code == 200,
                "status_code": resp.status_code,
                "detail": "ok" if resp.status_code == 200 else "non-200 response",
            }
        except Exception as exc:  # pragma: no cover - network issues vary by env
            return {"reachable": False, "status_code": None, "detail": f"runtime unreachable: {exc}"}

    async def doctor(self, *, skip_runtime_check: bool = False) -> dict[str, Any]:
        missing = []
        if not self.config.runtime_url:
            missing.append("KARMA_RUNTIME_URL")
        if not self.config.agent_id:
            missing.append("KARMA_AGENT_ID")
        if not self.config.api_key:
            missing.append("KARMA_API_KEY")
        runtime = await self.verify_runtime(skip_runtime_check=skip_runtime_check)
        healthy = (len(missing) == 0) and (runtime["reachable"] in {True, None})
        return {
            "framework": self.config.framework,
            "workspace_dir": str(self.config.workspace_dir),
            "missing_env": missing,
            "runtime": runtime,
            "status": "ok" if healthy else "needs_attention",
        }
