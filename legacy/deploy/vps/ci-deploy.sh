#!/usr/bin/env bash
# Karma — CI 自动部署入口（GitHub Actions 通过 SSH 调用）。
#
# 为什么不用 deploy/vps/deploy.sh：那是首次/完整部署，会 `up -d --build` 重建镜像。
# 这台机器只有 1.6G 内存，编译一次要很久，push 一次就编译一次不现实。
# 生产上的代码是 bind mount 进容器的，所以这里走 `karma deploy`：
#   拉代码 → 跑数据库迁移 → 发布静态站与操作台 → 重建容器（不 build）→ 健康检查。
#
# 必须在服务器上 /opt/karma/repo 这份检出里执行；脚本自己会切过去。
#
# CI 侧调用它的 SSH key 是**带 forced command 的**（见 docs/DEPLOY_PIPELINE.md）：
# 这把 key 只能触发这个脚本，拿不到 shell。所以这里不做任何交互。
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

bash "${CLI}" deploy

# --------------------------------------------------------------------------
# 安装副本同步
# --------------------------------------------------------------------------
# 操作者敲的 /usr/local/bin/karma 和 CI 跑的仓库那份必须一致：不一致时新命令在机器上
# 根本不存在（2026-10-08 就是这样，安装副本还是 9 月的构建，连 env-gates 都没有）。
# deploy/karma 里的 sync_cli 也会同步，但它本身就是**被 git pull 改写的那份脚本**，
# 靠不住（bash 会带着旧偏移继续解析，实测见 reexec_if_cli_changed 的注释）。这个文件
# 由 ci-deploy-entry.sh 拷到临时文件后执行，不会被改写，所以在这里兜底 —— 而且漂移
# 没能修好就红，不再有「静默的绿」。
INSTALLED_CLI=/usr/local/bin/karma
if [ -f "${INSTALLED_CLI}" ] && ! cmp -s "${CLI_SRC}" "${INSTALLED_CLI}"; then
  if install -m 0755 "${CLI_SRC}" "${INSTALLED_CLI}"; then
    echo "refreshed ${INSTALLED_CLI} from deploy/karma"
  else
    echo "无法刷新 ${INSTALLED_CLI}（与 deploy/karma 不一致）" >&2
    exit 1
  fi
fi

# --------------------------------------------------------------------------
# 部署后自证
# --------------------------------------------------------------------------
# 「脚本没报错」不等于「线上跑的就是这次提交」。以前这里 `exec` 掉自己，
# 跑完就没了下文，CI 绿了但没人证明服务器真的换了版本。现在补上：
#   1. HEAD 必须等于刚 fetch 到的 origin/main（拉取真的生效了）；
#   2. 已跟踪文件不能有未提交改动（否则线上跑的代码不在任何提交里，回滚无从谈起）。
# 未跟踪文件只提醒不拦：部署过程本身会生成一些。
EXPECTED="$(git rev-parse origin/main 2> /dev/null || true)"
ACTUAL="$(git rev-parse HEAD 2> /dev/null || true)"
if [ -z "${EXPECTED}" ] || [ -z "${ACTUAL}" ]; then
  echo "部署后校验失败：拿不到 origin/main 或 HEAD" >&2
  exit 1
fi
if [ "${ACTUAL}" != "${EXPECTED}" ]; then
  echo "部署后校验失败：HEAD=${ACTUAL}，origin/main=${EXPECTED}" >&2
  echo "（拉取没生效，或者本地被改到了别的提交上）" >&2
  exit 1
fi
if ! git diff --quiet; then
  echo "部署后校验失败：/opt/karma/repo 里有未提交的已跟踪改动" >&2
  git diff --stat >&2
  exit 1
fi
if [ -n "$(git status --porcelain --untracked-files=normal | grep '^??' || true)" ]; then
  echo "部署后提醒：工作树里有未跟踪文件（不拦部署）" >&2
fi
echo "deployed revision verified: ${ACTUAL}"