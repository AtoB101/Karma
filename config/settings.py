"""
Karma — Global Settings (Public)
"""
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_secret_key: str = "change-me-in-production"
    debug: bool = False

    # Comma-separated browser origins for CORS, e.g. "https://app.example.com,https://console.example.com".
    # Empty in non-development environments defaults to no cross-origin allowance until configured.
    cors_allow_origins: str = ""

    # Database
    database_url: str = "postgresql+asyncpg://karma:karma@localhost:5432/karma_db"
    database_pool_size: int = 20
    database_max_overflow: int = 10

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # MinIO
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket_evidence: str = "karma-evidence"
    minio_bucket_receipts: str = "karma-receipts"
    minio_secure: bool = False

    # LLM
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"

    # Signing keys
    ed25519_private_key_path: str = "./keys/agent_private.pem"
    ed25519_public_key_path: str = "./keys/agent_public.pem"

    # Private runtime (internal only)
    private_runtime_url: str = "http://localhost:8001"
    private_runtime_api_key: str = ""

    # Settlement (off-chain)
    escrow_min_amount: float = 0.01
    escrow_max_amount: float = 10000.0
    dispute_window_hours: int = 72
    arbitration_timeout_hours: int = 168

    # Verification
    verification_min_steps: int = 1
    verification_hash_algo: str = "sha256"
    verification_timeout_seconds: int = 300

    # Reputation
    reputation_initial_score: float = 100.0
    reputation_min_score: float = 0.0
    reputation_max_score: float = 1000.0

    # Celery
    celery_broker_url: str = "redis://localhost:6379/3"
    celery_result_backend: str = "redis://localhost:6379/4"

    # Monitoring
    prometheus_port: int = 9090
    log_level: str = "INFO"

    # ------------------------------------------------------------------
    # Chain / Testnet
    # ------------------------------------------------------------------

    # Settlement mode: "offchain" | "testnet" | "hybrid"
    #   offchain — database only, no chain interaction
    #   testnet  — real on-chain settlement via existing Karma contracts
    #   hybrid   — off-chain receipts/verification, on-chain payment + hash
    settlement_mode: str = "offchain"

    # Testnet RPC
    testnet_rpc_url: str = ""
    testnet_chain_id: int = 11155111  # Sepolia default

    # Wallet used to sign and submit transactions (NEVER commit a real key)
    testnet_private_key: str = ""

    # Existing Karma contract addresses
    karma_engine_address: str = ""         # KarmaSettlementEngine (legacy/EIP-712)
    karma_non_custodial_address: str = ""  # KarmaNonCustodial (M2.0 batch)

    # ERC-20 token for settlement
    erc20_token_address: str = ""

    # Payee (worker agent wallet on-chain)
    payee_address: str = ""

    # EIP-712 scope string embedded in every Quote
    settlement_scope: str = "karma:agent-task:v1"

    # Quote TTL in seconds
    settlement_ttl_seconds: int = 3600

    @model_validator(mode="after")
    def _reject_default_secrets_in_production(self) -> "Settings":
        env = (self.app_env or "").lower()
        if env in ("production", "prod"):
            key = (self.app_secret_key or "").strip()
            if not key or key == "change-me-in-production":
                raise ValueError(
                    "APP_SECRET_KEY must be set to a strong value when APP_ENV is production",
                )
        return self

    def cors_allow_origins_list(self) -> list[str]:
        raw = (self.cors_allow_origins or "").strip()
        if raw:
            return [o.strip() for o in raw.split(",") if o.strip()]
        if (self.app_env or "").lower() in ("development", "dev", "local", "test"):
            return ["*"]
        return []


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
