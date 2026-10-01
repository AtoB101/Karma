#!/usr/bin/env bash
# Public beta security gate.
#
# 这份脚本是 docs/SECURITY_RELEASE_GATES.md（Gate A-F）里**可执行的那一半**。
# 凡是能从环境变量、仓库代码、或对运行中服务做活体探测判定的条目，都在这里判，
# 并打印 PASS / FAIL / WARN。判不了的（告警是否真的送达、演练做没做过、日志留存
# 的合规口径、密钥轮换的时间点）打印 HUMAN —— 那些必须人签字，脚本不会替你把
# 它们勾上。
#
# 用法:
#   ./scripts/public-beta-security-gate.sh [--allow-non-prod] [--strict]
#                                        [--base-url URL] [--env-exec CMD]
#                                        [--no-heavy]
#
#   --env-exec 'docker exec karma-api env'  发布环境: 从容器里取真实环境变量。
#                                           不传就用当前 shell 的环境变量。
#   --base-url https://karma-network.ai     顺带做活体探测(错误面泄漏、请求 ID、
#                                           告警端点的鉴权)。不传则这几项记 HUMAN。
#   --strict                                HUMAN 也计入失败, 给"全自动放行"用。
#   --no-heavy                              跳过 pytest / acceptance 这类重活。
#
# 退出码: 0 = 无 FAIL; 1 = 有 FAIL (--strict 时 HUMAN 也算)。
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ALLOW_NON_PROD=false
STRICT=false
NO_HEAVY=false
BASE_URL=""
ENV_EXEC_CMD=""

usage() {
  sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --allow-non-prod) ALLOW_NON_PROD=true ;;
    --strict)         STRICT=true ;;
    --no-heavy)       NO_HEAVY=true ;;
    --base-url)       BASE_URL="${2:-}"; shift ;;
    --env-exec)       ENV_EXEC_CMD="${2:-}"; shift ;;
    -h|--help)        usage; exit 0 ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

# --------------------------------------------------------------------------
# 环境变量来源
# --------------------------------------------------------------------------
declare -A ENVK=()
if [[ -n "$ENV_EXEC_CMD" ]]; then
  echo "==> Loading release-environment variables via: ${ENV_EXEC_CMD}"
  while IFS= read -r line; do
    [[ "$line" =~ ^([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]] || continue
    ENVK["${BASH_REMATCH[1]}"]="${BASH_REMATCH[2]}"
  done < <(eval "$ENV_EXEC_CMD" 2>/dev/null || true)
  if [[ "${#ENVK[@]}" -eq 0 ]]; then
    echo "ERR  --env-exec produced no KEY=VALUE lines" >&2
    exit 2
  fi
fi

# ev NAME -> 取自 --env-exec 的名字优先, 否则退回当前 shell 环境
ev() {
  local n="$1"
  if [[ -n "${ENVK[$n]+x}" ]]; then printf '%s' "${ENVK[$n]}"; else printf '%s' "${!n:-}"; fi
}
# env_names -> 所有可见变量名(每行一个)
env_names() {
  if [[ -n "$ENV_EXEC_CMD" ]]; then
    printf '%s\n' "${!ENVK[@]}"
  else
    env | sed -n 's/^\([A-Za-z_][A-Za-z0-9_]*\)=.*/\1/p'
  fi
}

pass=0; fail=0; warn=0; human=0
declare -a FAILURES=()

p() { echo "PASS  $1"; pass=$((pass + 1)); }
f() { echo "FAIL  $1" >&2; fail=$((fail + 1)); FAILURES+=("$1"); }
w() { echo "WARN  $1"; warn=$((warn + 1)); }
h() { echo "HUMAN $1"; human=$((human + 1)); }

# 只判真假的小工具
is_true() { [[ "${1,,}" == "true" || "$1" == "1" || "${1,,}" == "yes" ]]; }
eq_prod() { [[ "${1,,}" == "production" || "${1,,}" == "prod" ]]; }

# --------------------------------------------------------------------------
# 活体探测用 python3, 不用 curl —— Windows/Git-bash 上的 curl 走 schannel, 在受限
# 环境里连不上 TLS(实测 git 也要 http.sslBackend=openssl 才行)。这个仓库本来就
# 依赖 python3(下面还要跑 pytest), 所以不额外增加依赖。
# --------------------------------------------------------------------------
# 光靠 `command -v` 不够: Windows 上 python3 常常存在但一执行就
# "Permission denied"(Microsoft Store 占位程序)。那样探针根本没跑, 读回来的
# 是上一轮的临时文件, 会把没验过的东西报成 PASS(2026-10-01 真踩过)。
# 所以每个候选都**真跑一次**再选。
_PY=""
for _cand in python3 python py; do
  if command -v "$_cand" > /dev/null 2>&1 && "$_cand" -c 'import sys' > /dev/null 2>&1; then
    _PY="$_cand"; break
  fi
done
if [[ -z "$_PY" ]]; then
  w "no usable python3/python on PATH - live probes (B4/C2b/D1D2) cannot run"
fi

PROBE_CODE=""; PROBE_RID=""; PROBE_BODY=""
# probe METHOD URL [JSON_DATA] -> 0 拿到响应(含 4xx/5xx), 1 传输层失败
probe() {
  PROBE_CODE=""; PROBE_RID=""; PROBE_BODY=""
  [[ -z "$_PY" ]] && return 1
  local method="$1" url="$2" data="${3:-}"
  # 每次探测一个全新的目录: 复用固定路径时, 一旦探针没跑起来就会读到上一轮的
  # 结果, 把 stale 的 401/200 当成这次探测的结论。
  local tmpd
  tmpd="$(mktemp -d "${TMPDIR:-/tmp}/karma_security_gate_probe.XXXXXX")" || return 1
  "$_PY" - "$method" "$url" "$data" "$tmpd" <<'PYEOF' || true
import io, os, sys, urllib.error, urllib.request
method, url, data, tmpd = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
req = urllib.request.Request(
    url,
    data=(data.encode() if data else None),
    method=method,
    headers={"User-Agent": "karma-security-gate", "Content-Type": "application/json"},
)
code, headers, payload = 0, {}, b""
try:
    with urllib.request.urlopen(req, timeout=20) as resp:
        code, headers, payload = resp.status, dict(resp.headers), resp.read()
except urllib.error.HTTPError as exc:
    code, headers, payload = exc.code, dict(exc.headers), exc.read()
except Exception as exc:
    payload = ("transport error: %s" % exc).encode()
io.open(os.path.join(tmpd, "code"), "w").write(str(code))
io.open(os.path.join(tmpd, "rid"), "w", encoding="utf-8").write(
    headers.get("X-Request-Id") or headers.get("x-request-id") or "")
io.open(os.path.join(tmpd, "body"), "wb").write(payload[:8000])
PYEOF
  PROBE_CODE="$(cat "$tmpd/code" 2> /dev/null || echo 0)"
  PROBE_RID="$(cat "$tmpd/rid" 2> /dev/null || echo "")"
  PROBE_BODY="$(cat "$tmpd/body" 2> /dev/null || echo "")"
  rm -rf "$tmpd"
  [[ -n "$PROBE_CODE" && "$PROBE_CODE" != "0" ]]
}

echo "========================================"
echo " Public beta security gate"
echo "========================================"
echo "==> env source : ${ENV_EXEC_CMD:-current shell}"
echo "==> base url   : ${BASE_URL:-<none - live probes become HUMAN>}"

# --------------------------------------------------------------------------
# Gate A - Identity and Access
# --------------------------------------------------------------------------
echo ""
echo "--- Gate A - Identity and Access"

APP_ENV_V="$(ev APP_ENV)"
if [[ "$ALLOW_NON_PROD" == "true" ]]; then
  echo "SKIP  A1 APP_ENV (--allow-non-prod)"
else
  if eq_prod "$APP_ENV_V"; then p "A1 APP_ENV=production"; else f "A1 APP_ENV must be production (got '${APP_ENV_V:-unset}')"; fi
fi

SECRET_V="$(ev APP_SECRET_KEY)"
if [[ -z "$SECRET_V" ]]; then
  f "A2 APP_SECRET_KEY is not set"
elif [[ "${SECRET_V,,}" =~ ^(change-me|changeme|dev|secret|test|karma|app-secret|dev-secret|change-me-in-production)$ ]]; then
  f "A2 APP_SECRET_KEY is a known default value"
elif [[ "${#SECRET_V}" -lt 32 ]]; then
  f "A2 APP_SECRET_KEY too short (${#SECRET_V} chars, want >= 32)"
else
  p "A2 APP_SECRET_KEY set and non-default (len=${#SECRET_V})"
fi
# A2b 密钥轮换台账。以前这一条一律 HUMAN —— 脚本判不出「谁、什么时候轮换的」。
# 现在判的是**台账本身可核查**：docs/KEY_ROTATION.md 里有一段机器可读的 ledger，
# 校验它字段齐全、口径自洽（next_due = anchor + cycle_days）、有人签字，且没到期。
# 判不出来的仍然是「签字人是不是真人」—— 那是 A4d 的事，不混进这一条。
ROT_LEDGER="docs/KEY_ROTATION.md"
if [[ ! -f "$ROT_LEDGER" ]]; then
  f "A2b key-rotation ledger missing ($ROT_LEDGER)"
elif [[ -z "$_PY" ]]; then
  h "A2b $ROT_LEDGER present but no usable python3 here to parse the ledger"
else
  rot_out="$("$_PY" - "$ROT_LEDGER" <<'PYEOF' 2> /dev/null || true
import datetime, re, sys
raw = open(sys.argv[1], encoding="utf-8").read()
m = re.search(r"<!--\s*karma-rotation-ledger(.*?)-->", raw, re.S)
if not m:
    print("err=no-machine-ledger-block"); raise SystemExit(0)
kv = {}
for line in m.group(1).splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    kv[k.strip()] = v.strip()
need = ("scope", "basis_date", "last_rotated", "cycle_days", "next_due", "signed_by")
missing = [k for k in need if not kv.get(k)]
if missing:
    print("err=missing-fields:" + ",".join(missing)); raise SystemExit(0)
try:
    basis = datetime.date.fromisoformat(kv["basis_date"])
    nxt = datetime.date.fromisoformat(kv["next_due"])
    cyc = int(kv["cycle_days"])
except Exception as exc:
    print("err=unparsable-field:%s" % exc); raise SystemExit(0)
if cyc < 1:
    print("err=cycle-days-not-positive"); raise SystemExit(0)
lr = kv["last_rotated"].strip().lower()
if lr in ("never", "none", "n/a", "-"):
    anchor, state = basis, "never-rotated"
else:
    try:
        anchor = datetime.date.fromisoformat(lr)
    except Exception:
        print("err=last_rotated-is-neither-never-nor-a-date:%s" % kv["last_rotated"]); raise SystemExit(0)
    if anchor > datetime.date.today():
        print("err=last_rotated-is-in-the-future"); raise SystemExit(0)
    state = "rotated"
if (nxt - anchor).days != cyc:
    print("err=next_due-is-not-cycle_days-after-anchor:%d" % (nxt - anchor).days); raise SystemExit(0)
print("state=%s" % state)
print("next_due=%s" % nxt.isoformat())
print("signed_by=%s" % kv["signed_by"])
print("days_left=%d" % (nxt - datetime.date.today()).days)
PYEOF
)"
  rot_err="$(printf '%s\n' "$rot_out" | sed -n 's/^err=//p')"
  if [[ -n "$rot_err" ]]; then
    f "A2b key-rotation ledger is not verifiable (${rot_err})"
  else
    rot_state="$(printf '%s\n' "$rot_out" | sed -n 's/^state=//p')"
    rot_next="$(printf '%s\n' "$rot_out" | sed -n 's/^next_due=//p')"
    rot_by="$(printf '%s\n' "$rot_out" | sed -n 's/^signed_by=//p')"
    rot_left="$(printf '%s\n' "$rot_out" | sed -n 's/^days_left=//p')"
    if [[ -z "$rot_state" || -z "$rot_left" ]]; then
      h "A2b ledger parsed but reported nothing usable - look by hand"
    elif [[ "$rot_left" -lt 0 ]]; then
      f "A2b key rotation is OVERDUE (next_due=${rot_next}, ${rot_left}d) - rotate, then append a row to docs/KEY_ROTATION.md"
    else
      p "A2b rotation ledger verified (state=${rot_state}, next_due=${rot_next}, ${rot_left}d left, signed_by=${rot_by})"
    fi
  fi
fi

ENFORCE_V="$(ev AUTH_ENFORCE_PROTECTED_ROUTES)"
if [[ "$ALLOW_NON_PROD" == "true" ]]; then
  echo "SKIP  A3 AUTH_ENFORCE_PROTECTED_ROUTES (--allow-non-prod)"
elif is_true "$ENFORCE_V"; then
  p "A3 AUTH_ENFORCE_PROTECTED_ROUTES=true"
else
  f "A3 AUTH_ENFORCE_PROTECTED_ROUTES must be true (got '${ENFORCE_V:-unset}')"
fi

KEYS_V="$(ev AUTH_API_KEYS)"
if [[ -z "$KEYS_V" ]]; then
  f "A4 AUTH_API_KEYS is not configured"
else
  key_count="$(printf '%s' "$KEYS_V" | tr ',' '\n' | grep -c '[^[:space:]]' || true)"
  p "A4 AUTH_API_KEYS configured (${key_count} entr(y|ies))"
  if [[ "$key_count" -lt 2 ]]; then
    w "A4b only ${key_count} API key configured - confirm every service agent has its own key"
  else
    p "A4b ${key_count} API keys configured (one per service agent)"
  fi

  # A4c —— 2026-10-01 从 HUMAN 收口成机器可判。
  # 「每个 service agent 一把独立 key」能判的部分就三条：
  #   1. 没有任何两个 agent 共用同一个 secret（共用 = 审计追不到人）；
  #   2. 每把 secret 都不短（弱密钥等于没有）；
  #   3. 运维白名单里点名的 actor 必须各有一把自己的钥匙 —— 悬空的
  #      `ADMIN_ACTOR_IDS` 条目等于把一个没人管的 id 留成了后门。
  # 判不出来的那部分（白名单里的身份号是不是真的对得上人）留给 A4d 人工签。
  # 注：白名单里的 `kid_*`（身份号）和纯数字（telegram id）是另一个命名空间，
  # 不占静态钥匙的账，跳过。
  a4c_bad=0
  key_actors="$(printf '%s' "$KEYS_V" | tr ',' '\n' \
    | awk -F: 'NF >= 2 { a = $1; gsub(/^[ \t]+|[ \t]+$/, "", a); print a }' || true)"
  dup_secrets="$(printf '%s' "$KEYS_V" | tr ',' '\n' \
    | awk -F: 'NF >= 2 { sub(/^[^:]*:/, ""); gsub(/^[ \t]+|[ \t]+$/, ""); print }' \
    | sort | uniq -d || true)"
  if [[ -n "$dup_secrets" ]]; then
    f "A4c two service agents share the same API key secret - audit cannot tell them apart"
    a4c_bad=1
  fi
  short_actors="$(printf '%s' "$KEYS_V" | tr ',' '\n' \
    | awk -F: 'NF >= 2 { a = $1; sub(/^[^:]*:/, ""); gsub(/^[ \t]+|[ \t]+$/, ""); if (length($0) < 24) print a }' || true)"
  if [[ -n "$short_actors" ]]; then
    f "A4c API key secret shorter than 24 chars: $(printf '%s' "$short_actors" | tr '\n' ' ')"
    a4c_bad=1
  fi
  for listed_var in ADMIN_ACTOR_IDS ARBITRATOR_ACTOR_IDS GOVERNANCE_VERIFIER_IDS; do
    for listed_actor in $(ev "$listed_var" | tr ',' ' '); do
      case "$listed_actor" in
        kid_*|[0-9]*) continue ;;
      esac
      if ! grep -qxF "$listed_actor" <<< "$key_actors"; then
        f "A4c ${listed_var} names '${listed_actor}' but AUTH_API_KEYS has no key for it (dangling privileged actor)"
        a4c_bad=1
      fi
    done
  done
  if [[ "$a4c_bad" == "0" ]]; then
    p "A4c no shared secret, no short secret, every privileged actor has its own key"
  fi
  h "A4d 运维白名单里的身份号（kid_* / telegram id）确有其人，且与持有人对得上"
fi

# A5 - 运行环境里不该出现测试凭证
dev_fallback="$(ev AUTH_ALLOW_DEV_KEY_FALLBACK)"
relax_phase1="$(ev OPENCLAW_LOCAL_PHASE1_AUTO_RELAX)"
relax_delivery="$(ev OPENCLAW_RELAX_DELIVERY_SIGNATURES)"
a5_bad=0
if [[ "$ALLOW_NON_PROD" == "false" ]]; then
  for item in "AUTH_ALLOW_DEV_KEY_FALLBACK:$dev_fallback" \
              "OPENCLAW_LOCAL_PHASE1_AUTO_RELAX:$relax_phase1" \
              "OPENCLAW_RELAX_DELIVERY_SIGNATURES:$relax_delivery"; do
    name="${item%%:*}"; val="${item#*:}"
    if is_true "$val"; then
      f "A5 ${name}=true is a test/dev relaxation and must be off"
      a5_bad=1
    fi
  done
  suspicious="$(env_names | grep -iE '^(TEST|DEMO|FIXTURE|SEED|EXAMPLE|DUMMY)_(API_?KEY|SECRET|TOKEN|PASSWORD|PRIVATE_KEY)$' || true)"
  if [[ -n "$suspicious" ]]; then
    f "A5 test-credential-shaped env vars present: $(echo "$suspicious" | tr '\n' ' ')"
    a5_bad=1
  fi
fi
if [[ "$a5_bad" -eq 0 ]]; then
  p "A5 no test credentials / dev relaxations in the release env"
fi

# A6 —— x402 出网口。`/v1/x402/pay-and-fetch` 的目标 URL 是 agent 传进来的，所以
# 这是一个「调用方指定目标」的出网口：它能打到哪，取决于这里怎么判。代码默认
# `X402_ALLOW_PRIVATE_HOSTS=true`（本地 mock 图方便），生产必须显式关掉；关掉之后
# url_safety 还会把域名解析一遍，拦住「域名指向 127.0.0.1 / 169.254.169.254」这类
# 绕过 —— 原来只查字面 IP，裸域名直接放行，等于没拦。
if [[ "$ALLOW_NON_PROD" == "true" ]]; then
  echo "SKIP  A6 x402 outbound fetch guardrails (--allow-non-prod)"
elif [[ "$(printf '%s' "$(ev X402_ENABLED)" | tr 'A-Z' 'a-z')" == "false" ]]; then
  # 注意：这里判的是「显式等于 false」而不是「不是 true」。代码里 x402_enabled 默认
  # 就是 true，发布环境里根本没写这个变量 —— 早先按「不是 true 就 SKIP」写，生产
  # 上直接 SKIP 掉了，等于这条闸门从没判过。
  echo "SKIP  A6 x402 disabled (X402_ENABLED=false)"
else
  a6_backend="$(printf '%s' "$(ev X402_PAYMENT_BACKEND)" | tr 'A-Z' 'a-z')"
  a6_allow="$(ev X402_ALLOW_PRIVATE_HOSTS)"
  a6_bad=0
  if [[ "$a6_backend" == "mock" ]]; then
    f "A6 X402_PAYMENT_BACKEND=mock in a release env (mock payments are not payments)"
    a6_bad=1
  fi
  if is_true "$a6_allow" || [[ -z "$a6_allow" ]]; then
    f "A6 X402_ALLOW_PRIVATE_HOSTS is '${a6_allow:-unset}' - must be false; unset defaults to true, and the agent-facing fetch could then reach private/loopback addresses"
    a6_bad=1
  fi
  if [[ "$a6_bad" == "0" ]]; then
    p "A6 x402 outbound fetch locked to public hosts (backend=${a6_backend})"
  fi
fi

# --------------------------------------------------------------------------
# Gate B - API Abuse Resistance
# --------------------------------------------------------------------------
echo ""
echo "--- Gate B - API Abuse Resistance"

REDIS_V="$(ev REDIS_URL)"; REDIS_RL_V="$(ev RATE_LIMIT_REDIS_URL)"
redis_url="${REDIS_RL_V:-$REDIS_V}"
if [[ -z "$redis_url" ]]; then
  f "B1 no REDIS_URL / RATE_LIMIT_REDIS_URL - rate limiter would be process-local only"
elif [[ "$redis_url" != redis://* && "$redis_url" != rediss://* ]]; then
  f "B1 REDIS_URL scheme is not redis:// (got '${redis_url%%:*}')"
else
  p "B1 Redis URL configured for the limiter (scheme=${redis_url%%:*})"
fi
# B1b Redis 到底连不连得上。以前这一条一律 HUMAN（「脚本在应用进程外探不到容器
# 网络」），但**同一个事实 H4 已经在判** —— 一处 PASS 一处 HUMAN 是自相矛盾。
# 这里直接 ping；够不着才退回 HUMAN（远端 Redis 确实需要到发布机上确认）。
b1b_pong="$(docker exec karma-redis redis-cli ping 2> /dev/null || true)"
if [[ "$b1b_pong" == *PONG* ]]; then
  p "B1b Redis reachable from the release host (karma-redis redis-cli ping -> PONG)"
elif [[ "$redis_url" == redis://127.* || "$redis_url" == redis://localhost* ]]; then
  f "B1b the limiter points at a host-local Redis but karma-redis did not answer PONG"
else
  h "B1b Redis is remote or unreachable from here - confirm on the release host"
fi

FAIL_CLOSED_V="$(ev RATE_LIMIT_REDIS_FAIL_CLOSED)"
if is_true "$FAIL_CLOSED_V"; then
  p "B1c RATE_LIMIT_REDIS_FAIL_CLOSED=true (limiter fails closed if Redis dies)"
else
  if [[ "$ALLOW_NON_PROD" == "true" ]]; then
    w "B1c RATE_LIMIT_REDIS_FAIL_CLOSED is not true (tolerated by --allow-non-prod)"
  else
    f "B1c RATE_LIMIT_REDIS_FAIL_CLOSED must be true in production"
  fi
fi

# B2 - 敏感写路径的额度确实存在（仓库代码层面）
if grep -q '"write_sensitive"' api/middleware/rate_limit.py \
   && grep -q '"state_transition"' api/middleware/rate_limit.py; then
  p "B2 write_sensitive + state_transition buckets defined"
else
  f "B2 write_sensitive / state_transition buckets missing from api/middleware/rate_limit.py"
fi
if grep -q '_is_sensitive_write' api/app.py && grep -q 'security_write_rate_limit_middleware' api/app.py; then
  p "B2b sensitive-write limiter is wired into the app middleware stack"
else
  f "B2b sensitive-write middleware is not wired in api/app.py"
fi

# B4 - 告警端点存在且受保护
if [[ -n "$BASE_URL" ]]; then
  if probe GET "${BASE_URL%/}/v1/security/ops/alerts"; then
    case "$PROBE_CODE" in
      401|403) p "B4 /v1/security/ops/alerts exists and is auth-protected (HTTP $PROBE_CODE)" ;;
      200)     f "B4 /v1/security/ops/alerts answered 200 without credentials" ;;
      *)       w "B4 /v1/security/ops/alerts returned HTTP $PROBE_CODE (expected 401/403)" ;;
    esac
  else
    h "B4 /v1/security/ops/alerts not verified from this host (probe unavailable/transport error)"
  fi
else
  h "B4 /v1/security/ops/alerts is auth-protected (pass --base-url to probe)"
fi

h "B3 alerting is delivered for sustained 429 spikes and auth failures (on-call must confirm)"

# B5/B6/B7 阈值策略。以前这三条一律 HUMAN。现在从**库里的 active 那一行**直判：
#   有没有真的激活过策略（0 行 = 全站跑代码默认，没有任何按路径/路由组的收紧）、
#   冷却窗口定没定、
#   以及文档里钉的版本跟库里**对不对得上**（对不上就是文档和现实分叉，比没文档更危险）。
# 判不出来的只剩「这套阈值拍得合不合理」—— 那才是人签字的活。
if [[ -z "$_PY" ]]; then
  h "B5/B6/B7 threshold policy not inspectable (no usable python3 here)"
else
  TP_DOC="docs/SECURITY_THRESHOLD_POLICY.md"
  POL_JSON="$(docker exec karma-postgres psql -U karma -d karma -tAc \
    "select json_build_object('policy_id',policy_id,'version',version,'config',config,'activated_at',activated_at) from security_threshold_policies where status='active' order by activated_at desc limit 1" \
    2> /dev/null || true)"
  if [[ -z "${POL_JSON//[[:space:]]/}" ]]; then
    f "B6/B7 no ACTIVE security threshold policy - every scope runs on code defaults (no per-path / per-group tightening at all)"
    h "B5 alert cooldown / suppression policy reviewed with on-call"
  else
    POL_FIELDS="$("$_PY" -c '
import json, re, sys
try:
    row = json.loads(sys.argv[1])
except Exception as exc:
    print("err=unparsable:%s" % exc); raise SystemExit(0)
cfg = row.get("config") or {}
need = (
    "failed_auth_threshold_overrides",
    "rate_limit_threshold_overrides",
    "private_runtime_error_threshold_overrides",
    "settlement_transition_denied_threshold_overrides",
)
missing = [k for k in need if not str(cfg.get(k) or "").strip()]
print("version=%s" % row.get("version"))
print("policy_id=%s" % row.get("policy_id"))
print("cooldown=%s" % cfg.get("alert_cooldown_minutes"))
print("missing=%s" % ",".join(missing))
try:
    raw = open(sys.argv[2], encoding="utf-8").read()
except Exception:
    print("doc=missing"); raise SystemExit(0)
m = re.search(r"<!--\s*karma-threshold-policy(.*?)-->", raw, re.S)
if not m:
    print("doc=nopin"); raise SystemExit(0)
kv = {}
for line in m.group(1).splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        kv[k.strip()] = v.strip()
print("doc=ok")
print("pin_version=%s" % kv.get("active_version", ""))
print("pin_id=%s" % kv.get("active_policy_id", ""))
' "$POL_JSON" "$TP_DOC" 2> /dev/null || true)"
    pol_err="$(printf '%s\n' "$POL_FIELDS" | sed -n 's/^err=//p')"
    pol_ver="$(printf '%s\n' "$POL_FIELDS" | sed -n 's/^version=//p')"
    pol_id="$(printf '%s\n' "$POL_FIELDS" | sed -n 's/^policy_id=//p')"
    pol_cd="$(printf '%s\n' "$POL_FIELDS" | sed -n 's/^cooldown=//p')"
    pol_missing="$(printf '%s\n' "$POL_FIELDS" | sed -n 's/^missing=//p')"
    pol_doc="$(printf '%s\n' "$POL_FIELDS" | sed -n 's/^doc=//p')"
    pin_ver="$(printf '%s\n' "$POL_FIELDS" | sed -n 's/^pin_version=//p')"
    pin_id="$(printf '%s\n' "$POL_FIELDS" | sed -n 's/^pin_id=//p')"
    if [[ -n "$pol_err" ]]; then
      h "B5/B6/B7 the active policy row is unparsable (${pol_err})"
    else
      if [[ -n "$pol_missing" ]]; then
        f "B6 critical paths carry no threshold override (missing: ${pol_missing})"
      else
        p "B6 critical-path threshold overrides are configured (active policy v${pol_ver})"
      fi
      if [[ -n "$pol_cd" && "$pol_cd" != "None" ]]; then
        p "B5 alert cooldown is pinned in the active policy (alert_cooldown_minutes=${pol_cd})"
      else
        h "B5 alert cooldown / suppression policy reviewed with on-call"
      fi
      if [[ "$pol_doc" == "missing" ]]; then
        f "B7 $TP_DOC is missing - the active policy is not documented anywhere"
      elif [[ "$pol_doc" != "ok" ]]; then
        f "B7 $TP_DOC has no machine-readable karma-threshold-policy pin block"
      elif [[ -z "$pin_ver" || -z "$pin_id" ]]; then
        f "B7 $TP_DOC pin block is missing active_version / active_policy_id"
      elif [[ "$pin_ver" != "$pol_ver" || "$pin_id" != "$pol_id" ]]; then
        f "B7 the pinned policy in $TP_DOC (v${pin_ver} ${pin_id}) disagrees with the live active policy (v${pol_ver} ${pol_id})"
      else
        p "B7 active threshold policy is pinned and documented (v${pol_ver} ${pol_id})"
      fi
    fi
  fi
fi

# --------------------------------------------------------------------------
# Gate C - Security Auditability
# --------------------------------------------------------------------------
echo ""
echo "--- Gate C - Security Auditability"

if grep -q 'security_write_audit' api/app.py; then
  p "C1 sensitive writes emit a security audit record (security_audit_middleware)"
else
  f "C1 no sensitive-write audit record found in api/app.py"
fi
if grep -q 'X-Request-Id' api/app.py; then
  p "C2 responses carry X-Request-Id (actor/path/method/status/request_id are logged together)"
else
  f "C2 X-Request-Id header not set in api/app.py"
fi
if [[ -n "$BASE_URL" ]]; then
  if probe GET "${BASE_URL%/}/health"; then
    if [[ -n "$PROBE_RID" ]]; then
      p "C2b live response carries X-Request-Id (${PROBE_RID})"
    else
      w "C2b live response has no X-Request-Id header"
    fi
  else
    h "C2b could not reach ${BASE_URL%/}/health - X-Request-Id not verified"
  fi
else
  h "C2b live response carries X-Request-Id (pass --base-url to probe)"
fi
# C3 日志留存 + 排查时的查询入口。以前一律 HUMAN。能机器判的先判，剩下的才留给人：
#   C3a 容器日志有没有轮转上限（没有上限迟早写满磁盘，且「留存多久」根本不可控）；
#   C3b 系统日志（journald）的留存上限是不是**显式写死**的（跟着发行版默认走 = 口径不明）；
#   C3c 留存窗口与查询命令有没有写进 playbook（出事时没人在现场翻命令）。
C3_CAP=""
if command -v docker > /dev/null 2>&1; then
  C3_CAP="$(docker inspect -f '{{json .HostConfig.LogConfig.Config}}' karma-api 2> /dev/null || true)"
fi
C3_DAEMON=""
[[ -r /etc/docker/daemon.json ]] && C3_DAEMON="$(cat /etc/docker/daemon.json 2> /dev/null || true)"
if grep -q 'max-size' <<< "${C3_CAP}${C3_DAEMON}"; then
  p "C3a container logs are capped (${C3_CAP:-daemon.json log-opts})"
else
  f "C3a container logs have no rotation cap - they will fill the disk (set logging.options max-size/max-file)"
fi
C3_JOURNAL=""
[[ -r /etc/systemd/journald.conf ]] && C3_JOURNAL="$(grep -E '^[[:space:]]*(SystemMaxUse|SystemKeepFree|MaxRetentionSec)=' /etc/systemd/journald.conf 2> /dev/null || true)"
if [[ -n "$C3_JOURNAL" ]]; then
  p "C3b journald retention is pinned explicitly ($(printf '%s' "$C3_JOURNAL" | tr '\n' ' ' | sed 's/ *$//'))"
else
  h "C3b journald retention follows the distro default - pin SystemMaxUse / MaxRetentionSec"
fi
if grep -qiE 'log retention|日志留存' docs/SECURITY_INCIDENT_PLAYBOOK.md 2> /dev/null; then
  p "C3c retention window + query commands are documented (docs/SECURITY_INCIDENT_PLAYBOOK.md)"
else
  h "C3c log retention + query access are not documented yet"
fi

# --------------------------------------------------------------------------
# Gate D - Error Surface Control
# --------------------------------------------------------------------------
echo ""
echo "--- Gate D - Error Surface Control"

if [[ -n "$BASE_URL" ]]; then
  leak=0
  unreachable=0
  for probe_path in "/v1/__gate_probe_not_a_route__" "/v1/settlement/__gate_probe__/lock"; do
    if probe POST "${BASE_URL%/}${probe_path}" '{"__gate_probe__":1}'; then
      for marker in 'Traceback' 'File "' 'site-packages' '/opt/karma' 'sqlalchemy' 'asyncpg'; do
        if grep -qF "$marker" <<< "$PROBE_BODY"; then
          f "D1 internal detail leaked at ${probe_path} (marker: ${marker})"
          leak=1
        fi
      done
    else
      unreachable=1
    fi
  done
  if [[ "$leak" -eq 0 && "$unreachable" -eq 0 ]]; then
    p "D1/D2 no stack traces, filesystem paths or driver internals leaked on error paths"
  elif [[ "$leak" -eq 0 ]]; then
    h "D1/D2 probe(s) unreachable from this host - error surface not verified"
  fi
else
  h "D1/D2 error responses carry no internal detail (pass --base-url to probe)"
fi

DEBUG_V="$(ev DEBUG)"; APP_DEBUG_V="$(ev APP_DEBUG)"
if is_true "$DEBUG_V" || is_true "$APP_DEBUG_V"; then
  f "D3 DEBUG/APP_DEBUG is enabled in the release env"
elif grep -qE '^\s*debug: bool = False' config/settings.py; then
  p "D3 debug mode disabled (settings.debug defaults to False, no DEBUG env override)"
else
  w "D3 could not confirm settings.debug default is False"
fi

# --------------------------------------------------------------------------
# Gate E - Verification and Rollback
# --------------------------------------------------------------------------
echo ""
echo "--- Gate E - Verification and Rollback"

h "E1 security regression tests pass in CI (see the GitHub Actions run for this commit)"
h "E2 public acceptance script passes (run by CI; heavy local run below)"

if [[ -f docs/SECURITY_INCIDENT_PLAYBOOK.md ]]; then
  p "E4a rollback/on-call runbook exists (docs/SECURITY_INCIDENT_PLAYBOOK.md)"
else
  f "E4a docs/SECURITY_INCIDENT_PLAYBOOK.md is missing"
fi
h "E4b rollback plan and on-call runbook confirmed by a human"

ONCALL_P="$(ev SECURITY_ONCALL_PRIMARY)"; ONCALL_B="$(ev SECURITY_ONCALL_BACKUP)"
if [[ "$ALLOW_NON_PROD" == "true" ]]; then
  echo "SKIP  E5 SECURITY_ONCALL_* (--allow-non-prod)"
elif [[ -n "$ONCALL_P" && -n "$ONCALL_B" ]]; then
  p "E5 SECURITY_ONCALL_PRIMARY / SECURITY_ONCALL_BACKUP configured"
  # 两个值一样 = 没有第二个人。真出事时「值班的人联系不上」和「没人值班」等价，
  # 所以这一条也必须是机器可判的。
  if [[ "${ONCALL_P,,}" == "${ONCALL_B,,}" ]]; then
    f "E5b SECURITY_ONCALL_BACKUP is the same as PRIMARY - there is no second on-call"
  else
    p "E5b on-call primary and backup are different people"
  fi
else
  f "E5 SECURITY_ONCALL_PRIMARY / SECURITY_ONCALL_BACKUP must be configured"
fi

if grep -q 'baseline_window_minutes' api/routes/security.py && grep -q 'baseline_drift_multiplier' api/routes/security.py; then
  p "E6a baseline drift controls exist (baseline_window_minutes / baseline_drift_multiplier)"
else
  f "E6a baseline drift controls not found in api/routes/security.py"
fi
h "E6b baseline drift strategy reviewed and the chosen values agreed with on-call"
# E7 回滚演练。以前一律 HUMAN（「演练做没做过」）。现在判**留没留证据**：
# 演练把结果写到 /opt/karma/state/security-policy-drill.json，这里校验「回滚成功」+ 不太旧。
# 跟 F4 判恢复演练同一个思路：不接受「口头说练过」。
E7_FILE="${KARMA_POLICY_DRILL_STATE:-/opt/karma/state/security-policy-drill.json}"
if [[ ! -f "$E7_FILE" ]]; then
  h "E7 no policy-center rollback drill on record ($E7_FILE missing) - run one and record it"
elif [[ -z "$_PY" ]]; then
  h "E7 $E7_FILE present but no usable python3 here to read it"
else
  E7_OUT="$("$_PY" -c '
import datetime, json, sys
try:
    d = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception as exc:
    print("err=unreadable:%s" % exc); raise SystemExit(0)
age = -1
try:
    ts = datetime.datetime.strptime(str(d.get("at") or ""), "%Y-%m-%dT%H:%M:%SZ")
    age = (datetime.datetime.utcnow() - ts).days
except Exception:
    pass
print("ok=%s" % ("1" if d.get("rollback_ok") else "0"))
print("age_days=%d" % age)
print("version=%s" % (d.get("active_version") if d.get("active_version") is not None else "?"))
' "$E7_FILE" 2> /dev/null || true)"
  e7_ok="$(printf '%s\n' "$E7_OUT" | sed -n 's/^ok=//p')"
  e7_age="$(printf '%s\n' "$E7_OUT" | sed -n 's/^age_days=//p')"
  e7_ver="$(printf '%s\n' "$E7_OUT" | sed -n 's/^version=//p')"
  if [[ -z "$e7_ok" ]]; then
    h "E7 $E7_FILE unreadable - look by hand"
  elif [[ "$e7_ok" != "1" ]]; then
    f "E7 the recorded policy rollback drill did not succeed ($E7_FILE)"
  elif [[ -z "$e7_age" || "$e7_age" -lt 0 ]]; then
    h "E7 drill evidence has no usable timestamp ($E7_FILE)"
  elif [[ "$e7_age" -gt 180 ]]; then
    f "E7 policy rollback drill is ${e7_age} days old - run it again (want <= 180)"
  else
    p "E7 policy-center rollback drill on record (${e7_age}d ago, rolled back onto v${e7_ver})"
  fi
fi

# --------------------------------------------------------------------------
# 定时任务文本：F2/G2 判断「这东西到底装没装」。crontab / cron.d / /etc/crontab /
# systemd timer 全收进来，因为「装了但用另一种方式装」也是装了。
# --------------------------------------------------------------------------
schedule_text() {
  local blob=""
  blob+="$(crontab -l 2> /dev/null || true)"$'\n'
  if [[ -d /etc/cron.d ]]; then blob+="$(cat /etc/cron.d/* 2> /dev/null || true)"$'\n'; fi
  if [[ -r /etc/crontab ]]; then blob+="$(cat /etc/crontab 2> /dev/null || true)"$'\n'; fi
  if command -v systemctl > /dev/null 2>&1; then
    blob+="$(systemctl list-timers --all --no-pager 2> /dev/null || true)"$'\n'
    blob+="$(systemctl list-unit-files --no-pager 2> /dev/null || true)"$'\n'
  fi
  printf '%s' "$blob"
}

# --------------------------------------------------------------------------
# Gate F - Backup and Recovery
#
# 「有备份」和「备份能用」是两件事。F3 只证明快照存在且不空；F4 证明这份 dump 真的
# 恢复得回去（恢复演练由 scripts/ops/backup.sh --verify 做，逐表比对行数）。
# 只有离站副本（F5/F6）能挡住「盘坏 / 机器丢」；同盘快照挡不住。
# --------------------------------------------------------------------------
echo ""
echo "--- Gate F - Backup and Recovery"

BK_SCRIPT="scripts/ops/backup.sh"
if [[ ! -f "$BK_SCRIPT" ]]; then
  f "F1 backup script missing ($BK_SCRIPT)"
elif ! bash -n "$BK_SCRIPT" 2> /dev/null; then
  f "F1 $BK_SCRIPT does not parse (bash -n failed)"
else
  p "F1 backup script present and parses ($BK_SCRIPT)"
fi

if [[ "$ALLOW_NON_PROD" == "true" ]] || ! eq_prod "$APP_ENV_V"; then
  echo "SKIP  F2-F5 host backup state (not a production release env)"
else
  BK_ROOT="${KARMA_BACKUP_ROOT:-/opt/karma/backups}"

  # F2 到底装没装：定时任务里有没有引用它
  sched_blob="$(schedule_text)"
  if [[ -z "${sched_blob//[[:space:]]/}" ]]; then
    h "F2 backup schedule not inspectable from here - confirm the timer on the host"
  elif grep -qaE 'karma-backup|ops/backup\.sh' <<< "$sched_blob"; then
    p "F2 backup is scheduled (cron/systemd-timer references the backup script)"
  else
    f "F2 backup script exists but nothing schedules it - it will never run on its own"
  fi

  # 只认 YYYYmmdd-HHMMSS 这种快照目录。deploy 脚本会往同一个 /opt/karma/backups 里
  # 放 web-<ts> 的网站备份，它没有 karma-db.sql.gz —— 2026-10-01 拿它当「最新快照」
  # 判了一次假 FAIL。一条假 FAIL 会让人开始不信闸门，和假绿灯一样糟。
  BK_LATEST=""
  while read -r _d; do
    [[ -n "$_d" ]] || continue
    if [[ "$(basename "$_d")" =~ ^[0-9]{8}-[0-9]{6}$ ]]; then BK_LATEST="$_d"; break; fi
  done < <(ls -1dt "$BK_ROOT"/*/ 2> /dev/null | sed 's:/$::')
  if [[ -z "$BK_LATEST" ]]; then
    f "F3 no snapshot under $BK_ROOT"
  else
    BK_DUMP="$BK_LATEST/karma-db.sql.gz"
    BK_BYTES=0
    [[ -f "$BK_DUMP" ]] && BK_BYTES="$(stat -c '%s' "$BK_DUMP" 2> /dev/null || echo 0)"
    BK_AGE_H=$(( ( $(date +%s) - $(stat -c '%Y' "$BK_DUMP" 2> /dev/null || date +%s) ) / 3600 ))
    if [[ "$BK_BYTES" -lt 1024 ]]; then
      f "F3 newest dump is empty or missing ($(basename "$BK_LATEST"): ${BK_BYTES}B)"
    elif [[ "$BK_AGE_H" -gt 26 ]]; then
      f "F3 newest dump is stale (${BK_AGE_H}h old, want <= 26h)"
    else
      p "F3 newest snapshot is fresh and non-empty ($(basename "$BK_LATEST"), ${BK_AGE_H}h old, ${BK_BYTES}B)"
    fi

    BK_MANIFEST="$BK_LATEST/manifest.txt"
    if [[ ! -f "$BK_MANIFEST" ]]; then
      h "F4/F5 no manifest.txt next to the newest dump - cannot tell whether a restore drill or an offsite copy ran"
    else
      # 演练和离站**只在每天 03:17 那一轮**跑。所以「最新那份快照演练过没有」这个判据
      # 几乎永远是「没有」：快照每小时落一份，03:17 之后每一份都是没演练过的。照它判，
      # 闸门会每小时从绿变黄、再在 03:17 变回绿 —— 2026-10-01 实测就是这样：19:17 的
      # cron 快照把 F4 从 PASS 顶成 HUMAN。一个按时辰变色的闸门，很快就会被当成噪声忽略。
      #
      # 真正该判的是**最近一次演练的结果**，而不是「最新那份有没有演练」。所以从新到旧
      # 找第一份真的跑过演练的（skipped / pending 不算跑过 —— 没跑就是没跑），再判它
      # 成没成、离现在多久。演练一停，26h 后立刻转红，那才是该红的时候。
      bk_status_lines() {
        # 输出 "<status>|<snapshot>|<age_h>"，新→旧。age 取 manifest 的 created_at
        # （只写一次），不用目录 mtime —— 演练会碰目录 mtime，那样会把停掉的演练算成新的。
        local field="$1" d st ca ts age
        while read -r d; do
          [[ -n "$d" ]] || continue
          [[ "$(basename "$d")" =~ ^[0-9]{8}-[0-9]{6}$ ]] || continue
          [[ -f "$d/manifest.txt" ]] || continue
          st="$(sed -n "s/^${field}=//p" "$d/manifest.txt" | tail -1)"
          ca="$(sed -n 's/^created_at=//p' "$d/manifest.txt" | tail -1)"
          ts=""
          if [[ -n "$ca" ]]; then ts="$(date -d "$ca" +%s 2> /dev/null || true)"; fi
          if [[ -z "$ts" ]]; then ts="$(stat -c '%Y' "$d" 2> /dev/null || date +%s)"; fi
          age=$(( ( $(date +%s) - ts ) / 3600 ))
          printf '%s|%s|%s\n' "${st:-absent}" "$(basename "$d")" "$age"
        done < <(ls -1dt "$BK_ROOT"/*/ 2> /dev/null | sed 's:/$::')
      }

      BK_LATEST_NAME="$(basename "$BK_LATEST")"
      V_ST="$(sed -n 's/^verify_status=//p' "$BK_MANIFEST" | tail -1)"
      O_ST="$(sed -n 's/^offsite_status=//p' "$BK_MANIFEST" | tail -1)"

      # 注意：这里先把清单收进变量，再用 herestring 过滤 —— **不要**写成
      # `bk_status_lines ... | awk '...{exit}'`。awk 一 `exit` 就把上游掐了，
      # 上游 printf 拿到 SIGPIPE，pipefail 再把这个赋值判成 141，set -e 直接干掉整个
      # 闸门（实测：最新一份 verify_status=failed 时，Gate F 整段静默消失）。这跟上面
      # G2 那次假红是同一个坑，只是这次踩在自己新写的代码上。
      F4_ALL="$(bk_status_lines verify_status)"
      F4_LAST="$(awk -F'|' '!f && ($1=="ok" || $1=="failed") {print; f=1}' <<< "$F4_ALL")"
      if [[ -z "$F4_LAST" ]]; then
        h "F4 no kept snapshot has ever been drilled (newest says verify_status=${V_ST:-absent})"
      else
        f4_st="$(printf '%s' "$F4_LAST" | cut -d'|' -f1)"
        f4_snap="$(printf '%s' "$F4_LAST" | cut -d'|' -f2)"
        f4_age="$(printf '%s' "$F4_LAST" | cut -d'|' -f3)"
        if [[ "$f4_st" == "failed" ]]; then
          f "F4 the most recent restore drill FAILED ($f4_snap, ${f4_age}h ago) - the backup may not be restorable"
        elif [[ "$f4_age" -gt 26 ]]; then
          f "F4 no successful restore drill in ${f4_age}h (last one $f4_snap) - the daily drill is not running"
        elif [[ "$f4_snap" == "$BK_LATEST_NAME" ]]; then
          p "F4 restore drill passed on the newest snapshot ($f4_snap, ${f4_age}h ago, row counts identical)"
        else
          p "F4 most recent restore drill passed ${f4_age}h ago ($f4_snap); the newest snapshot $BK_LATEST_NAME says verify_status=${V_ST:-absent} - the daily 03:17 run covers it next"
        fi
      fi

      F5_ALL="$(bk_status_lines offsite_status)"
      F5_LAST="$(awk -F'|' '!f && ($1=="ok" || $1=="failed" || $1=="not-configured") {print; f=1}' <<< "$F5_ALL")"
      if [[ -z "$F5_LAST" ]]; then
        h "F5 no offsite copy has ever been attempted (newest says offsite_status=${O_ST:-absent})"
      else
        f5_st="$(printf '%s' "$F5_LAST" | cut -d'|' -f1)"
        f5_snap="$(printf '%s' "$F5_LAST" | cut -d'|' -f2)"
        f5_age="$(printf '%s' "$F5_LAST" | cut -d'|' -f3)"
        case "$f5_st" in
          ok)
            if [[ "$f5_age" -gt 26 ]]; then
              f "F5 no successful offsite copy in ${f5_age}h (last one $f5_snap) - the offsite job is not running"
            else
              p "F5 most recent offsite copy succeeded ${f5_age}h ago ($f5_snap)"
            fi
            ;;
          failed)
            f "F5 the most recent offsite copy FAILED ($f5_snap, ${f5_age}h ago)" ;;
          not-configured)
            h "F5 no offsite target configured - the snapshot sits on the same disk as the database" ;;
          *)
            h "F5 unrecognised offsite status '$f5_st' ($f5_snap)" ;;
        esac
      fi
    fi
  fi
fi

h "F6 an offsite copy exists in a different account/region/host and has been restored from once"

# --------------------------------------------------------------------------
# Gate G - Alerting Delivery
#
# B5/B6/B7 问的是「阈值和政策定没定」；这一组问的是**告警能不能到达人**。
# 报表接口的鉴权在 B 里验过了，这里验的是「有没有人去拉、拉到之后往哪送、送没送成」。
# 只写进 cron 日志不叫出口 —— 没有人会去看那行日志。
# --------------------------------------------------------------------------
echo ""
echo "--- Gate G - Alerting Delivery"

POLLER_SCRIPT="scripts/ops/security_alert_poller.py"
if [[ ! -f "$POLLER_SCRIPT" ]]; then
  f "G1 alert poller missing ($POLLER_SCRIPT)"
elif [[ -z "$_PY" ]]; then
  h "G1 $POLLER_SCRIPT present, but no usable python3 here to parse it"
elif "$_PY" -c "import ast,sys; ast.parse(open(sys.argv[1], encoding='utf-8').read())" \
        "$POLLER_SCRIPT" > /dev/null 2>&1; then
  p "G1 alert poller present and parses ($POLLER_SCRIPT)"
else
  f "G1 $POLLER_SCRIPT does not parse"
fi

if [[ "$ALLOW_NON_PROD" == "true" ]] || ! eq_prod "$APP_ENV_V"; then
  echo "SKIP  G2-G4 host alerting state (not a production release env)"
else
  # 先读「轮询本身跑没跑」，因为 G2（调度里有没有它）和 G3（最近跑成功没有）必须能
  # 互相印证。2026-10-01 生产上出过一次自相矛盾的输出：G2 报 FAIL「没人调度」，
  # 同一秒 G3 报 PASS「273 秒前刚跑成功」。
  ALERT_STATE="${KARMA_ALERT_STATE_PATH:-/opt/karma/state/security-alerts.json}"
  a_run=""; a_ok=""; a_eg=""; a_eg_ok=""; a_eg_err=""; a_eg_src=""
  if [[ -n "$_PY" && -f "$ALERT_STATE" ]]; then
    ALERT_INFO="$("$_PY" - "$ALERT_STATE" <<'PYEOF' 2> /dev/null || true
import json, sys, time
try:
    with open(sys.argv[1], "r", encoding="utf-8") as fh:
        data = json.load(fh)
except Exception:
    print("parse_error=1"); raise SystemExit(0)
now = time.time()
ok_ts = data.get("last_ok_ts")
run_ts = data.get("last_run_ts") or 0
print("run_age=%d" % int(now - float(run_ts)))
print("ok_age=%s" % ("" if ok_ts is None else int(now - float(ok_ts))))
print("egress=%s" % ",".join(data.get("egress") or []))
# 出口「配了」和「发得出去」是两件事。后面三项读的是最近一次真发送的结果。
ok_ts = data.get("last_egress_ok_ts")
print("egress_ok_age=%s" % ("" if ok_ts is None else int(now - float(ok_ts))))
# 折叠成一行的理由：这个值要经过按行解析，里面的换行会把后面的字段顶掉。
print("egress_err=%s" % " ".join(str(data.get("last_egress_error") or "").split())[:160])
print("egress_src=%s" % (data.get("last_egress_src") or ""))
print("active=%d" % len(data.get("active") or []))
PYEOF
)"
    a_run="$(printf '%s\n' "$ALERT_INFO" | sed -n 's/^run_age=//p')"
    a_ok="$(printf '%s\n' "$ALERT_INFO" | sed -n 's/^ok_age=//p')"
    a_eg="$(printf '%s\n' "$ALERT_INFO" | sed -n 's/^egress=//p')"
    a_eg_ok="$(printf '%s\n' "$ALERT_INFO" | sed -n 's/^egress_ok_age=//p')"
    a_eg_err="$(printf '%s\n' "$ALERT_INFO" | sed -n 's/^egress_err=//p')"
    a_eg_src="$(printf '%s\n' "$ALERT_INFO" | sed -n 's/^egress_src=//p')"
  fi

  # G2 到底装没装。这里刻意**不用** `printf '%s' "$blob" | grep -q PAT` 这种写法：
  # 脚本是 `set -o pipefail` 的，grep -q 一命中就退出，上游 printf 拿到 SIGPIPE(141)，
  # pipefail 会把整条管道判成失败 —— 于是「找到了」被判成「没找到」。主机上实测
  # 10 次里错 3 次，不是偶发（这就是上面那次自相矛盾的来源）。改用 herestring：
  # 没有管道，就没有 SIGPIPE。第一次读不到时再重读一遍，别让一次读空变成一记假红。
  sched_blob="$(schedule_text)"
  if ! grep -qaE 'security_alert_poller' <<< "$sched_blob"; then
    sleep 1
    sched_blob="$(schedule_text)"
  fi
  if grep -qaE 'security_alert_poller' <<< "$sched_blob"; then
    p "G2 alert poller is scheduled (cron/systemd-timer references it)"
  elif [[ -n "$a_run" && "$a_run" -le 900 ]]; then
    h "G2 no scheduler found, but a poll went through ${a_run}s ago - the two checks disagree, look by hand"
  else
    f "G2 nothing schedules the alert poller - nobody pulls /v1/security/ops/alerts"
  fi

  if [[ -z "$_PY" ]]; then
    h "G3/G4 alert poller state not inspectable (no usable python3)"
  elif [[ ! -f "$ALERT_STATE" ]]; then
    h "G3 the alert poller has never recorded a run ($ALERT_STATE missing)"
  elif [[ -z "$a_run" ]]; then
    h "G3 alert poller state unreadable ($ALERT_STATE)"
  elif [[ "$a_run" -gt 900 ]]; then
    f "G3 alert poller has not run for ${a_run}s (schedule is not working)"
  elif [[ -z "$a_ok" ]]; then
    h "G3 last alert poll failed (see last_error in $ALERT_STATE)"
  elif [[ "$a_ok" -gt 900 ]]; then
    f "G3 last successful alert poll was ${a_ok}s ago"
  else
    p "G3 alert poller ran ${a_run}s ago and the last poll succeeded"
  fi

  if [[ -n "$_PY" && -f "$ALERT_STATE" ]]; then
    case ",$a_eg," in
      *",webhook,"*|*",telegram,"*|*",smtp,"*)
        # 以前这里只判「配了出口没有」，于是 token 写错、bot 被踢出群、出网被墙，
        # 只要那两行配置还在，G4 就一直 PASS —— 一条都没送到人手里的假绿。
        # 现在判的是**最近一次真发送**的结果：失败过且之后没成功过 = FAIL。
        if [[ -n "$a_eg_err" ]]; then
          f "G4 alert egress configured (${a_eg}) but the last send failed: ${a_eg_err}"
        elif [[ -n "$a_eg_ok" ]]; then
          p "G4 alert egress configured (${a_eg}) and the last send went out ${a_eg_ok}s ago (${a_eg_src:-unknown})"
        else
          h "G4 alert egress configured (${a_eg}) but nothing has been sent yet - run: security_alert_poller.py --test"
        fi ;;
      *)
        h "G4 no alert egress configured (${a_eg:-log}) - alerts only reach the cron log" ;;
    esac
  fi
fi

h "G5 a self-test alert was delivered to a human (run the poller with --test) and acknowledged"

# --------------------------------------------------------------------------
# Gate H - Testnet Go-Live Prerequisites
#
# docs/public-testing/PUBLIC_TESTNET_GO_LIVE-zh.md §4 的那 12 条「Go 前全部 ☐→☑」。
# 以前它们只是文档里一排空方框：没人知道到底缺哪几条、谁去补。能机器判的放这里判，
# 判不了的（「有钱的测试钱包」「人工签字」）明确留给人，不假装判过。
# --------------------------------------------------------------------------
echo ""
echo "--- Gate H - Testnet Go-Live Prerequisites"

if [[ "$ALLOW_NON_PROD" == "true" ]] || ! eq_prod "$APP_ENV_V"; then
  echo "SKIP  H1-H12 (not a production release env)"
else
  # H1 链上三件套
  h1_missing=""
  for _v in TESTNET_RPC_URL ERC20_TOKEN_ADDRESS KARMA_BILATERAL_ADDRESS; do
    [[ -n "$(ev "$_v")" ]] || h1_missing="${h1_missing} ${_v}"
  done
  if [[ -z "$h1_missing" ]]; then
    p "H1 chain config present (TESTNET_RPC_URL / ERC20_TOKEN_ADDRESS / KARMA_BILATERAL_ADDRESS)"
  else
    f "H1 missing chain config:${h1_missing}"
  fi

  # H3 每次 launch 的锚定哈希。它本该由交易流程按笔写入，环境变量里有没有只算参考。
  if [[ -n "$(ev CHAIN_ANCHOR_HASH)" ]]; then
    p "H3 CHAIN_ANCHOR_HASH is pinned in the release env"
  else
    h "H3 CHAIN_ANCHOR_HASH not in env - confirm it is written per trade (it is per-launch, not global)"
  fi

  # H4 / H5 运行态依赖：限流要 fail-closed，数据库必须不是 SQLite
  redis_pong="$(docker exec karma-redis redis-cli ping 2> /dev/null || true)"
  if [[ "$redis_pong" == *PONG* ]]; then
    p "H4 Redis reachable from the host (the limiter can fail closed)"
  else
    h "H4 cannot confirm Redis from here - check by hand"
  fi
  db_url_v="$(ev DATABASE_URL)"
  if [[ "$db_url_v" == postgres* ]]; then
    p "H5 PostgreSQL in use (DATABASE_URL is postgresql, not SQLite)"
  else
    f "H5 DATABASE_URL is not postgresql ('$(printf '%s' "$db_url_v" | cut -c1-24)')"
  fi

  # H6 / H7 已经在别处机器判过，这里不重复报数，只说明去哪看
  echo "SKIP  H6 strong APP_SECRET_KEY / AUTH_API_KEYS (judged by A2/A4)"
  echo "SKIP  H7 on-call primary/backup (judged by E5/E5b)"

  # H8 部署清单。这一条以前只问「文件在不在」—— 而现在文件在了，所以它必须再往前
  # 走一步：**清单、发布环境、链上三方对齐**。理由很直白：清单是人写的声明，写错了比
  # 没有更糟 —— 没有的话人会去链上查，写错了人会信它。
  #
  # 三方分别是：清单自己的结构 / 发布环境里的绑定变量 / 链上事实（chain_id、
  # 合约地址上有没有代码、结算钱包有没有钱）。探不到链记 HUMAN（网络问题不是不一致），
  # 退 3；不一致记 FAIL。
  if [[ ! -f scripts/acceptance/verify-manifest.sh ]]; then
    f "H8 no manifest verifier (scripts/acceptance/verify-manifest.sh missing)"
  elif [[ ! -f deployment-manifest.json ]]; then
    f "H8 no deployment-manifest.json - the deployed addresses are not recorded as a verifiable artifact"
  elif [[ -z "$_PY" ]]; then
    h "H8 deployment-manifest.json present but no usable python3 here to check it against env/chain"
  else
    m_args=(--onchain)
    if [[ -n "$ENV_EXEC_CMD" ]]; then m_args+=(--env-exec "$ENV_EXEC_CMD"); fi
    m_rc=0
    m_out="$(bash scripts/acceptance/verify-manifest.sh "${m_args[@]}" 2>&1)" || m_rc=$?
    case "$m_rc" in
      0)
        m_n="$(printf '%s\n' "$m_out" | grep -c '^PASS' || true)"
        p "H8 manifest matches the release env and the chain (${m_n} checks passed)" ;;
      3)
        h "H8 manifest present, but the chain could not be reached to compare - check by hand" ;;
      *)
        f "H8 the manifest disagrees with the release env / chain"
        printf '%s\n' "$m_out" | grep '^FAIL' | sed 's/^/      /' >&2 || true ;;
    esac
  fi

  h "H2 funded buyer/seller test wallets exist (money, cannot be judged from a shell)"
  h "H9 Karma2 CORE_VERSION.lock matches the public commit (private-repo check)"
  h "H10 OpenClaw MCP registration + a signed path A/B run"
  h "H11 OpenManus / phase1_claw_manus_smoke.py passes against the live testnet"
  h "H12 RUN_TESTNET_ONCHAIN hybrid on-chain smoke"
fi

# --------------------------------------------------------------------------
# 重活: 仓库级守门 + 回归
# --------------------------------------------------------------------------
if [[ "$NO_HEAVY" == "false" ]]; then
  echo ""
  echo "--- Repo gates"
  echo "==> security baseline guard"
  ./scripts/security-baseline-guard.sh
  echo "==> auth/security regression tests"
  python3 -m pytest -q tests/unit/test_auth_security.py tests/unit/test_security_ops.py
  echo "==> public acceptance checks"
  ./scripts/public-p0-acceptance.sh
fi

# --------------------------------------------------------------------------
echo ""
echo "========================================"
printf ' PASS %d   FAIL %d   WARN %d   HUMAN %d\n' "$pass" "$fail" "$warn" "$human"
echo "========================================"
if [[ "$fail" -gt 0 ]]; then
  echo "" >&2
  echo "Blocking failures:" >&2
  for item in "${FAILURES[@]}"; do echo "  - ${item}" >&2; done
  echo "" >&2
  echo "GATE: FAIL" >&2
  exit 1
fi
if [[ "$STRICT" == "true" && "$human" -gt 0 ]]; then
  echo "" >&2
  echo "GATE: FAIL --strict and ${human} item(s) still need human sign-off" >&2
  exit 1
fi
echo ""
echo "GATE: PASS (${human} item(s) still need a human signature -- see docs/SECURITY_RELEASE_GATES.md)"
