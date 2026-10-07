#!/usr/bin/env bash
# Karma — VPS 应用部署/更新（在服务器 /opt/karma 下运行）
# 语义：拉最新代码 → 重建镜像 → 滚动重启 → 健康检查 → 幂等 setWebhook
set -euo pipefail

DEPLOY_DIR="/opt/karma"
REPO_DIR="${DEPLOY_DIR}/repo"
ENV_FILE="${DEPLOY_DIR}/.env"

[ -f "${ENV_FILE}" ] || { echo "缺少 ${ENV_FILE}（参考 .env.example）"; exit 1; }
cd "${REPO_DIR}"

echo "==> [1/5] 拉取最新代码"
git fetch origin
# `reset --hard` 会把工作树里所有本地改动一次性抹掉，而且一声不吭 —— 有人在盒子上
# 手工救过火的话，这就是一次静默的数据丢失。默认停下来看清楚，要用 --force 明确丢弃。
FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1
DIRTY="$(git status --porcelain | wc -l | tr -d ' ')"
if [ "${DIRTY}" != "0" ]; then
  echo "工作树里有 ${DIRTY} 处未提交改动，reset --hard 会把它们全部丢弃：" >&2
  git status --porcelain | sed 's/^/    /' >&2
  if [ "${FORCE}" != "1" ]; then
    echo "已停下。确认要丢弃就重跑：bash deploy/vps/deploy.sh --force" >&2
    echo "（想留着就先 git stash，或 git diff > /tmp/local-$(date +%F-%H%M%S).patch）" >&2
    exit 1
  fi
  echo "--force：按上面的清单丢弃。" >&2
fi
git reset --hard origin/main

echo "==> [2/5] 重建镜像并重启"
docker compose --env-file "${ENV_FILE}" -f deploy/docker-compose.yml up -d --build --remove-orphans

echo "==> [3/5] 健康检查（最长 120s）"
BASE_URL="${APP_PUBLIC_URL:-http://127.0.0.1}"
for i in $(seq 1 24); do
  if curl -fsS --max-time 5 "${BASE_URL}/health" >/dev/null 2>&1; then
    echo "health OK: ${BASE_URL}/health"
    break
  fi
  [ "$i" -eq 24 ] && { echo "健康检查失败"; docker compose -f deploy/docker-compose.yml logs --tail 50 app; exit 1; }
  sleep 5
done

echo "==> [4/5] 幂等 setWebhook（Telegram）"
# shellcheck disable=SC1090
set -a; . "${ENV_FILE}"; set +a
if [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_WEBHOOK_SECRET:-}" ]; then
  WEBHOOK_URL="${APP_PUBLIC_URL}/v1/telegram/bot/webhook"
  CURRENT="$(curl -fsS "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getWebhookInfo" | jq -r '.result.url // ""')"
  if [ "${CURRENT}" = "${WEBHOOK_URL}" ]; then
    echo "Webhook 已指向 ${WEBHOOK_URL}，跳过"
  else
    curl -fsS "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
      -d "url=${WEBHOOK_URL}" -d "secret_token=${TELEGRAM_WEBHOOK_SECRET}" >/dev/null
    echo "Webhook 已设置: ${WEBHOOK_URL}"
  fi
else
  echo "未配置 TELEGRAM_*，跳过 webhook"
fi

echo "==> [5/5] 完成"
docker compose -f deploy/docker-compose.yml ps

# 「脚本没报错」不等于「线上跑的就是这次提交」—— ci-deploy.sh 早就有这条自证，这里
# 之前只有一句 ps。同时把操作者敲的 /usr/local/bin/karma 对齐（首次部署后它可能压根
# 不存在，README 却已经让人用 karma 了）。
CLI_SRC="$(pwd)/deploy/karma"
if [ -f "${CLI_SRC}" ] && [ "$(id -u)" -eq 0 ]; then
  install -m 0755 "${CLI_SRC}" /usr/local/bin/karma
  echo "installed /usr/local/bin/karma"
fi

EXPECTED="$(git rev-parse origin/main)"
ACTUAL="$(git rev-parse HEAD)"
if [ "${ACTUAL}" != "${EXPECTED}" ]; then
  echo "部署后校验失败：HEAD=${ACTUAL}，origin/main=${EXPECTED}" >&2
  exit 1
fi
echo "deployed revision verified: ${ACTUAL}"
