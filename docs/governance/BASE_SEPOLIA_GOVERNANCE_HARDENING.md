# Base Sepolia 治理加固（2-of-3 多签 + 1h 延迟）

## 为什么这是最致命的一项

Base Sepolia 线上 `AdminTimelock` 长期处于部署脚本的「引导态」：

- `ownerCount = 1`，唯一 owner 是部署者 EOA `0x79BFfa6fF14B0b0e6766AB6A29d210f56E76336e`
- `threshold = 1`
- `minDelay = 0`

也就是说，协议 admin（Bilateral / Registry / Evidence / Scoring / Breaker / Freeze / ReputationAnchor / FeeBridge / Gateway 全部指向它）实际被一把私钥控制，且任何改动即时生效、无延迟。这等价于单钥治理——此前源码里的多签与证据约束全部「存在但未上线」。

## 已完成（2026-11-17，Base Sepolia 84532）

通过时间锁自身的 `schedule + execute` 执行了 `reconfigure`，把线上治理升级为：

- owners：`[0x79BF…, 0x47D7…, 0x9DE9…]`（3 个）
- threshold：`2`（2-of-3）
- minDelay：`3600`（1 小时）

交易：

- schedule：`0x692461b51a84f24178aa342cdc32a06a343e4e12aa63cf0da3d1870782e2533a`
- execute：`0x631f17e288232f34006d1f6d82801321d7c9e85c32d3382722841ff0a6ae00cb`

修复前先在本机 `anvil --fork-url https://sepolia.base.org` 上用同一份 calldata 完整走通并校验，再上真实链，结果一致。

## Owner 私钥托管（重要）

- `0x79BF…`：部署者 EOA，私钥在服务器 `/opt/karma/.env` 之外由你本人保管（此前你给过该 key）。
- `0x47D7…`、`0x9DE9…`：本次新生成的 2 个多签 key，私钥在本仓库根目录 `.env.base-sepolia-owners`（已被 `.gitignore` 忽略，绝不提交）。

**必须立刻把 `.env.base-sepolia-owners` 里的两把私钥搬进密码管理器 / 硬件钱包，然后删除该文件。** 2-of-3 的意义是任何一把泄露都不致命；但三把都放在同一台机器上等于回到单点。

## 后续治理操作方式

minDelay=3600、threshold=2 之后，任何 admin 参数变更都需要：

1. 任一 owner 调 `schedule(target, value, data)` 并自动自批一票；
2. 第二个 owner 调 `approve(id)`；
3. 至少等 1 小时后，任何人可调 `execute(id)`。

## 仍未恢复的测试网时序参数

线上仍为 e2e 演示用的短窗口：`settleDelaySeconds=60`、`evidenceWindow=60`、`settleTimeoutSeconds=60`、`optimisticDisputeWindow=120`。这是测试网故意压短以加速演示，对测试网可接受；但 `evidenceWindow`（源码默认 72h）与 `optimisticDisputeWindow`（源码默认 24h）只有 admin 能改，而 admin 现在是多签+延迟，泄露到主网的路径已被堵死。

`DISPUTE_WINDOW`（实为 settle delay）、`SETTLE_TIMEOUT`、`CHALLENGE_WINDOW` 是部署脚本的 env 驱动参数，本次已在 `DeployKarmaBilateral.s.sol` 的 MAINNET GUARD 中加了最小值校验，防止部署者用 60 秒这类演示值上主网。

## 验证

见 `scripts/ops/verify-base-sepolia-governance.ps1`。期望输出：

```text
ownerCount = 3
threshold  = 2
minDelay   = 3600
owners[0]  = 0x79BFfa6fF14B0b0e6766AB6A29d210f56E76336e
owners[1]  = 0x47D782e14E444AADD806912b1119516C95E89e7c
owners[2]  = 0x9DE93aD8eBc00484E110652c9E35Cb302aad579b
```
