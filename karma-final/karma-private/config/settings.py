"""
PRIVATE — Karma Runtime Settings
Contains production thresholds and sensitive config.
DO NOT commit to public repository.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class PrivateSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env.private", env_file_encoding="utf-8", extra="ignore"
    )

    # Runtime
    runtime_host: str = "127.0.0.1"
    runtime_port: int = 8001
    runtime_api_key: str = "change-in-production"
    policy_version: str = "private-policy-v1"
    audit_log_path: str = "./runtime-data/private-audit.log"

    # Database (same as public)
    database_url: str = "postgresql+asyncpg://karma:karma@localhost:5432/karma_db"
    database_pool_size: int = 10

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Signing
    ed25519_private_key_path: str = "./keys/runtime_private.pem"
    ed25519_public_key_path: str = "./keys/runtime_public.pem"

    # Settlement limits
    escrow_min_amount: float = 0.01
    escrow_max_amount: float = 10000.0

    # PRIVATE: Verification thresholds (not in public settings)
    verification_min_success_rate: float = 0.80
    verification_min_step_ratio: float = 0.75
    anti_cheat_min_duration_ms: int = 10
    timing_uniformity_max_cv: float = 0.03
    spam_max_duplicate_ratio: float = 0.30

    # PRIVATE: Settlement decision thresholds
    settlement_release_min_score: float = 0.80
    settlement_hold_min_score: float = 0.65
    settlement_dispute_min_score: float = 0.40

    # PRIVATE: Arbitration thresholds
    arbitration_seller_wins_score: float = 0.72
    arbitration_buyer_wins_score: float = 0.35

    # PRIVATE: Reputation scoring
    reputation_decay_factor: float = 0.95
    reputation_initial_score: float = 100.0
    reputation_max_score: float = 1000.0
    reputation_min_score: float = 0.0
    reputation_dispute_rate_threshold: float = 0.15
    reputation_streak_bonus_cap: float = 10.0

    # PRIVATE: Risk scoring
    risk_hold_threshold: float = 0.40
    risk_block_threshold: float = 0.70
    wash_trade_window: int = 10
    wash_trade_pair_limit: int = 3

    # Monitoring
    log_level: str = "INFO"


@lru_cache()
def get_private_settings() -> PrivateSettings:
    return PrivateSettings()


settings = get_private_settings()
