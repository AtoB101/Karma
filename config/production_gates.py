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


def _clean_value(raw: str) -> str:
    """取值清洗：引号里以引号为准，未加引号的 ` #` 之后算行内注释。"""
    value = raw.strip()
    if value[:1] in ('"', "'"):
        quote = value[0]
        end = value.find(quote, 1)
        return value[1:end] if end > 0 else value
    for marker in (" #", "\t#"):
        cut = value.find(marker)
        if cut >= 0:
            value = value[:cut]
    return value.strip()


def parse_env(text: str) -> dict[str, str]:
    """极简 dotenv 解析：跳过注释/空行，忽略 ``export `` 前缀，剥引号、去行内注释。"""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, _, val = line.partition("=")
        values[key.strip()] = _clean_value(val)
    return values


def audit_env(env_text: str) -> list[tuple[str, str, str]]:
    """拿一份 .env 文本对清单，返回问题列表 ``(tag, key, expected)``。

    tag ∈ {MISSING（缺键）, DIFF（取值不对）, EMPTY（占位项必须在场且有值）}。
    **只回结论、从不回值** —— 这个结果会被运维 CLI（``karma env-gates``）拿去核对
    生产 ``/opt/karma/.env``，所以这里绝不能把值带出来。
    """
    values = parse_env(env_text)
    problems: list[tuple[str, str, str]] = []
    for key, want in sorted(PRODUCTION_GATE_FLAGS.items()):
        got = values.get(key)
        if got is None:
            problems.append(("MISSING", key, want))
        elif got != want and got not in PRODUCTION_GATE_ALLOWED_VALUES.get(key, ()):
            problems.append(("DIFF", key, want))
    for key in sorted(PRODUCTION_GATE_PLACEHOLDERS):
        if not values.get(key):
            problems.append(("EMPTY", key, ""))
    return problems


def main(argv: list[str] | None = None) -> int:
    """``python -m config.production_gates < /opt/karma/.env``：TSV 报告 + 退出码。

    每行 ``TAG<TAB>KEY<TAB>EXPECTED``，最后一行 ``SUMMARY<TAB>flags=N placeholders=N
    problems=N``；有问题退出 1。``karma env-gates`` 就是拿这份 TSV 渲染给人看的。
    """
    import sys

    problems = audit_env(sys.stdin.read())
    for tag, key, want in problems:
        print("%s\t%s\t%s" % (tag, key, want))
    print("SUMMARY\tflags=%d placeholders=%d problems=%d"
          % (len(PRODUCTION_GATE_FLAGS), len(PRODUCTION_GATE_PLACEHOLDERS), len(problems)))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
