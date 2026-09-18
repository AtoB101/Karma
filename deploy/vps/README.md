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

需要 repo Secrets：`VPS_HOST` / `VPS_SSH_USER` / `VPS_SSH_KEY`，
以及 repo Variable `VPS_DEPLOY_ENABLED=true`（不设就只跑单测，deploy 那步跳过）。

`deploy-vps.yml`：单测 + import 冒烟 → SSH 执行
`/opt/karma/repo/deploy/vps/ci-deploy.sh` 滚动更新。

那个脚本内部调 `karma deploy`：拉代码 → 发布静态站与操作台 → 重建容器（**不 build**）
→ 健康检查，并自动备份 webroots 到 `/opt/karma/backups/`。
不用 `deploy/vps/deploy.sh` 是因为它会 `--build` 重建镜像 —— 1.6G 的机器上太慢，
而生产代码是 bind mount 进容器的，改代码不需要重新构建镜像。

## 域名要求

Telegram webhook 强制 HTTPS，需要一个域名解析到服务器（Caddy 自动签发 Let's Encrypt）。

## 安全基线（bootstrap.sh 已含）

- 防火墙只开 22/80/443
- fail2ban 防 SSH 暴破
- 自动安全更新
- `.env` 权限 600，机密永不入库
- 部署验证后：SSH 禁密码登录、禁 root 登录
