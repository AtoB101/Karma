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
    # Comma-separated actor IDs (karma identity_id or telegram user id) allowed to
    # resolve disputes via /miniapp/disputes/resolve. Empty in production is rejected;
    # in development an empty list falls back to admin_actor_ids for convenience.
    arbitrator_actor_ids: str = ""
    # ---- 仲裁规则（P0-1 收紧，2026-09-17）--------------------------------
    # 调用者必须绑定到自己宣称的仲裁员身份（或案件当事人），运维白名单可代为操作。
    # 关掉它等于恢复「任何登录身份都能替别人投票」，生产环境必须是 true。
    arbitration_require_actor_binding: bool = True
    # 仲裁池是「开放申请」还是「仅限 ARBITRATOR_ACTOR_IDS 白名单」。
    # 两种模式下都只能给自己入池，且质押必须有真实锁仓背书。
    arbitration_pool_open_join: bool = False
    # 仲裁庭人数窗口：调用方不能自填人数，只能落在这个区间内。
    arbitration_min_arbitrators: int = 3
    arbitration_max_arbitrators: int = 21
    # 入池质押的下限（0 表示只要求 > 0），以及是否必须由已锁仓 USDC 背书。
    arbitration_min_stake_amount: float = 0.0
    arbitration_require_backed_stake: bool = True

    # Comma-separated identity ids allowed to hold governance role profiles
    # (class=verifier / arbitrator). Empty means nobody can self-create one over the
    # API; the operational grant path is scripts/ops/grant_governance_role.py on the
    # server. Either way an identity can never review its own filing.
    governance_verifier_ids: str = ""
    # Comma-separated identity ids allowed through the *platform bootstrap* approval
    # channel (scripts/maintenance/approve_identity_verification.py). That channel
    # signs as "platform:bootstrap" and exists only because a brand-new platform has
    # exactly one identity, which is therefore its own only reviewer.
    # Empty means nobody: the channel must stay scoped to platform-owned identities,
    # otherwise it is a KYC bypass back door for every user on the platform.
    bootstrap_approve_identity_ids: str = ""
    # When true, publishing a skill additionally requires a verified developer
    # real-name profile whose agreement wallet is the one signing the listing.
    skill_require_developer_verification: bool = True
    # ------------------------------------------------------------------
    # 第三方实名 / 活体服务（可选）
    # ------------------------------------------------------------------
    # none | mock | aliyun | tencent | persona。默认 none：不接任何服务商，主身份认证走
    # 「本人提交密文包 + 复核台人工核验」。填了名字但密钥没配齐时，接口会**明确报缺哪一项**，
    # 绝不静默降级成「已核验」。Karma 永远不经手证件 / 人脸明文：浏览器直连服务商，
    # 我们只收结论与会话号。生产环境禁止 mock。
    identity_provider: str = "none"
    # 服务商能访问到的公网地址（用来拼回调 URL）；不填就没法接回调。
    identity_provider_public_base_url: str = ""
    # 回调签名密钥：mock / 自建回调用它；Persona 用它自己的 webhook secret。
    identity_provider_callback_secret: str = ""
    # 回调时间戳的容忍窗口（秒）：挡重放。
    identity_provider_callback_tolerance_seconds: int = 300
    # 阿里云实人认证（Cloud Auth）
    identity_provider_aliyun_access_key_id: str = ""
    identity_provider_aliyun_access_key_secret: str = ""
    identity_provider_aliyun_scene_id: str = ""
    identity_provider_aliyun_endpoint: str = "cloudauth.aliyuncs.com"
    identity_provider_aliyun_region: str = "cn-hangzhou"
    # 腾讯云慧眼（人脸核身）
    identity_provider_tencent_secret_id: str = ""
    identity_provider_tencent_secret_key: str = ""
    identity_provider_tencent_rule_id: str = ""
    identity_provider_tencent_region: str = "ap-guangzhou"
    # Persona（海外：跨境电商用户走它）
    identity_provider_persona_api_key: str = ""
    identity_provider_persona_template_id: str = ""
    identity_provider_persona_webhook_secret: str = ""
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
    # Comma-separated CIDRs treated as reverse proxies. Forwarded headers
    # (X-Real-IP / X-Forwarded-For) are only believed when the socket peer is in
    # this list, so a caller cannot pick its own rate-limit bucket.
    rate_limit_trusted_proxy_cidrs: str = "127.0.0.0/8,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"

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
    # P2-8: hourly sweep refunds orders stuck in LOCKED/EXECUTED/EVIDENCE_SUBMITTED
    # longer than escrow_timeout_sweep_hours (aligned with on-chain settleTimeout = 7d).
    escrow_timeout_sweep_enabled: bool = True
    escrow_timeout_sweep_hours: int = 168

    # Verification
    verification_min_steps: int = 1
    verification_hash_algo: str = "sha256"
    verification_timeout_seconds: int = 300
    # Evidence bundle / verify proxy — limits oversized JSON and receipt lists (DoS mitigation).
    evidence_bundle_max_receipt_entries: int = 2048
    evidence_bundle_max_json_bytes: int = 5 * 1024 * 1024
    verify_max_combined_json_bytes: int = 5 * 1024 * 1024
    # P1-7：合同 / 结算流转这类交易明细默认只对当事人（买/卖）与平台运维岗开放。
    # 想让任何人都能公开审计交易明细（产品决策），把它设成 true 即可，不需要改代码。
    task_records_public_read: bool = False
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
    # ── Wallet registration gate ────────────────────────────────────────────
    # One wallet = one identity is enforced in services/identity_gateway/store.py
    # (`_BY_WALLET` index + create_sub_identity rejection).
    # These settings add the *funding* half of the rule: a wallet that holds no
    # funds may still register (onboarding must not dead-end), but it is throttled
    # on a dimension the caller cannot forge, so a script cannot mint identities
    # from a pile of freshly generated empty wallets.
    registration_require_funding: bool = True
    # "Has funds" = native balance >= threshold OR settlement-token balance >= threshold.
    # A threshold of 1 means "any nonzero balance".
    registration_min_native_wei: int = 1
    registration_min_token_units: int = 1
    # Zero-funding registrations allowed per real client IP / per window.
    registration_zero_funding_max_per_ip: int = 3
    # Zero-funding registrations allowed platform-wide / per window (funded wallets
    # are never counted against this, so a real user with funds is never blocked).
    # Kept well above the per-IP budget: this bucket exists to blunt a scripted
    # flood, not to cap growth — too low and a handful of empty wallets would
    # lock onboarding for every honest new user for a whole window.
    registration_zero_funding_max_global: int = 200
    registration_zero_funding_window_seconds: int = 3600
    registration_funding_rpc_timeout_seconds: int = 5
    # None = use openclaw_local_phase1_auto_relax + trade_launch_require_eip712 rule
    openclaw_relax_delivery_signatures: bool | None = None
    # Local OpenClaw Phase 1 template sets this true (never production)
    openclaw_local_phase1_auto_relax: bool = False
    # When true, POST /v1/progress/{id}/confirm requires authenticated actor to match settlement.client_agent_id (buyer).
    progress_confirm_require_buyer_actor: bool = False

    # Reputation
    reputation_initial_score: float = 100.0
    reputation_min_score: float = 0.0
    reputation_max_score: float = 1000.0
    # Pack off-chain score onto KarmaReputationAnchor (not a fee waiver).
    reputation_pack_min_score: float = 200.0
    reputation_pack_min_successes: int = 5
    reputation_rehab_days: int = 90
    reputation_dividend_min_score: float = 300.0
    karma_reputation_anchor_address: str = ""
    # Wash / fake-volume heuristics (do not grant pack credit).
    reputation_wash_min_amount: float = 1.0
    reputation_wash_pair_window_hours: int = 24
    reputation_wash_pair_max: int = 4
    reputation_wash_burst_window_minutes: int = 60
    reputation_wash_burst_max: int = 8
    reputation_wash_flag_pack_block: int = 3

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

    # Default seller penalty stake (bps) when locking on-chain at acceptance.
    # Rule: the seller stakes 30% of the order value on every accepted order
    # (cumulative — each accepted order locks its own bill), and may lock more at
    # any time to raise its own credibility. The stake is locked automatically on
    # acceptance so sellers never have to post margin by hand.
    settlement_default_penalty_bps: int = 3000

    # Token decimals for on-chain settlement (USDC = 6). Off-chain escrow is in
    # USD float; the on-chain boundary converts USD -> wei via 10**decimals.
    settlement_token_decimals: int = 6

    # Testnet RPC
    testnet_rpc_url: str = ""
    testnet_chain_id: int = 11155111  # Sepolia default

    # Wallet used to sign and submit transactions (NEVER commit a real key)
    testnet_private_key: str = ""

    # Seller/agent signer for the bilateral lock (penalty stake). When unset,
    # the bilateral lock+bind falls back to the buyer hot wallet (dev only).
    agent_testnet_private_key: str = ""

    # SECURITY (KSA-fund-006): when false, the backend hot wallet (TESTNET_PRIVATE_KEY)
    # may NOT act as the escrow payer — lock funds must come from user-signed
    # transactions (client_only / external signing). Allowed true only for
    # dev/testnet MVP; rejected in production by the settings validator.
    chain_allow_hot_wallet_payer: bool = True

    # Active Karma contract address (KarmaBilateral)
    karma_bilateral_address: str = ""
    # Deprecated aliases — prefer karma_bilateral_address
    karma_engine_address: str = ""         # legacy alias; unused by bilateral adapter
    karma_non_custodial_address: str = ""  # removed NCPA; kept for env compat only

    # ERC-20 token for settlement
    erc20_token_address: str = ""

    # Block explorer used by the Console to link a lock/withdraw transaction.
    chain_explorer_url: str = "https://sepolia.etherscan.io"

    # Console deposits: when true (and the two addresses + RPC above are set),
    # 「增加锁仓额度」 asks the user's wallet to sign approve + lock on-chain and
    # the ledger is credited from the receipt. Deliberately independent of
    # SETTLEMENT_MODE so turning on real deposits cannot change how orders settle.
    chain_wallet_lock_enabled: bool = False

    # ------------------------------------------------------------------
    # v2 non-custodial allowance escrow (KarmaAllowanceEscrow)
    # ------------------------------------------------------------------
    # The user keeps the USDC in their own wallet and grants the escrow a
    # one-time ERC-20 allowance; the Bill is then a *responsibility record*
    # ("this wallet has committed up to X"), not a deposit. Settlement pulls
    # payer -> payee directly, so the console never asks for a private key and
    # the user never signs again per order. Turning this on is independent of
    # SETTLEMENT_MODE, exactly like CHAIN_WALLET_LOCK_ENABLED.
    chain_allowance_escrow_enabled: bool = False
    allowance_escrow_address: str = ""

    # Karma's own operational account. It may bind/submit on behalf of a wallet
    # that named it as `operator`, but it can never move funds: only the payer's
    # own allowance gates a pull, and the payer can revoke at any time. Unset
    # means "no server-side signing" and the agent drives the calls itself.
    settlement_operator_address: str = ""
    settlement_operator_private_key: str = ""

    # Ceiling (gwei) Karma's own settlement account will ever pay for gas. A wild
    # fee spike must never make an automatic settlement uneconomic or drain the
    # operator account; 0 disables the cap.
    settlement_max_gas_price_gwei: float = 5.0

    # Challenge window (seconds) the console advertises for new commitments.
    allowance_escrow_dispute_window: int = 120

    # Automatic settlement: verify, then the money moves, without anybody
    # pressing a button. On-chain the pull is permissionless once the challenge
    # window has elapsed, so the only missing piece is a caller. With this on,
    # the API process walks the due bindings and executes them itself using the
    # operator key above (no user token, no user key). Off is the safe default
    # for any process that must never move money on its own.
    escrow_autosettle_enabled: bool = False
    escrow_autosettle_interval_seconds: int = 15
    escrow_autosettle_batch: int = 5

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

    # Phase 1 — Trade launch EIP-712 (Open Wallet signing)
    trade_launch_require_eip712: bool = False
    trade_launch_eip712_chain_id: int | None = None  # None → testnet_chain_id
    trade_launch_eip712_verifying_contract: str = "0x0000000000000000000000000000000000000000"
    trade_launch_signature_ttl_seconds: int = 600
    # client_only | external | local | env — local/env sign server-side (dev/CI only)
    karma_signing_backend: str = "client_only"
    karma_signing_dev_private_key: str = ""

    # Mirror trade launch amounts into Runtime Key daily spend (unify with policy daily_limit)
    trade_launch_record_runtime_daily_spend: bool = True

    # Phase 2 — x402 HTTP machine payments
    x402_enabled: bool = True
    x402_payment_backend: str = "mock"
    x402_default_max_budget_usdc: float = 10.0
    x402_hard_max_budget_usdc: float = 100.0
    x402_allow_private_hosts: bool = True

    # OpenClaw — optional outbound handoff webhooks (HMAC) + in-process event ring for polling
    openclaw_webhook_url: str = ""
    openclaw_webhook_secret: str = ""
    openclaw_webhook_store_events: bool = False
    openclaw_webhook_max_retries: int = 3

    # PaymentIntent maintenance (expire stale intents)
    payment_intent_expire_enabled: bool = True

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
        """Reject unsafe defaults in any non-development environment (production, testnet, staging)."""
        env = (self.app_env or "").lower()
        # Only skip these checks for local development environments
        if env not in ("development", "dev", "local", "test"):
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
            if not self.registration_require_funding:
                raise ValueError(
                    "REGISTRATION_REQUIRE_FUNDING must be true when APP_ENV is production",
                )
            if not self.arbitration_require_actor_binding:
                raise ValueError(
                    "ARBITRATION_REQUIRE_ACTOR_BINDING must be true when APP_ENV is production "
                    "(otherwise any logged-in identity can vote on someone else's dispute)",
                )
            if not (self.arbitrator_actor_ids or "").strip():
                raise ValueError(
                    "ARBITRATOR_ACTOR_IDS must list at least one dispute arbitrator when "
                    "APP_ENV is production (dispute resolution cannot be open to any session)",
                )
            if self.chain_allow_hot_wallet_payer:
                raise ValueError(
                    "CHAIN_ALLOW_HOT_WALLET_PAYER must be false when APP_ENV is production "
                    "(backend hot wallet must never be the escrow payer for real funds)",
                )
            if not self.receipt_require_signature:
                raise ValueError(
                    "RECEIPT_REQUIRE_SIGNATURE must be true when APP_ENV is production",
                )
            if not self.ledger_require_party_actor:
                raise ValueError(
                    "LEDGER_REQUIRE_PARTY_ACTOR must be true when APP_ENV is production",
                )
            if not self.settlement_require_party_actor:
                raise ValueError(
                    "SETTLEMENT_REQUIRE_PARTY_ACTOR must be true when APP_ENV is production",
                )
            if self.openclaw_relax_delivery_signatures is True:
                raise ValueError(
                    "OPENCLAW_RELAX_DELIVERY_SIGNATURES must be false or unset when APP_ENV is production",
                )
            if self.openclaw_local_phase1_auto_relax:
                raise ValueError(
                    "OPENCLAW_LOCAL_PHASE1_AUTO_RELAX must be false when APP_ENV is production",
                )
            if (self.identity_provider or "").strip().lower() == "mock":
                raise ValueError(
                    "IDENTITY_PROVIDER=mock is not allowed when APP_ENV is production "
                    "(the mock provider has no real identity check behind it)",
                )
            if (self.x402_payment_backend or "").strip().lower() == "mock":
                raise ValueError(
                    "X402_PAYMENT_BACKEND=mock is not allowed when APP_ENV is production",
                )
            if not self.trade_launch_require_eip712:
                raise ValueError(
                    "TRADE_LAUNCH_REQUIRE_EIP712 must be true when APP_ENV is production",
                )
            backend = (self.karma_signing_backend or "client_only").strip().lower()
            if backend in ("local", "env"):
                raise ValueError(
                    "KARMA_SIGNING_BACKEND must be client_only or external in production (not local/env)",
                )
            # Verify MinIO credentials are not defaults
            minio_access = (self.minio_access_key or "").strip()
            minio_secret = (self.minio_secret_key or "").strip()
            if not minio_access or minio_access == "minioadmin":
                raise ValueError(
                    "MINIO_ACCESS_KEY must be set to a non-default value in this environment",
                )
            if not minio_secret or minio_secret == "minioadmin":
                raise ValueError(
                    "MINIO_SECRET_KEY must be set to a non-default value in this environment",
                )
        return self

    def cors_allow_origins_list(self) -> list[str]:
        raw = (self.cors_allow_origins or "").strip()
        env = (self.app_env or "").lower()
        if raw:
            origins = [o.strip() for o in raw.split(",") if o.strip()]
            # Reject wildcard CORS outside local/dev/test — adversarial open-origin.
            if any(o == "*" for o in origins) and env not in (
                "development",
                "dev",
                "local",
                "test",
            ):
                return []
            return origins
        if env in ("development", "dev", "local", "test"):
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

    def arbitrator_actor_id_set(self) -> set[str]:
        raw = (self.arbitrator_actor_ids or "").strip()
        if raw:
            return {item.strip() for item in raw.split(",") if item.strip()}
        # Development convenience: fall back to admin allowlist when unset.
        return self.admin_actor_id_set()

    def governance_verifier_id_set(self) -> set[str]:
        """谁能给自己开 verifier / arbitrator 档案：运维白名单，默认无人。"""
        raw = (self.governance_verifier_ids or "").strip()
        if not raw:
            return set()
        return {item.strip() for item in raw.split(",") if item.strip()}

    def bootstrap_approve_identity_id_set(self) -> set[str]:
        """自举审批只对哪些身份开放（平台自有的那一个）：默认**谁都不给**。

        这条通道签的是 platform:bootstrap，一旦放开就等于绕开实名核验，
        所以默认必须是空的；要用必须显式在服务器 .env 里点名。
        """
        raw = (self.bootstrap_approve_identity_ids or "").strip()
        if not raw:
            return set()
        return {item.strip() for item in raw.split(",") if item.strip()}


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
