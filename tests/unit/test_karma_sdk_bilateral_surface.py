"""Static surface checks for packages/karma-sdk Bilateral lifecycle methods."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY_CLIENT = ROOT / "packages/karma-sdk/python/karma_sdk/client.py"
TS_CLIENT = ROOT / "packages/karma-sdk/typescript/src/index.ts"


def test_python_sdk_exposes_finalize_dispute_refund():
    text = PY_CLIENT.read_text(encoding="utf-8")
    for needle in (
        '"name": "finalizeSettle"',
        '"name": "dispute"',
        '"name": "refundOnTimeout"',
        "def finalize_settle",
        "def dispute",
        "def refund_on_timeout",
        '"FINALIZING"',
    ):
        assert needle in text, f"missing {needle}"


def test_typescript_sdk_exposes_finalize_dispute_refund():
    text = TS_CLIENT.read_text(encoding="utf-8")
    for needle in (
        "function finalizeSettle",
        "function dispute",
        "function refundOnTimeout",
        "async finalizeSettle",
        "async dispute",
        "async refundOnTimeout",
        "FINALIZING",
    ):
        assert needle in text, f"missing {needle}"


def test_sdk_exposes_bounded_subagent_authorization():
    """Sub-agent budget primitives must be wired through both SDKs."""
    py_text = PY_CLIENT.read_text(encoding="utf-8")
    for needle in (
        '"name": "lockFor"',
        '"name": "identityRegistry"',
        "def lock_for",
        "def identity_registry",
        "def free_balance",
    ):
        assert needle in py_text, f"python sdk missing {needle}"

    py_identity = (ROOT / "packages/karma-sdk/python/karma_sdk/identity.py").read_text(encoding="utf-8")
    for needle in (
        "class KarmaIdentityRegistry",
        "setSubAgentBounds",
        "def set_sub_agent_bounds",
        "def add_sub_agent",
        "def is_authorized",
        "def get_sub_agents",
    ):
        assert needle in py_identity, f"python identity client missing {needle}"

    ts_text = TS_CLIENT.read_text(encoding="utf-8")
    for needle in (
        '"function lockFor(',
        '"function identityRegistry() view returns (address)"',
        "KARMA_IDENTITY_REGISTRY_ABI",
        "class KarmaIdentityRegistry",
        "async lockFor",
        "async setSubAgentBounds",
        "async isAuthorized",
    ):
        assert needle in ts_text, f"typescript sdk missing {needle}"


def test_certora_verify_only_lists_live_confs():
    script = (ROOT / "scripts/certora-verify.sh").read_text(encoding="utf-8")
    assert "SettlementEngine.conf" not in script
    assert "NonCustodialAgentPayment.conf" not in script
    for conf in ("KYARegistry.conf", "CircuitBreaker.conf", "AuthTokenManager.conf"):
        assert conf in script
