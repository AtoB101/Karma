# Console 最后一公里 — 前后端真实交互

> 静态 Console（`apps/console/`）已接通 Karma HTTP API：读状态轮询 + 写操作按钮。

## 快速启动

```bash
# 1. API（示例：本机 8000）
cd /path/to/Karma && uvicorn api.app:app --reload --port 8000

# 2. 静态 Console
python3 -m http.server 8787
# 打开 http://127.0.0.1:8787/apps/console/index.html

# 3. 配置（复制示例）
cp apps/console/config.example.js apps/console/config.js
# 编辑 KARMA_API_BASE、KARMA_BFF_PUBLIC_BASE、API Key
```

## 页面与能力

| 页面 | 读（轮询） | 写（按钮） |
|------|------------|------------|
| Overview | health、capacity、tasks、safety | Test API |
| Payments | 同上 | 锁仓、release、settlement pending/lock、accept、dispute |
| Receiving | 同上 | start、submit、evidence、transitions |
| Trade | — | 付款码、预授权、launch order |
| Evidence | bundles | 查看/复制 hash/导出 JSON |
| Disputes | disputed 过滤 | 开争议、查看 settlement |

## 脚本分层

- `console-bootstrap.js` — localStorage + 默认 API base
- `karma-public-api.js` — 统一 `cyberKarmaApi`（读 + 写）
- `console-sync.js` — 10s 轮询、任务表点击选中
- `console-actions.js` — `data-console-action` 按钮
- `console-connect.js` — Test API / JWT 交换
- `console-trade.js` — 交易页（调用同一 client）

## 验收

```bash
bash scripts/acceptance/console_last_mile_gate.sh
```

上线前另跑：`full_chain_audit_gate.sh`、`testnet_claw_manus_gate.sh`（live API）。

## CORS

浏览器直连 API 时设置 `CORS_ALLOW_ORIGINS` 包含 Console 源，或同源反代 Console + `/v1`。
