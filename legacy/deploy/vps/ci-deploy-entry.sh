#!/bin/sh
# Karma — CI 部署入口（装在 /usr/local/bin/karma-ci-deploy，root:root 755）。
#
# 这个文件在仓库之外，是**故意的**：
#   1. authorized_keys 里那条被限制的 key 用 command="..." 指向它，而仓库会被
#      git pull 覆盖 —— 让 sshd 指向一个会被部署过程改写的东西不是好主意；
#   2. 真正的部署逻辑（deploy/vps/ci-deploy.sh）留在仓库里，跟着代码一起评审。
#
# 它多做一件事：把 ci-deploy.sh 拷到临时文件再执行。因为 ci-deploy.sh 里第一步
# 就是 `git pull`，会把它自己就地换掉 —— 正在执行的脚本被改写是经典的自伤写法。
#
# 安装（仓库里这份是唯一事实来源）：
#   install -m 0755 /opt/karma/repo/deploy/vps/ci-deploy-entry.sh /usr/local/bin/karma-ci-deploy
#
# authorized_keys 里对应的一行（私钥 = GitHub secret VPS_SSH_KEY）：
#   command="/usr/local/bin/karma-ci-deploy",no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty,no-user-rc ssh-ed25519 AAAA... karma-ci-deploy(forced-cmd)
set -e

SRC=/opt/karma/repo/deploy/vps/ci-deploy.sh
[ -f "$SRC" ] || { echo "missing $SRC" >&2; exit 1; }

d="$(mktemp /tmp/karma-cideploy.XXXXXX.sh)"
trap 'rm -f "$d"' EXIT INT TERM

cp -f "$SRC" "$d"
exec /bin/bash "$d"