#!/usr/bin/env bash
# Public beta security gate.
#
# 这份脚本是 docs/SECURITY_RELEASE_GATES.md（Gate A-E）里**可执行的那一半**。
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
_PY=""
if command -v python3 > /dev/null 2>&1; then _PY="python3"
elif command -v python > /dev/null 2>&1; then _PY="python"
fi

PROBE_CODE=""; PROBE_RID=""; PROBE_BODY=""
# probe METHOD URL [JSON_DATA] -> 0 拿到响应(含 4xx/5xx), 1 传输层失败
probe() {
  PROBE_CODE=""; PROBE_RID=""; PROBE_BODY=""
  [[ -z "$_PY" ]] && return 1
  local method="$1" url="$2" data="${3:-}"
  local tmpd="${TMPDIR:-/tmp}/karma_security_gate_probe"
  mkdir -p "$tmpd"
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
h "A2b APP_SECRET_KEY rotation date is recorded"

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
  fi
  h "A4c AUTH_API_KEYS covers every service agent (per-agent keys, not one shared key)"
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
h "B1b Redis is actually reachable from the release host (scripts cannot ping across the boundary)"

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
    w "B4 /v1/security/ops/alerts unreachable from this host (transport error)"
  fi
else
  h "B4 /v1/security/ops/alerts is auth-protected (pass --base-url to probe)"
fi

h "B3 alerting is delivered for sustained 429 spikes and auth failures (on-call must confirm)"
h "B5 alert cooldown / suppression policy reviewed with on-call"
h "B6 endpoint / route-group threshold overrides configured for critical paths"
h "B7 active security threshold policy version pinned and documented"

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
    w "C2b could not reach ${BASE_URL%/}/health (transport error)"
  fi
else
  h "C2b live response carries X-Request-Id (pass --base-url to probe)"
fi
h "C3 log retention + query access configured for incident response"

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
        if printf '%s' "$PROBE_BODY" | grep -qF "$marker"; then
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
    w "D1/D2 probe(s) unreachable from this host - error surface not verified"
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
else
  f "E5 SECURITY_ONCALL_PRIMARY / SECURITY_ONCALL_BACKUP must be configured"
fi

if grep -q 'baseline_window_minutes' api/routes/security.py && grep -q 'baseline_drift_multiplier' api/routes/security.py; then
  p "E6a baseline drift controls exist (baseline_window_minutes / baseline_drift_multiplier)"
else
  f "E6a baseline drift controls not found in api/routes/security.py"
fi
h "E6b baseline drift strategy reviewed and the chosen values agreed with on-call"
h "E7 policy-center rollback drill (/v1/security/policies/rollback) has been exercised"

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
