# Phase 3 — AP2 / PaymentIntent 验收清单

## 自动化门

```bash
bash scripts/acceptance/phase3_ap2_gate.sh
```

## 交付物核对

| # | 项 | 路径 | 状态 |
|---|-----|------|------|
| 3.1 | 字段映射文档 | `docs/AP2_EVIDENCE_PROFILE-zh.md` | ☑ |
| 3.2 | AP2 适配器 | `trusted_agent_runtime/ap2_adapter.py` | ☑ |
| 3.3 | SD-JWT 导出 | `services/evidence_export.py` | ☑ |
| 3.4 | Payment Intent API | `api/routes/payment_intents.py` | ☑ |
| 3.5 | Human-not-present | `human_not_present_allowed` + `services/human_not_present_policy.py` | ☑ |
| 3.6 | 外部验证 | `POST /v1/evidence/{id}/verify-external` | ☑ |

## 验收标准（路线图 §6.2）

- [x] 单测：bundle ↔ AP2 JSON 往返（`tests/unit/test_ap2_adapter.py`）
- [x] 集成：PaymentIntent 创建 → 绑定 task → settlement 同步 `settled`（`tests/integration/test_phase3_payment_intent.py`）
- [x] SD-JWT 公开验证命令（见 `docs/AP2_EVIDENCE_PROFILE-zh.md` §6）
- [x] `docs/API_ROADMAP_V01.md` M5 状态更新

## 手动冒烟（可选）

1. 提交 evidence bundle → `POST /v1/evidence/{bundle_id}/export-ap2` 获取 mandate + SD-JWT  
2. `POST /v1/evidence/{bundle_id}/verify-external` 传入 `ap2_mandate`  
3. 创建 PaymentIntent → bind `taskId` → 跑 settlement 至 SETTLED → GET intent 为 `settled`
