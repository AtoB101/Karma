#!/usr/bin/env bash
# Karma — VPS 首次初始化（以 root 运行一次）
# 安全基线：密钥登录、禁密码、防火墙只开 22/80/443、fail2ban、自动安全更新、swap
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "请用 root 运行"; exit 1; }

echo "==> [1/8] 系统更新"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq && apt-get upgrade -y -qq

echo "==> [2/8] 基础工具"
apt-get install -y -qq curl git ufw fail2ban unattended-upgrades ca-certificates gnupg jq

echo "==> [3/8] Docker"
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker

echo "==> [4/8] 防火墙（只开 22/80/443）"
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp   # 部署验证后可收紧为来源 IP
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

echo "==> [5/8] fail2ban（SSH 防暴破）"
systemctl enable --now fail2ban
cat > /etc/fail2ban/jail.local <<'EOF'
[sshd]
enabled = true
maxretry = 5
bantime = 1h
findtime = 10m
EOF
systemctl restart fail2ban

echo "==> [6/8] 自动安全更新"
dpkg-reconfigure -f noninteractive unattended-upgrades || true

echo "==> [7/8] swap（2G 内存机器防 OOM）"
if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "==> [8/8] 部署目录"
mkdir -p /opt/karma
cat > /opt/karma/.env.example <<'EOF'
# ===== Karma 生产环境变量（复制为 .env 后填写，chmod 600）=====
APP_SECRET_KEY=<64位随机串，用于会话/HMAC>
KARMA_TRUST_LEDGER_KEY=<64位随机串，信任台账 HMAC 密钥>
TELEGRAM_BOT_TOKEN=<bot token>
TELEGRAM_WEBHOOK_SECRET=<随机串>
APP_PUBLIC_URL=https://你的域名
KARMA_DOMAIN=你的域名
# 数据库（第3步数据层生产化启用）
POSTGRES_USER=karma
POSTGRES_PASSWORD=<强密码>
POSTGRES_DB=karma
DATABASE_URL=postgresql+asyncpg://karma:<密码>@postgres:5432/karma
REDIS_URL=redis://redis:6379/0
EOF
chmod 600 /opt/karma/.env.example

echo ""
echo "✅ 初始化完成。下一步："
echo "  1. ssh-keygen 生成部署密钥（或用现有公钥），写入 /home/deploy/.ssh/authorized_keys"
echo "  2. 修改 /etc/ssh/sshd_config: PasswordAuthentication no + PermitRootLogin no，然后 systemctl restart sshd"
echo "  3. cd /opt/karma && git clone <仓库地址> repo && cp deploy/vps/deploy.sh . && ./deploy.sh"
