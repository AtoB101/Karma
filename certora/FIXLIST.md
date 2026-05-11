# Certora 修复清单（与仓库配置对齐）

| # | 位置 | 问题 | 修复 |
|---|------|------|------|
| 1 | `certora/conf/*.conf` | `solc8.28` 等短名在 Certora 云上可能不可用 | 使用 `"/usr/local/bin/solc"`（与云上默认布局一致）；本机若无该路径，用 `solc-select`/`foundry` 安装后 symlink，或改 conf 中 `solc` 为本地绝对路径 |
| 2 | `certora/conf/*.conf` | 与 Foundry `via_ir = true` 不一致 | 设置 `"solc_via_ir": true` |
| 3 | `certora/specs/AuthTokenManager.spec` | `import Types.sol` 在部分运行根目录下断裂 | 已移除 import；`Types.OperationType` 由编译场景提供 |
| 4 | `scripts/certora-verify.sh` | 部分 CLI 不支持 `--conf`，且参数顺序易错 | 使用 `certoraRun "${conf}" "$@"`（配置文件作首个位置参数） |
| 5 | `certora/specs/NonCustodialAgentPayment.spec` | 类型/别名 | 保持当前 CVL2 版本（勿使用实例名作类型前缀） |
| 6 | `certora/specs/SettlementEngine.spec` | 无 EIP-712 `Quote` / `submitSettlement` 规则 | **有意为之**：降低工具链差异；详见 `certora/README.md`「SettlementEngine 范围」 |
| 7 | 运行环境 | 类型检查 / Java | Certora 建议 **Java 21+**；若本地类型检查阻塞，可在确认风险后使用官方文档中的 **`--disable_local_typechecking`**（不推荐作为长期默认） |
| 8 | 报告 INFO | `onlyAdminWithdraw` / `optimistic_fallback` | 指 **`admin()`** 零参调用的摘要策略提示；**非失败**。`KYARegistry.conf` 已加 **`optimistic_fallback`**；也可用 **`CERTORA_EXTRA_ARGS`** 传给 `certora-verify.sh` |
