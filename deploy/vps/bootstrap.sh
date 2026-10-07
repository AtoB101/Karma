#!/usr/bin/env bash
# Karma — VPS 首次初始化（以 root 运行一次）
# 安全基线：密钥登录、禁密码、防火墙只开 22/80/443、fail2ban、自动安全更新、swap
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "请用 root 运行"; exit 1; }

# 脚本头部声称的安全基线，最后要逐条核对；对不上就不许报「完成」。
BASELINE_OK=1

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

echo "==> [4/8] 防火墙（只开 SSH/80/443）"
# ufw --force reset 会清掉全部规则。如果 sshd 不在 22 端口，接下来这一串会把运维
# 直接关在门外 —— 所以按 sshd 的**实际**端口放行，而不是硬编码 22。
SSH_PORT="$(sshd -T 2>/dev/null | awk '/^port /{print $2; exit}')"
SSH_PORT="${SSH_PORT:-22}"
[ "${SSH_PORT}" = "22" ] || echo "注意：sshd 实际监听 ${SSH_PORT}，按实际端口放行"
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow "${SSH_PORT}/tcp"   # 部署验证后可收紧为来源 IP
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
if ! dpkg-reconfigure -f noninteractive unattended-upgrades; then
  echo "警告：dpkg-reconfigure unattended-upgrades 失败，继续核对它到底有没有生效" >&2
fi
if systemctl is-enabled --quiet unattended-upgrades 2>/dev/null \
   && systemctl is-active --quiet unattended-upgrades 2>/dev/null; then
  echo "unattended-upgrades: enabled + active"
else
  echo "警告：unattended-upgrades 没在跑 —— 自动安全更新等于没开" >&2
  BASELINE_OK=0
fi

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

# 头部写了「密钥登录、禁密码」，但这个脚本从来没核对过 —— 只打印一句提示就当完成。
# 没做的话，机器就是带着密码登录 + root 密码登录挂在公网上，而运维以为已经收紧了。
echo ""
echo "==> 安全基线核对（看 sshd -T 的**实际生效值**，不是配置文件里写了什么）"
SSH_CONF="$(sshd -T 2>/dev/null || true)"
if [ -z "${SSH_CONF}" ]; then
  echo "警告：sshd -T 读不到有效配置，无法确认安全基线" >&2
  BASELINE_OK=0
else
  for k in passwordauthentication permitrootlogin pubkeyauthentication; do
    v="$(printf '%s\n' "${SSH_CONF}" | awk -v k="${k}" 'tolower($1)==k {print $2; exit}')"
    printf '  %-24s %s\n' "${k}:" "${v:-未设置}"
  done
  printf '%s\n' "${SSH_CONF}" | grep -qi '^passwordauthentication yes' \
    && { echo "未达标：PasswordAuthentication 还是 yes（密码可被暴力破解）" >&2; BASELINE_OK=0; }
  printf '%s\n' "${SSH_CONF}" | grep -qi '^permitrootlogin yes' \
    && { echo "未达标：PermitRootLogin 还是 yes（root 可密码登录）" >&2; BASELINE_OK=0; }
  printf '%s\n' "${SSH_CONF}" | grep -qi '^pubkeyauthentication no' \
    && { echo "未达标：PubkeyAuthentication 是 no（密钥登录被关了）" >&2; BASELINE_OK=0; }
fi

if [ "${BASELINE_OK}" != "1" ]; then
  echo "" >&2
  echo "❌ 初始化没达到脚本头部声称的安全基线（具体项见上）。修法：" >&2
  echo "  1. 确认 deploy key 的公钥已写进 authorized_keys" >&2
  echo "  2. /etc/ssh/sshd_config.d/99-karma.conf 写：PasswordAuthentication no / PermitRootLogin prohibit-password" >&2
  echo "  3. sshd -t && systemctl restart sshd —— 改完**另开一个终端**用 key 登录确认，再关掉旧会话" >&2
  exit 2
fi

echo ""
echo "✅ 初始化完成（安全基线已核对）。下一步："
echo "  1. cd /opt/karma && git clone <仓库地址> repo"
echo "  2. bash repo/deploy/vps/deploy.sh（首次会重建镜像；之后的更新走 CI 的 ci-deploy.sh 或 karma deploy）"
