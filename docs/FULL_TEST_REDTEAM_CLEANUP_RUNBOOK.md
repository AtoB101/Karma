# 全量测试 + 红队测试 + 仓库清理 操作手册

本手册是 Karma 仓库「一次性把测试跑全、把安全面扫一遍、把建筑垃圾清干净」的标准操作流程（SOP）。
每步都给出：**命令** → **预期结果** → **失败时怎么查**。全部命令以仓库根目录为工作目录执行。

> 环境约定
> - Windows PowerShell；合约工具 Foundry `forge` 版本 v1.7.1（`C:\Users\Administrator\.foundry\bin\forge.exe`）。
> - 合约用 solc `0.8.24`（`C:\Users\Administrator\AppData\Roaming\svm\0.8.24\solc-0.8.24`）。
> - 合约测试必须从**仓库根目录**执行（根 `foundry.toml` 的 `src=karma-core/contracts/core`），
>   不要 `cd` 进 `karma-core/contracts` 用里面的嵌套配置，否则会撞上 via_ir 的 Yul「stack too deep」。
> - Python 测试用 `python -m pytest`（版本 8.x + pytest-asyncio）。

---

## Part 1 全量测试

### 1.1 合约全量测试（Forge）

```powershell
$env:HOME='C:\Users\Administrator'
$env:USERPROFILE='C:\Users\Administrator'
Remove-Item Env:FOUNDRY_CACHE -ErrorAction SilentlyContinue
$env:FOUNDRY_CACHE_PATH="$env:TEMP\karma-main\.cache"
C:\Users\Administrator\.foundry\bin\forge.exe test --use "C:\Users\Administrator\AppData\Roaming\svm\0.8.24\solc-0.8.24"
```

- **预期**：`Ran 18 test suites ... 303 tests passed, 0 failed, 0 skipped`。
- **失败排查**：若出现 `Yul exception ... stack too deep`，说明用错了 solc 或用了嵌套
  `karma-core/contracts/foundry.toml`；改回根目录 + `--use` 指定 0.8.24。

### 1.2 Python 全量测试（pytest）

```powershell
python -m pytest tests/ -q --tb=short
# 以及 Makefile 里的 karma-openclaw 冒烟
python -m pytest packages/karma-openclaw/tests -q --tb=short
```

- **预期**：`tests/` 约 2500+ 条，全部通过（CI 口径 2676 passed）。本地首次运行较慢
  （SQLite 异步引擎冷启动），单测全量约 20~30 分钟，属正常。
- **注意**：部分集成测试会访问链上/外部服务；本地无外网时会超时，以 CI（GitHub Actions
  `python-tests.yml`）结果为准。

---

## Part 2 红队全量测试

### 2.1 合约对抗测试（Forge adversarial）

以下文件属于安全/对抗面，已被 1.1 的全量 `forge test` 覆盖：

- `karma-core/contracts/test/FinancialInvariants.t.sol`（资金不变量）
- `karma-core/contracts/test/OffchainCompromise.t.sol`（链下私钥泄露威胁模型）
- `karma-core/contracts/test/KarmaBilateralAdvanced.t.sol`（重入 / 越权 / 状态机）
- `karma-core/contracts/test/VerifierRegistryAccessControl.t.sol`（验证者权限）
- `karma-core/contracts/test/CircuitBreaker.t.sol`（熔断）

只跑对抗面（可选）：

```powershell
C:\Users\Administrator\.foundry\bin\forge.exe test --use "C:\Users\Administrator\AppData\Roaming\svm\0.8.24\solc-0.8.24" \
  --match-path "karma-core/contracts/test/{FinancialInvariants,OffchainCompromise,KarmaBilateralAdvanced,VerifierRegistryAccessControl,CircuitBreaker}.t.sol"
```

### 2.2 Python 对抗测试（adversarial packs）

```powershell
python -m pytest tests/unit/test_adversarial_p1_p8.py tests/unit/test_adversarial_whole_project.py -q --tb=short
```

其余安全相关单测（被 1.2 全量覆盖）：`test_*_security*.py`、`test_level2_attack_mitigations.py`、
`test_platform_privilege_boundaries.py`、`test_wash_trade.py` 等。

### 2.3 静态规则审计

```powershell
python scripts/acceptance/reverse_rule_audit.py
```

- **预期**：`REVERSE RULE AUDIT: PASS`。

Bash 类守卫（`scripts/security-baseline-guard.sh`、`scripts/ci-proof-gates.sh`、
`scripts/public-beta-security-gate.sh`、`scripts/visibility-guard.sh`）只能在 Linux CI 跑，
本地 Windows 无 bash，由 `.github/workflows/security-ci.yml` / `security-baseline-guard.yml` 把关。

### 2.4 密钥/凭证扫描（red-team 核心）

```powershell
# 真实私钥：0x + 64 位十六进制
rg -n --no-heading "0x[0-9a-fA-F]{64}" -g '!lib/**' -g '!**/lib/**' -g '!node_modules/**' .
# RPC / API key
rg -n --no-heading -i "infura|alchemy|api[_-]?key|access[_-]?token" -g '!lib/**' -g '!**/lib/**' -g '!node_modules/**' .
# 已提交的敏感文件（env / key / pem / keystore）
git ls-files | rg -i '(^|/)(\.env[^/]*|.*\.pem$|.*\.key$|keystore|keys?/)'
```

- **预期**：以上对真实私钥 / Infura key 的扫描**零命中**。

### 2.5 本次红队发现与处置

| 发现 | 严重度 | 处置 |
|---|---|---|
| 水龙头管理员私钥（Sepolia）硬编码于 `scripts/faucet.py` 等 | 高 | 改为 `FAUCET_KEY` 环境变量；**必须轮换**（历史已含该私钥） |
| 3 个 Sepolia 测试网私钥（W1/W2/W3）散落 10 个文件 + `telegram_miniapp/index.html` | 高 | 改为 `SEPOLIA_ADMIN_KEY` / `SEPOLIA_BUYER_KEY` / `SEPOLIA_AGENT_KEY`；**必须轮换** |
| Infura API key 明文硬编码于 5 个脚本 | 中 | 改为 `SEPOLIA_RPC`；**必须到 Infura 后台作废并换新** |
| Anvil 默认私钥（公开测试密钥）在 4 个本地 demo 脚本 | 低 | 保留（公开 dev fixture），已注明 |

> 轮换说明见 `docs/KEY_ROTATION.md`。因为私钥/API key 已进入 git 历史，仅从 HEAD 删除不够，
> 必须作废旧值并换新，否则历史泄露仍可被利用。

---

## Part 3 建筑垃圾清理

### 3.1 本次已清理

- 删除死子模块 `contracts/lib/forge-std`（迁移到 `karma-core/contracts/` 之前的遗留，CI 不使用）。
- 删除跟踪中的备份文件 `karma-core/contracts/test/KarmaIntentPackage.t.sol.bak`。
- 停止跟踪构建产物 `packages/sdk/dist/index.js`、`packages/sdk/dist/index.d.ts`。
- 清理 10 个文件里的硬编码私钥/API key（见 2.5）。

### 3.2 `.gitignore` 新增规则

```text
.cache/
karma-core/contracts/lib/
packages/sdk/dist/
*.bak
```

### 3.3 保持干净的检查

```powershell
git status --short   # 不应出现 .cache/、karma-core/contracts/lib/、*.bak、sdk/dist
git ls-files | rg -i '(^|/)(\.env[^/]*|.*\.pem$|.*\.key$|keystore|keys?/)'   # 仅 .env.example
```

---

## 附录：新增必需环境变量

| 变量 | 用途 | 原硬编码值去向 |
|---|---|---|
| `FAUCET_KEY` | 水龙头管理员私钥 | 已从 `scripts/faucet.py` 移除 |
| `SEPOLIA_RPC` | Sepolia RPC URL | 替换 5 处 Infura key |
| `SEPOLIA_ADMIN_KEY` | 仲裁/管理员测试私钥 | 已移除 |
| `SEPOLIA_BUYER_KEY` | 买方测试私钥 | 已移除 |
| `SEPOLIA_AGENT_KEY` | 卖方/agent 测试私钥 | 已移除 |

运行相关脚本前请 `export` 上述变量（值用你自己的新密钥，勿再回填旧值）。
