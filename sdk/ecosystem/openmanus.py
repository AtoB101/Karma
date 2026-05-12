"""OpenManus one-click integration adapter."""
from __future__ import annotations

from typing import Any

from sdk.ecosystem.core import KarmaEcosystemConfig, KarmaEcosystemDeployer


_OPENMANUS_TEMPLATE = """[karma]
runtime_url = "${KARMA_RUNTIME_URL}"
agent_id = "${KARMA_AGENT_ID}"
api_key_env = "KARMA_API_KEY"

[karma.hooks]
before_execute = "karma.preflight"
after_execute = "karma.submit_receipts"
"""


class OpenManusKarmaAdapter:
    framework_name = "openmanus"

    def __init__(self, config: KarmaEcosystemConfig):
        self.deployer = KarmaEcosystemDeployer(config)

    def init_scaffold(self, *, overwrite: bool = False) -> list[str]:
        created = self.deployer.write_common_scaffold(overwrite=overwrite)
        created.append(
            self.deployer._write_file(
                "openmanus/karma.integration.toml",
                _OPENMANUS_TEMPLATE,
                overwrite=overwrite,
            )
        )
        return created

    async def deploy(self, *, overwrite: bool = False, skip_runtime_check: bool = False) -> dict[str, Any]:
        created = self.init_scaffold(overwrite=overwrite)
        doctor = await self.deployer.doctor(skip_runtime_check=skip_runtime_check)
        return {"framework": self.framework_name, "created_files": created, "doctor": doctor}

    async def verify(self, *, skip_runtime_check: bool = False) -> dict[str, Any]:
        return await self.deployer.doctor(skip_runtime_check=skip_runtime_check)
