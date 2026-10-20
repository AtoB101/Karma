import os

from identity import resolve_bridge_agent_id

REGISTRY_URL = os.getenv("A2A_REGISTRY_URL", "https://a2aregistry.org")
KARMA_API_BASE = os.getenv("KARMA_API_BASE", "https://karma-network.ai")
KARMA_API_KEY = os.getenv("KARMA_API_KEY", "")

# agent_id is a DID projection when A2A_DID_AGENT_ADDRESS is set
AGENT_ID = resolve_bridge_agent_id()
AGENT_NAME = os.getenv("A2A_AGENT_NAME", "Karma A2A Bridge")
AGENT_DESCRIPTION = os.getenv("A2A_AGENT_DESC", "Karma Trust Protocol A2A Bridge Agent")
# Discoverable capabilities — NOT privileged VerifierRegistry methods
_DEFAULT_CAPS = "karma_settle,agent_discovery,karma_attestation"
AGENT_CAPABILITIES = os.getenv("A2A_AGENT_CAPABILITIES", _DEFAULT_CAPS).split(",")
AGENT_ENDPOINT = os.getenv("A2A_AGENT_ENDPOINT", "http://localhost:8080")
AGENT_ICON_URL = os.getenv("A2A_AGENT_ICON_URL", "")

KARMA_CONTRACT_ADDRESS = os.getenv("KARMA_CONTRACT_ADDRESS", "0xF8aa4fDc19dc7Fff855B99521F9a60E0A3c5A14A")
KARMA_VERIFIER_REGISTRY = os.getenv("KARMA_VERIFIER_REGISTRY", "0x0240639afE02Fb48b5a0B2F227C20f724Cad88EC")
KARMA_ATTESTATION_GATEWAY = os.getenv("KARMA_ATTESTATION_GATEWAY", "0x2a47e749d011CB2aa8D282bDbAD7e83045a6D0A9")
KARMA_NETWORK = os.getenv("KARMA_NETWORK", "base-sepolia")
KARMA_SETTLEMENT_MODES = os.getenv("KARMA_SETTLEMENT_MODES", "bilateral,escrow").split(",")

DID_AGENT_ADDRESS = os.getenv("A2A_DID_AGENT_ADDRESS", "")
ON_CHAIN_DID = os.getenv("A2A_ON_CHAIN_DID", "")

HEARTBEAT_INTERVAL = int(os.getenv("A2A_HEARTBEAT_INTERVAL", "60"))
