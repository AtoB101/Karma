# Karma — VPS 部署指南

## 架构

```
用户/TG/Agent ──HTTPS──> Caddy(自动证书) ──> karma-api(uvicorn)
                                              ├─ postgres（第3步数据层启用）
                                              └─ redis（限流后端）
```

## 首次部署（服务器上以 root 运行一次）

```bash
bash deploy/vps/bootstrap.sh   # Docker + 防火墙(22/80/443) + fail2ban + swap
```

## 应用部署

1. 服务器上：`git clone <仓库> /opt/karma/repo`
2. `cp /opt/karma/.env.example /opt/karma/.env` 并填写机密（chmod 600）
3. `bash deploy/vps/deploy.sh`（拉代码 → 重建镜像 → 健康检查 → 幂等 setWebhook）

## CI 自动部署（push 到 main）

GitHub repo Secrets 配置：`VPS_HOST` / `VPS_SSH_USER` / `VPS_SSH_KEY`。
`deploy-vps.yml`：单测 + import 冒烟 → SSH 执行 `/opt/karma/deploy.sh` 滚动更新。

## 域名要求

Telegram webhook 强制 HTTPS，需要一个域名解析到服务器（Caddy 自动签发 Let's Encrypt）。

## 安全基线（bootstrap.sh 已含）

- 防火墙只开 22/80/443
- fail2ban 防 SSH 暴破
- 自动安全更新
- `.env` 权限 600，机密永不入库
- 部署验证后：SSH 禁密码登录、禁 root 登录
