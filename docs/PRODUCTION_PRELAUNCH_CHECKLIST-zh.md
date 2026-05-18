# 生产前检查清单（公开 API / PaaS）

在测试网全链路验收（如 `reports/testnet-pre-auth-*.md`）通过后，上线生产前执行本清单。

## 1. 环境变量（`deploy/.env.paas.example`）

| 变量 | 生产值 |
|------|--------|
| `APP_ENV` | `production` |
| `RECEIPT_REQUIRE_SIGNATURE` | `true`（启动时校验，不可为 false） |
| `AUTH_ENFORCE_PROTECTED_ROUTES` | `true` |
| `LEDGER_REQUIRE_PARTY_ACTOR` | `true` |
| `SETTLEMENT_REQUIRE_PARTY_ACTOR` | `true` |
| `RUNTIME_REQUIRE_*` | 见 example 全部为 `true` |
| `RATE_LIMIT_REDIS_FAIL_CLOSED` | `true` |
| `TRADE_LAUNCH_REQUIRE_EIP712` | `true` |
| `KARMA_SIGNING_BACKEND` | `client_only` 或 `external` |

```bash
./scripts/production-prelaunch-gate.sh /path/to/production.env
```

## 2. 收据签名

- 默认 `RECEIPT_REQUIRE_SIGNATURE=true`；测试网若曾关闭，**生产必须开启**。
- 无签名收据 → `POST /v1/receipts` 在 guard 层拒绝。

## 3. 自动化测试

```bash
python3 -m pytest tests/unit/test_production_settings_gates.py \
  tests/unit/test_production_receipt_signature.py -q
```

## 4. Karma2 manifest（私有仓）

- `CORE_COMMIT=ee68f62d3c3f2f0cda3ee1b3d3b6c375c9997b9a`
- `deployment-manifest.json` 中 **禁止** 零地址（`verify-manifest.sh` 在 `environment=sepolia` 时会拒绝 `0x000…000`）
- 填入链上真实 `settlementEngine` / `nonCustodialAgentPayment`

## 5. 数据库

```bash
alembic upgrade head   # 至 0025_trade_pipeline_security
```

## 6. 签核

- [ ] `production-prelaunch-gate.sh` 通过  
- [ ] `public-beta-security-gate.sh` 通过（配置 on-call）  
- [ ] Sepolia / 生产 smoke 已归档  
