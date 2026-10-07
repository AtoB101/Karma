# -*- coding: utf-8 -*-
"""生产环境「必填闸门」的唯一来源：env 名 → 生产必须取的值。

为什么单独一个文件
------------------
``config/settings.py`` 里有一段 ``APP_ENV=production`` 的硬校验：任何一条不满足，
``Settings()`` 直接抛 ValueError、进程起不来（fail-closed）。这些键以前散落在两处
门禁脚本（``scripts/acceptance/phase1_open_wallet_gate.sh``、
``scripts/production-prelaunch-gate.sh``）、三份 .env 模板和文档里。2026-10-08 新增
``VERIFIER_REQUIRE_NODE_SIGNATURE`` 时漏改了脚本那一处，于是 CI 的
"Full-chain audit gate" 和线上部署（alembic 导入 settings）同时挂掉。

现在：
- 两处门禁脚本直接 ``from config.production_gates import PRODUCTION_GATE_DEFAULTS``；
- 模板/文档由 ``tests/unit/test_production_gate_manifest_parity.py`` 逐键校验；
- 那张校验**动态**枚举 settings 在 production 下拒绝、在 test 下不拒绝的字段：
  凡是「模型默认值本身不安全」的新闸门，只要没写进下面两张表，CI 立刻变红。

新增闸门的三步
--------------
1. ``config/settings.py``：加字段 + 在 production 分支里 raise；
2. 这里：开关/枚举进 ``PRODUCTION_GATE_FLAGS``（值就是 .env 必须写的值）；密钥、
   白名单这种「必须在场但取值因部署而异」的进 ``PRODUCTION_GATE_PLACEHOLDERS``；
   取值只有固定几个的，再登记进 ``PRODUCTION_GATE_ALLOWED_VALUES``；
3. ``PRODUCTION_GATE_TEMPLATES`` 里每个文件补上这个键（跑那条测试就知道缺谁）。
"""

from __future__ import annotations

# 生产必须显式给出的开关：不写 .env 就起不来（模型默认值本身不安全），或者
# 默认虽然安全、但仓库一直把它显式钉住（显式优于隐式，也防止本机 .env 反手关掉）。
PRODUCTION_GATE_FLAGS: dict[str, str] = {
    # --- 鉴权 / 限流 ---------------------------------------------------------
    "AUTH_ENFORCE_PROTECTED_ROUTES": "true",
    "AUTH_ALLOW_DEV_KEY_FALLBACK": "false",
    "RATE_LIMIT_REDIS_FAIL_CLOSED": "true",
    # --- 回执 / 账本 / 结算：三方 actor 绑定 ---------------------------------
    "RECEIPT_REQUIRE_SIGNATURE": "true",
    "LEDGER_REQUIRE_PARTY_ACTOR": "true",
    "SETTLEMENT_REQUIRE_PARTY_ACTOR": "true",
    # --- Runtime Key 安全闸门 ------------------------------------------------
    "RUNTIME_REQUIRE_SAVED_AUTOMATION_POLICY": "true",
    "RUNTIME_REQUIRE_TASK_AUTOMATION_READINESS": "true",
    "RUNTIME_REQUIRE_HANDOFF_ATTESTATION": "true",
    "RUNTIME_REQUIRE_WALLET_IDENTITY_BINDING": "true",
    "RUNTIME_DAILY_SPEND_PERSIST": "true",
    # --- 交易发起（Open Wallet / EIP-712）-----------------------------------
    "TRADE_LAUNCH_REQUIRE_EIP712": "true",
    "KARMA_SIGNING_BACKEND": "client_only",
    # --- x402 支付通道（生产禁止 mock）--------------------------------------
    "X402_PAYMENT_BACKEND": "sepolia",
    "X402_ALLOW_PRIVATE_HOSTS": "false",
    # --- 资金托管：后端热钱包绝不能当托管付款方 ------------------------------
    "CHAIN_ALLOW_HOT_WALLET_PAYER": "false",
    # --- 去中心化验证者网络：节点写接口必须自带节点钱包签名 -------------------
    "VERIFIER_REQUIRE_NODE_SIGNATURE": "true",
}

# 枚举型开关：模板里出现的取值必须落在这些值里（写错 = 生产起不来）。
PRODUCTION_GATE_ALLOWED_VALUES: dict[str, tuple[str, ...]] = {
    "KARMA_SIGNING_BACKEND": ("client_only", "external"),
    "X402_PAYMENT_BACKEND": ("env", "sepolia"),
}

# 必须在场、但取值因部署而异（密钥 / actor 白名单）：门禁脚本里给的是自检占位值，
# 模板只要求「键在场」，不校验值。
PRODUCTION_GATE_PLACEHOLDERS: dict[str, str] = {
    "APP_SECRET_KEY": "gate-check-secret-min-32-chars-long!!",
    "AUTH_API_KEYS": "gate-agent:gate-secret-minimum",
    "MINIO_ACCESS_KEY": "gate-check-minio-access",
    "MINIO_SECRET_KEY": "gate-check-minio-secret",
    "X402_PRIVATE_KEY": "0x" + "11" * 32,
    "ARBITRATOR_ACTOR_IDS": "gate-arbitrator",
}

# 门禁脚本 os.environ.setdefault 用的整表（两处脚本都直接 import 它）。
PRODUCTION_GATE_DEFAULTS: dict[str, str] = {
    **PRODUCTION_GATE_FLAGS,
    **PRODUCTION_GATE_PLACEHOLDERS,
}

# 必须依赖清单（而不是各写一份 dict）的门禁脚本。
PRODUCTION_GATE_SCRIPTS: tuple[str, ...] = (
    "scripts/acceptance/phase1_open_wallet_gate.sh",
    "scripts/production-prelaunch-gate.sh",
)

# 必须逐键列全清单的生产模板 / 文档（人可以照抄成 .env 的那种）。
PRODUCTION_GATE_TEMPLATES: tuple[str, ...] = (
    ".env.example",
    "deploy/.env.paas.example",
    "docs/DEPLOYMENT_GUIDE.md",
)
