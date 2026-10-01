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
      if ! printf '%s\n' "$key_actors" | grep -qxF "$listed_actor"; then
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
    h "B4 /v1/security/ops/alerts not verified from this host (probe unavailable/transport error)"
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
    h "C2b could not reach ${BASE_URL%/}/health - X-Request-Id not verified"
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

  # F2 到底装没装：crontab / cron.d / /etc/crontab / systemd timer 里有没有引用它
  sched_seen=0; sched_hit=0; sched_blob=""
  sched_blob+="$(crontab -l 2> /dev/null || true)"$'\n'; sched_seen=1
  if [[ -d /etc/cron.d ]]; then
    sched_seen=1
    sched_blob+="$(cat /etc/cron.d/* 2> /dev/null || true)"$'\n'
  fi
  if [[ -r /etc/crontab ]]; then
    sched_seen=1
    sched_blob+="$(cat /etc/crontab 2> /dev/null || true)"$'\n'
  fi
  if command -v systemctl > /dev/null 2>&1; then
    sched_seen=1
    sched_blob+="$(systemctl list-timers --all --no-pager 2> /dev/null || true)"$'\n'
    sched_blob+="$(systemctl list-unit-files --no-pager 2> /dev/null || true)"$'\n'
  fi
  if printf '%s' "$sched_blob" | grep -Eq 'karma-backup|ops/backup\.sh'; then sched_hit=1; fi
  if [[ "$sched_seen" -eq 0 ]]; then
    h "F2 backup schedule not inspectable from here - confirm the timer on the host"
  elif [[ "$sched_hit" -eq 1 ]]; then
    p "F2 backup is scheduled (cron/systemd-timer references the backup script)"
  else
    f "F2 backup script exists but nothing schedules it - it will never run on its own"
  fi

  BK_LATEST="$(ls -1dt "$BK_ROOT"/*/ 2> /dev/null | head -1 | sed 's:/$::')"
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
      h "F4 no manifest.txt next to the newest dump - cannot tell whether a restore drill ran"
    else
      V_ST="$(sed -n 's/^verify_status=//p' "$BK_MANIFEST" | tail -1)"
      case "$V_ST" in
        ok)     p "F4 restore drill passed on the newest snapshot (--verify, row counts identical)" ;;
        failed) f "F4 restore drill FAILED on the newest snapshot - the backup may not be restorable" ;;
        *)      h "F4 restore drill not run on the newest snapshot (verify_status=${V_ST:-absent})" ;;
      esac
      O_ST="$(sed -n 's/^offsite_status=//p' "$BK_MANIFEST" | tail -1)"
      case "$O_ST" in
        ok)             p "F5 offsite copy of the newest snapshot succeeded" ;;
        failed)         f "F5 offsite copy of the newest snapshot FAILED" ;;
        not-configured) h "F5 no offsite copy configured - the snapshot sits on the same disk as the database" ;;
        *)              h "F5 no offsite copy recorded on the newest snapshot (offsite_status=${O_ST:-absent})" ;;
      esac
    fi
  fi
fi

h "F6 an offsite copy exists in a different account/region/host and has been restored from once"

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
