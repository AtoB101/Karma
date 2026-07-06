import os

REGISTRY_URL = os.getenv("A2A_REGISTRY_URL", "https://a2aregistry.org")
KARMA_API_BASE = os.getenv("KARMA_API_BASE", "https://karma-network.ai")
KARMA_API_KEY = os.getenv("KARMA_API_KEY", "")

AGENT_ID = os.getenv("A2A_AGENT_ID", "karma_bridge_001")
AGENT_NAME = os.getenv("A2A_AGENT_NAME", "Karma A2A Bridge")
AGENT_DESCRIPTION = os.getenv("A2A_AGENT_DESC", "Karma Trust Protocol A2A Bridge Agent")
AGENT_CAPABILITIES = os.getenv("A2A_AGENT_CAPABILITIES", "karma_settle,agent_discovery").split(",")
AGENT_ENDPOINT = os.getenv("A2A_AGENT_ENDPOINT", "http://localhost:8080")
AGENT_ICON_URL = os.getenv("A2A_AGENT_ICON_URL", "")

KARMA_CONTRACT_ADDRESS = os.getenv("KARMA_CONTRACT_ADDRESS", "0x496d178a5D32E9410E52bD5800602BDEe81B2A91")
KARMA_NETWORK = os.getenv("KARMA_NETWORK", "sepolia")
KARMA_SETTLEMENT_MODES = os.getenv("KARMA_SETTLEMENT_MODES", "bilateral,escrow").split(",")

HEARTBEAT_INTERVAL = int(os.getenv("A2A_HEARTBEAT_INTERVAL", "60"))
