#!/usr/bin/env bash
#
# Karma 一键本地开发启动脚本
#
# 用法:
#   ./scripts/dev.sh up      启动本地开发栈（venv + Redis + API + Worker + 操作台）
#   ./scripts/dev.sh down    停止本地开发栈
#   ./scripts/dev.sh reset   停止 + 删除 venv，回到干净状态
#
# 说明:
#   - 本地开发默认用 SQLite（.env 里 DATABASE_URL），API 启动时自动 create_all 建表，
#     无需手动跑 alembic（alembic 只用于生产 PostgreSQL）。
#   - 首次运行会自动创建 .venv 并安装依赖。
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info() { echo -e "${GREEN}[karma]${NC} $*"; }
warn() { echo -e "${YELLOW}[karma]${NC} $*"; }
err()  { echo -e "${RED}[karma]${NC} $*"; }

PY="${PYTHON:-python3}"
VENV="$ROOT/.venv"

require() {
  command -v "$1" >/dev/null 2>&1 || { err "缺少依赖命令: $1（请先安装）"; exit 1; }
}

setup_venv() {
  if [ ! -d "$VENV" ]; then
    info "创建虚拟环境 $VENV ..."
    "$PY" -m venv "$VENV"
  fi
  # shellcheck disable=SC1091
  source "$VENV/bin/activate"
  info "安装/同步依赖 (pip install -e .[dev]) ..."
  pip install -q -U pip
  pip install -q -e ".[dev]"
}

ensure_env() {
  if [ ! -f "$ROOT/.env" ]; then
    warn "未找到 .env，从 .env.example 复制一份（如需本地 SQLite，请把 DATABASE_URL 改成 sqlite+aiosqlite:///./karma_dev.db）"
    cp "$ROOT/.env.example" "$ROOT/.env"
  fi
}

start_redis() {
  if command -v redis-cli >/dev/null 2>&1 && redis-cli ping >/dev/null 2>&1; then
    info "Redis 已在运行"
  else
    require redis-server
    info "启动 Redis ..."
    redis-server --daemonize yes --port 6379
    sleep 1
  fi
}

up() {
  require "$PY"
  ensure_env
  setup_venv
  start_redis

  info "启动 Celery worker ..."
  celery -A worker.tasks worker --loglevel=INFO --pool=solo &
  WORKER_PID=$!

  info "启动 API (uvicorn 0.0.0.0:8000) ..."
  uvicorn api.app:app --host 0.0.0.0 --port 8000 --reload &
  API_PID=$!

  info "启动操作台 (静态服务 127.0.0.1:8787) ..."
  (cd "$ROOT/apps/console" && "$PY" -m http.server 8787 --bind 127.0.0.1) &
  CONSOLE_PID=$!

  echo ""
  info "=============================================="
  info "  本地开发栈已启动"
  info "  API    : http://127.0.0.1:8000  (/health)"
  info "  操作台 : http://127.0.0.1:8787/pages/cyber/index.html"
  info "  Worker : PID $WORKER_PID"
  info "  停止   : Ctrl+C 或 ./scripts/dev.sh down"
  info "=============================================="
  echo ""

  trap 'info "停止服务..."; kill "$API_PID" "$WORKER_PID" "$CONSOLE_PID" 2>/dev/null || true' INT TERM
  wait
}

down() {
  warn "停止本地开发栈 ..."
  pkill -f "uvicorn api.app:app" 2>/dev/null || true
  pkill -f "celery -A worker.tasks" 2>/dev/null || true
  pkill -f "http.server 8787" 2>/dev/null || true
  info "已停止"
}

reset() {
  down
  rm -rf "$VENV"
  info "已清理 .venv，重新运行 ./scripts/dev.sh up 即可"
}

case "${1:-up}" in
  up)    up ;;
  down)  down ;;
  reset) reset ;;
  *)     echo "用法: $0 [up|down|reset]"; exit 1 ;;
esac
