"""OpenClaw one-click integration adapter."""
from __future__ import annotations

from typing import Any

from sdk.ecosystem.core import KarmaEcosystemConfig, KarmaEcosystemDeployer


_OPENCLAW_TEMPLATE = """version: 1
name: karma-openclaw-integration
runtime:
  url: ${KARMA_RUNTIME_URL}
  agent_id: ${KARMA_AGENT_ID}
  api_key_env: KARMA_API_KEY
hooks:
  on_task_start: karma.preflight
  on_task_end: karma.submit_receipts
"""


class OpenClawKarmaAdapter:
    framework_name = "openclaw"

    def __init__(self, config: KarmaEcosystemConfig):
        self.deployer = KarmaEcosystemDeployer(config)

    def init_scaffold(self, *, overwrite: bool = False) -> list[str]:
        created = self.deployer.write_common_scaffold(overwrite=overwrite)
        created.append(
            self.deployer._write_file(
                "openclaw/karma.integration.yaml",
                _OPENCLAW_TEMPLATE,
                overwrite=overwrite,
            )
        )
        return created

    async def deploy(
        self,
        *,
        overwrite: bool = False,
        skip_runtime_check: bool = False,
        release_templates: bool = False,
    ) -> dict[str, Any]:
        created = self.init_scaffold(overwrite=overwrite)
        if release_templates:
            created.extend(
                self.deployer.write_release_templates(
                    framework=self.framework_name,
                    overwrite=overwrite,
                )
            )
        doctor = await self.deployer.doctor(skip_runtime_check=skip_runtime_check)
        return {"framework": self.framework_name, "created_files": created, "doctor": doctor}

    async def verify(self, *, skip_runtime_check: bool = False) -> dict[str, Any]:
        return await self.deployer.doctor(skip_runtime_check=skip_runtime_check)
