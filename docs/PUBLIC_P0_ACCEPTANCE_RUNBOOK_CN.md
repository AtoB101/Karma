# Public P0 验收 Runbook（CN）

用于验证公开仓库 12 项交付中的 P0 基线是否可用。

## 一键命令

```bash
bash scripts/public-p0-acceptance.sh
```

## 脚本覆盖项

1. 关键交付文件存在性检查（合约、SDK、文档、回执 schema、审计报告）。
2. Public 边界安全守卫：
   - `scripts/check-trust-engine-public-safety.sh`
   - `scripts/security-baseline-guard.sh`
3. 关键测试：
   - `tests/unit/test_sdk_adapters.py`
   - `tests/unit/test_sdk_client_public.py`
   - `tests/integration/test_api.py`
4. 可选合约 smoke（本机有 forge 时执行）。

## 通过标准

- 脚本输出 `OK   public P0 acceptance passed`
- 无 `ERR` 输出

