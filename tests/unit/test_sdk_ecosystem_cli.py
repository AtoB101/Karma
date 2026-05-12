from __future__ import annotations

import json
import subprocess
from pathlib import Path

from sdk.ecosystem.cli import main
from sdk.ecosystem.core import KarmaEcosystemConfig
from sdk.ecosystem.openclaw import OpenClawKarmaAdapter
from sdk.ecosystem.openmanus import OpenManusKarmaAdapter


def test_openclaw_adapter_init_scaffold(tmp_path):
    config = KarmaEcosystemConfig(
        runtime_url="http://localhost:8000",
        agent_id="agent-openclaw-1",
        api_key="karma_agent-openclaw-1_secret",
        framework="openclaw",
        workspace_dir=tmp_path,
    )
    adapter = OpenClawKarmaAdapter(config)
    created = adapter.init_scaffold(overwrite=True)

    assert any(path.endswith(".env.karma.example") for path in created)
    assert any(path.endswith("karma.ecosystem.json") for path in created)
    assert any(path.endswith("openclaw/karma.integration.yaml") for path in created)
    assert (tmp_path / "openclaw/karma.integration.yaml").exists()


def test_openmanus_adapter_init_scaffold(tmp_path):
    config = KarmaEcosystemConfig(
        runtime_url="http://localhost:8000",
        agent_id="agent-openmanus-1",
        api_key="karma_agent-openmanus-1_secret",
        framework="openmanus",
        workspace_dir=tmp_path,
    )
    adapter = OpenManusKarmaAdapter(config)
    created = adapter.init_scaffold(overwrite=True)

    assert any(path.endswith(".env.karma.example") for path in created)
    assert any(path.endswith("karma.ecosystem.json") for path in created)
    assert any(path.endswith("openmanus/karma.integration.toml") for path in created)
    assert (tmp_path / "openmanus/karma.integration.toml").exists()


def test_cli_init_openclaw_writes_scaffold(tmp_path, capsys):
    exit_code = main(
        [
            "--framework",
            "openclaw",
            "--workspace-dir",
            str(tmp_path),
            "--agent-id",
            "agent-cli-1",
            "--api-key",
            "karma_agent-cli-1_secret",
            "init",
        ]
    )
    assert exit_code == 0
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["framework"] == "openclaw"
    assert (tmp_path / ".env.karma.example").exists()
    assert (tmp_path / "openclaw/karma.integration.yaml").exists()


def test_cli_doctor_reports_missing_env_when_skip_runtime(tmp_path, capsys):
    exit_code = main(
        [
            "--framework",
            "openmanus",
            "--workspace-dir",
            str(tmp_path),
            "--skip-runtime-check",
            "doctor",
        ]
    )
    assert exit_code == 0
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["status"] == "needs_attention"
    assert "KARMA_AGENT_ID" in payload["missing_env"]
    assert "KARMA_API_KEY" in payload["missing_env"]
    assert payload["runtime"]["detail"] == "runtime health check skipped"


def test_cli_bootstrap_writes_release_templates(tmp_path, capsys):
    exit_code = main(
        [
            "--framework",
            "openclaw",
            "--workspace-dir",
            str(tmp_path),
            "--agent-id",
            "agent-cli-2",
            "--api-key",
            "karma_agent-cli-2_secret",
            "--skip-runtime-check",
            "bootstrap",
        ]
    )
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["framework"] == "openclaw"
    assert (tmp_path / "deploy/karma-ecosystem/docker-compose.openclaw.yml").exists()
    assert (tmp_path / "scripts/karma-ecosystem-inject-env.sh").exists()
    assert (tmp_path / ".github/workflows/karma-ecosystem-verify.template.yml").exists()


def test_quickstart_wrapper_bootstraps_without_compose(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    script_path = repo_root / "scripts/ecosystem/quickstart.sh"
    assert script_path.exists()
    result = subprocess.run(
        [
            "bash",
            str(script_path),
            "--framework",
            "openmanus",
            "--workspace-dir",
            str(tmp_path),
            "--skip-runtime-check",
            "--overwrite",
            "--no-compose",
        ],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "Karma ecosystem quickstart completed." in result.stdout
    assert (tmp_path / ".env.karma").exists()
    assert (tmp_path / "openmanus/karma.integration.toml").exists()
    assert (tmp_path / "deploy/karma-ecosystem/docker-compose.openmanus.yml").exists()
