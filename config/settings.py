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
    # Comma-separated static API keys: "agent-1:supersecret,agent-2:anothersecret".
    # Required in production for secure token issuance / API-key auth.
    auth_api_keys: str = ""
    # If enabled, all protected API routers require valid auth headers.
    auth_enforce_protected_routes: bool = False
    # When true with AUTH_ENFORCE_PROTECTED_ROUTES, accept karma_{agent}_{secret} keys that are not
    # listed in AUTH_API_KEYS (development convenience). Must stay false in production.
    auth_allow_dev_key_fallback: bool = False
    # Comma-separated privileged actor IDs allowed to use brake-only admin controls.
    admin_actor_ids: str = ""
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
    # When true, Redis errors in rate limiting return 503 instead of failing open (DDoS risk if Redis is down).
    rate_limit_redis_fail_closed: bool = False

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

    # Public Runtime Gateway (SDK / Console) — canonical external base URL for signed payloads.
    public_runtime_base_url: str = ""

    # Settlement (off-chain)
    escrow_min_amount: float = 0.01
    escrow_max_amount: float = 10000.0
    dispute_window_hours: int = 72
    arbitration_timeout_hours: int = 168

    # Verification
    verification_min_steps: int = 1
    verification_hash_algo: str = "sha256"
    verification_timeout_seconds: int = 300
    # Evidence bundle / verify proxy — limits oversized JSON and receipt lists (DoS mitigation).
    evidence_bundle_max_receipt_entries: int = 2048
    evidence_bundle_max_json_bytes: int = 5 * 1024 * 1024
    verify_max_combined_json_bytes: int = 5 * 1024 * 1024
    receipt_require_signature: bool = True
    receipt_max_future_skew_seconds: int = 300
    receipt_max_past_hours: int = 24 * 7
    # When true, execution/progress receipt timestamps may not be older than receipt_max_past_hours_strict.
    receipt_strict_recent_timestamps: bool = True
    receipt_max_past_hours_strict: int = 24
    # When true together with AUTH_ENFORCE_PROTECTED_ROUTES, settlement mutations require the caller's
    # authenticated actor to match the economic party (buyer = client_agent_id, worker = worker_agent_id).
    settlement_require_party_actor: bool = True
    # When true, POST /v1/settlement/{task_id}/lock is only allowed from PENDING (not directly from DRAFT).
    settlement_lock_requires_pending: bool = False
    # KSA2-006: require ≥1 successful execution receipt before any seller-side monetary release
    # (partial / regret / auto-arbitrate / buyer-accept), except pure refunds (settled_amount≈0).
    settlement_requires_success_execution_receipt_for_seller_release: bool = True
    # KSA2-034: reject worker lock if it would close a directed cycle among non-terminal settlements.
    settlement_block_buyer_worker_payment_cycle: bool = True
    # When true with AUTH_ENFORCE_PROTECTED_ROUTES, capacity lock/release and voucher create/verify/accept
    # bind the authenticated actor to the ledger identity or asserted voucher party (buyer/seller).
    ledger_require_party_actor: bool = True
    # P1 — bind typed execution receipt extensions to voucher.task_type when a settlement links a voucher.
    receipt_template_voucher_binding: bool = True
    progress_require_signature: bool = True
    # When true, POST /v1/progress/{id}/confirm requires authenticated actor to match settlement.client_agent_id (buyer).
    progress_confirm_require_buyer_actor: bool = False

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

    # P0 — Authorization Voucher EIP-712 (buyer commitment)
    # When true, POST /v1/vouchers requires buyer_wallet_address and a valid ECDSA
    # signature over the KarmaAuthorizationVoucher typed data (see services/voucher_eip712.py).
    voucher_require_eip712: bool = False
    voucher_eip712_chain_id: int | None = None  # None → testnet_chain_id
    voucher_eip712_verifying_contract: str = "0x0000000000000000000000000000000000000000"

    # OpenClaw — optional outbound handoff webhooks (HMAC) + in-process event ring for polling
    openclaw_webhook_url: str = ""
    openclaw_webhook_secret: str = ""
    openclaw_webhook_store_events: bool = False

    # Console — require saved automation policy before Runtime Key mint (fund limits + permissions + responsibility ack)
    runtime_require_saved_automation_policy: bool = False

    # Runtime mutators (receipt, progress, settlement, check-voucher) require task automation-readiness
    runtime_require_task_automation_readiness: bool = False

    # Require POST /v1/openclaw/handoff-confirm before task automation (pairs with readiness)
    runtime_require_handoff_attestation: bool = False

    # Runtime Key daily spend — persist to DB (recommended production / multi-instance)
    runtime_daily_spend_persist: bool = True

    # Wallet ↔ karma_identity_id binding on Runtime Key mint
    runtime_require_wallet_identity_binding: bool = False
    runtime_auto_bind_wallet_on_create_key: bool = True

    @model_validator(mode="after")
    def _reject_default_secrets_in_production(self) -> "Settings":
        env = (self.app_env or "").lower()
        if env in ("production", "prod"):
            key = (self.app_secret_key or "").strip()
            if not key or key == "change-me-in-production":
                raise ValueError(
                    "APP_SECRET_KEY must be set to a strong value when APP_ENV is production",
                )
            if not self.auth_enforce_protected_routes:
                raise ValueError(
                    "AUTH_ENFORCE_PROTECTED_ROUTES must be true when APP_ENV is production",
                )
            if not self.auth_api_keys_map():
                raise ValueError(
                    "AUTH_API_KEYS must contain at least one configured agent key in production",
                )
            if self.auth_allow_dev_key_fallback:
                raise ValueError(
                    "AUTH_ALLOW_DEV_KEY_FALLBACK must be false when APP_ENV is production",
                )
            if not self.rate_limit_redis_fail_closed:
                raise ValueError(
                    "RATE_LIMIT_REDIS_FAIL_CLOSED must be true when APP_ENV is production",
                )
            if not self.runtime_require_saved_automation_policy:
                raise ValueError(
                    "RUNTIME_REQUIRE_SAVED_AUTOMATION_POLICY must be true when APP_ENV is production",
                )
            if not self.runtime_require_task_automation_readiness:
                raise ValueError(
                    "RUNTIME_REQUIRE_TASK_AUTOMATION_READINESS must be true when APP_ENV is production",
                )
            if not self.runtime_require_handoff_attestation:
                raise ValueError(
                    "RUNTIME_REQUIRE_HANDOFF_ATTESTATION must be true when APP_ENV is production",
                )
            if not self.runtime_require_wallet_identity_binding:
                raise ValueError(
                    "RUNTIME_REQUIRE_WALLET_IDENTITY_BINDING must be true when APP_ENV is production",
                )
            if not self.runtime_daily_spend_persist:
                raise ValueError(
                    "RUNTIME_DAILY_SPEND_PERSIST must be true when APP_ENV is production",
                )
        return self

    def cors_allow_origins_list(self) -> list[str]:
        raw = (self.cors_allow_origins or "").strip()
        if raw:
            return [o.strip() for o in raw.split(",") if o.strip()]
        if (self.app_env or "").lower() in ("development", "dev", "local", "test"):
            return ["*"]
        return []

    def auth_api_keys_map(self) -> dict[str, str]:
        raw = (self.auth_api_keys or "").strip()
        if not raw:
            return {}
        parsed: dict[str, str] = {}
        for item in raw.split(","):
            entry = item.strip()
            if not entry or ":" not in entry:
                continue
            agent_id, secret = entry.split(":", 1)
            agent_id = agent_id.strip()
            secret = secret.strip()
            if agent_id and secret:
                parsed[agent_id] = secret
        return parsed

    def admin_actor_id_set(self) -> set[str]:
        raw = (self.admin_actor_ids or "").strip()
        if not raw:
            return set()
        return {item.strip() for item in raw.split(",") if item.strip()}


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
