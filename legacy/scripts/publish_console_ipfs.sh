#!/usr/bin/env bash
# 操作台静态包 → 内容寻址存储（IPFS）。
#
# 为什么不在 VPS 上常驻一个 ipfs 守护进程：那台机器只有 1.6G 内存，
# 装包压垮过一次（见 deploy/vps/ci-deploy.sh 里的注释）。所以发布从本机 / CI 走：
#
#   1. scripts/console_bundle.py build  —— 产出一份干净静态包 + console-dist.json
#   2. 有 ipfs CLI 就 add --cid-version 1，把 CID / DNSLink 写回清单
#   3. 没有 ipfs 就停在「清单已就绪」，并打印把它 pin 上去的确切命令
#
# 官方站点（karma-network.ai）从此只是**镜像之一**：谁都能自己拿一份静态包、
# 配自己的节点跑起来；DNSLink 只是给浏览器一个默认入口。
set -euo pipefail

usage() {
  cat <<'EOF'
用法: scripts/publish_console_ipfs.sh [选项]

  --out DIR        静态包输出目录（默认 dist/console）
  --src DIR        操作台源码目录（默认 apps/console）
  --domain NAME    DNSLink 用的域名（默认 karma-network.ai）
  --gateway URL    网关地址（默认 https://<domain>）
  --offline        传给 ipfs add：不联网
  --dry-run        只构建并自校验，不调用 ipfs
  -h, --help       显示本帮助
EOF
}

OUT="dist/console"
SRC="apps/console"
DOMAIN="karma-network.ai"
GATEWAY=""
OFFLINE=""
DRY_RUN=""

while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT="$2"; shift 2 ;;
    --src) SRC="$2"; shift 2 ;;
    --domain) DOMAIN="$2"; shift 2 ;;
    --gateway) GATEWAY="$2"; shift 2 ;;
    --offline) OFFLINE="--offline"; shift ;;
    --dry-run) DRY_RUN="1"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "未知参数：$1" >&2; usage >&2; exit 2 ;;
  esac
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || PY=python

MANIFEST="$(dirname "$OUT")/console-dist.json"

echo "==> [1/3] 构建静态包"
"$PY" scripts/console_bundle.py build --src "$SRC" --out "$OUT"

echo "==> [2/3] 自校验（清单 vs 目录）"
"$PY" scripts/console_bundle.py verify --dir "$OUT" --manifest "$MANIFEST"

echo "==> [3/3] 发布到 IPFS"
if [ -n "$DRY_RUN" ]; then
  echo "  --dry-run：跳过 ipfs；清单已在 $MANIFEST"
  exit 0
fi

if ! command -v ipfs >/dev/null 2>&1; then
  cat <<EOF
  没找到 ipfs CLI —— 静态包与清单都已就绪，任选一种方式 pin 上去：

    # 方式一：本机 / CI 装了 kubo（ipfs）
    ipfs add -r --cid-version 1 --quieter $OUT

    # 方式二：pinning 服务（web3.storage / Pinata / 自建集群都行）

  拿到 CID 后写回清单，并打印 DNSLink：

    $PY scripts/console_bundle.py stamp --manifest $MANIFEST --cid <CID> --domain $DOMAIN
EOF
  exit 0
fi

CID="$(ipfs add -r --cid-version 1 --quieter $OFFLINE "$OUT" | tail -n 1)"
[ -n "$CID" ] || { echo "ipfs add 没有返回 CID" >&2; exit 1; }

if [ -z "$GATEWAY" ]; then GATEWAY="https://$DOMAIN"; fi
"$PY" scripts/console_bundle.py stamp --manifest "$MANIFEST" --cid "$CID" --domain "$DOMAIN" --gateway "$GATEWAY" --pinned-by "local-ipfs"

echo
echo "静态包 CID : $CID"
echo "网关入口   : $GATEWAY"
echo "DNSLink    : _dnslink.$DOMAIN  TXT  \"dnslink=/ipfs/$CID\""
echo
echo "把上面这条 TXT 记录配到 DNS 之后，任何网关都能解析到这份静态包 —— 官方站点只是其中一个。"
