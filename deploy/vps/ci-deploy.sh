#!/usr/bin/env bash
# Karma — CI 自动部署入口（GitHub Actions 通过 SSH 调用）。
#
# 为什么不用 deploy/vps/deploy.sh：那是首次/完整部署，会 `up -d --build` 重建镜像。
# 这台机器只有 1.6G 内存，编译一次要很久，push 一次就编译一次不现实。
# 生产上的代码是 bind mount 进容器的，所以这里走 `karma deploy`：
#   拉代码 → 发布静态站与操作台 → 重建容器（不 build）→ 健康检查。
#
# 必须在服务器上 /opt/karma/repo 这份检出里执行；脚本自己会切过去。
set -euo pipefail

REPO_DIR="/opt/karma/repo"
CLI_SRC="${REPO_DIR}/deploy/karma"

[ -d "${REPO_DIR}" ] || { echo "缺少 ${REPO_DIR}（先按 deploy/vps/README.md 首次部署）"; exit 1; }
cd "${REPO_DIR}"

# 仓库里的 CLI 是唯一事实来源；旧版本装在 /usr/local/bin，这里以仓库版本为准。
if [ -f "${CLI_SRC}" ]; then
  CLI="${CLI_SRC}"
elif command -v karma >/dev/null 2>&1; then
  CLI="$(command -v karma)"
else
  echo "找不到 karma CLI（既没有 ${CLI_SRC}，也不在 PATH 里）"; exit 1
fi

exec bash "${CLI}" deploy
