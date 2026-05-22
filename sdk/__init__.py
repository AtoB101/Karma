"""
Karma Trust Protocol — Python SDK
==================================
One-stop import for integrating with the Karma runtime and decentralized verification.

Core Runtime:
    from karma.sdk import KarmaClient
    client = KarmaClient(runtime_url="https://api.karma.xyz", api_key="karma_...")
    result = await client.run_task(contract, my_task_fn)

Agent Runtimes (one-click connect):
    from karma.sdk import KarmaOpenClawAgent, discover_and_connect
    agent = await discover_and_connect()
    result, receipt = await agent.run_tool(task_id, "browser.navigate", fn, data)

Decentralized Verification (N-of-M attestation):
    from karma.sdk import DecentralizedVerifier, DecentralizedVerifierConfig
    dv = DecentralizedVerifier(DecentralizedVerifierConfig(
        verifier_id="node-001", wallet_address="0x..."
    ))
    attestation = await dv.verify_and_attest(task, bundle, receipts)
"""
from sdk.client import KarmaClient
from sdk.runtime_client import KarmaRuntime
from sdk.task import TaskRunner
from sdk.adapters import (
    APIExecutionAdapter,
    AIWorkflowExecutionAdapter,
    MCPExecutionAdapter,
    AgentRuntimeExecutionAdapter,
)
from sdk.openclaw_agent import KarmaOpenClawAgent
from sdk.integrations import (
    discover_and_connect,
    discover_all,
    validate_discovery,
    probe_runtime_health,
    probe_openclaw_gateway,
    build_connect_manifest,
    save_connect_manifest,
    load_connect_manifest,
    discover_agent_id,
    discover_api_key,
    discover_runtime_url,
    discover_openclaw_gateway,
    ENV_KARMA_RUNTIME_URL,
    ENV_KARMA_API_KEY,
    ENV_KARMA_AGENT_ID,
)

# Re-export OpenManus adapter from agents module
try:
    from agents.openmanus.adapter import KarmaOpenManusAgent
    _has_openmanus = True
except ImportError:
    _has_openmanus = False
    KarmaOpenManusAgent = None  # type: ignore[assignment]

# Decentralized verification layer
try:
    from sdk.verifier import (
        DecentralizedVerifier,
        DecentralizedVerifierConfig,
        EvidencePublisher,
        KarmaVerifierNode,
        AttestationAggregator,
        ChallengeWindowManager,
        structural_verify,
        verify_evidence_integrity,
        sign_attestation,
        verify_attestation,
    )
    _has_decentralized_verifier = True
except ImportError:
    _has_decentralized_verifier = False

__all__ = [
    # Core
    "KarmaClient",
    "KarmaRuntime",
    "TaskRunner",
    # Adapters
    "APIExecutionAdapter",
    "AIWorkflowExecutionAdapter",
    "MCPExecutionAdapter",
    "AgentRuntimeExecutionAdapter",
    # Agent wrappers
    "KarmaOpenClawAgent",
    "KarmaOpenManusAgent",
    # One-click integration
    "discover_and_connect",
    "discover_all",
    "validate_discovery",
    "discover_agent_id",
    "discover_api_key",
    "discover_runtime_url",
    "discover_openclaw_gateway",
    "probe_runtime_health",
    "probe_openclaw_gateway",
    "build_connect_manifest",
    "save_connect_manifest",
    "load_connect_manifest",
    # Env keys
    "ENV_KARMA_RUNTIME_URL",
    "ENV_KARMA_API_KEY",
    "ENV_KARMA_AGENT_ID",
    # Decentralized verification
    "DecentralizedVerifier",
    "DecentralizedVerifierConfig",
    "EvidencePublisher",
    "KarmaVerifierNode",
    "AttestationAggregator",
    "ChallengeWindowManager",
    "structural_verify",
    "verify_evidence_integrity",
    "sign_attestation",
    "verify_attestation",
]
