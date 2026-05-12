"""CLI for one-click Karma ecosystem deployment."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from sdk.ecosystem.core import KarmaEcosystemConfig
from sdk.ecosystem.openclaw import OpenClawKarmaAdapter
from sdk.ecosystem.openmanus import OpenManusKarmaAdapter


def _build_adapter(
    framework: str,
    *,
    runtime_url: str | None,
    agent_id: str | None,
    api_key: str | None,
    workspace_dir: str | None,
):
    config = KarmaEcosystemConfig.from_env(
        framework=framework,
        runtime_url=runtime_url,
        agent_id=agent_id,
        api_key=api_key,
        workspace_dir=Path(workspace_dir) if workspace_dir else None,
    )
    if framework == "openclaw":
        return OpenClawKarmaAdapter(config)
    if framework == "openmanus":
        return OpenManusKarmaAdapter(config)
    raise ValueError(f"unsupported framework: {framework}")


def _make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="karma-ecosystem", description="One-click ecosystem integration for Karma")
    parser.add_argument("--framework", required=True, choices=["openclaw", "openmanus"])
    parser.add_argument("--runtime-url", default=None)
    parser.add_argument("--agent-id", default=None)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--workspace-dir", default=None)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-runtime-check", action="store_true")
    parser.add_argument("--release-templates", action="store_true")
    parser.add_argument("command", choices=["init", "deploy", "verify", "doctor", "bootstrap"])
    return parser


async def _run_async(args: argparse.Namespace) -> dict:
    adapter = _build_adapter(
        args.framework,
        runtime_url=args.runtime_url,
        agent_id=args.agent_id,
        api_key=args.api_key,
        workspace_dir=args.workspace_dir,
    )
    if args.command == "init":
        return {"framework": args.framework, "created_files": adapter.init_scaffold(overwrite=args.overwrite)}
    if args.command == "deploy":
        return await adapter.deploy(
            overwrite=args.overwrite,
            skip_runtime_check=args.skip_runtime_check,
            release_templates=args.release_templates,
        )
    if args.command == "bootstrap":
        return await adapter.deploy(
            overwrite=args.overwrite,
            skip_runtime_check=args.skip_runtime_check,
            release_templates=True,
        )
    if args.command in {"verify", "doctor"}:
        return await adapter.verify(skip_runtime_check=args.skip_runtime_check)
    raise ValueError(f"unsupported command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    parser = _make_parser()
    args = parser.parse_args(argv)
    result = asyncio.run(_run_async(args))
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
