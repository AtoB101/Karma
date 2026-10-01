#!/usr/bin/env bash
# Karma production snapshot / restore drill / offsite copy.
#
# 为什么要有这个脚本
# ------------------
# 生产只有一台 VPS，PostgreSQL、Redis 和工作树都在同一块盘(/dev/vda3)上。
# 备份只落在同一块盘 = 盘坏或机器丢就一起没。这个脚本负责三件事：
#
#   1. 打一份自包含快照：env / 工作树 / git bundle / pg_dump / redis dump + manifest.txt
#   2. --verify：把 dump 真恢复进一个一次性 postgres 容器，逐表比对行数。
#      这不是「备份文件在不在」的检查，是「备出来的东西能不能用」的检查。
#   3. --offsite：把可搬运的部分推到离站目标(s3 / rsync / scp)。
#
# 用法：
#   backup.sh                   打一份快照（默认保留 14 份）
#   backup.sh --verify          打完立刻做恢复演练
#   backup.sh --verify-latest   不重新备份，演练最近一份快照
#   backup.sh --offsite         打完把 dump/redis 推离站
#   backup.sh --json            打一行 JSON 结果（给闸门 / CI 读）
#   backup.sh --help
#
# 环境变量（服务器上都有默认值，正常不用传）：
#   KARMA_BACKUP_ROOT            默认 /opt/karma/backups
#   KARMA_REPO_DIR               默认 /opt/karma/repo
#   KARMA_ENV_FILE               默认 /opt/karma/.env
#   KARMA_POSTGRES_CONTAINER     默认 karma-postgres
#   KARMA_REDIS_CONTAINER        默认 karma-redis
#   KARMA_BACKUP_KEEP            默认 14
#   KARMA_BACKUP_OFFSITE         none | s3 | rsync | scp        默认 none
#   KARMA_BACKUP_OFFSITE_TARGET  rsync/scp 目标，如 user@host:/srv/karma-backups
#   KARMA_BACKUP_S3_ENDPOINT/_BUCKET/_PREFIX/_REGION/_ACCESS_KEY/_SECRET_KEY
#   KARMA_BACKUP_SKIP_ENV        1 = 快照里不放 env.backup
#   KARMA_OPS_ENV                默认 /opt/karma/.env.ops（主机级运维配置，有就 source）
#
# 退出码：0 成功；1 备份失败；2 恢复演练失败；3 离站失败；4 参数错。
set -euo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 主机级运维配置：离站目标这类东西不该塞进 .env（那是应用读的），也不该每次改 cron。
# 有 /opt/karma/.env.ops 就 source 它，里面的 KARMA_BACKUP_* 覆盖默认值。
OPS_ENV="${KARMA_OPS_ENV:-/opt/karma/.env.ops}"
if [[ -r "$OPS_ENV" ]]; then
  set -a
  # shellcheck disable=SC1090
  . "$OPS_ENV"
  set +a
fi

BK_ROOT="${KARMA_BACKUP_ROOT:-/opt/karma/backups}"
REPO_DIR="${KARMA_REPO_DIR:-/opt/karma/repo}"
ENV_FILE="${KARMA_ENV_FILE:-/opt/karma/.env}"
PG_CONTAINER="${KARMA_POSTGRES_CONTAINER:-karma-postgres}"
REDIS_CONTAINER="${KARMA_REDIS_CONTAINER:-karma-redis}"
KEEP="${KARMA_BACKUP_KEEP:-14}"
OFFSITE="${KARMA_BACKUP_OFFSITE:-none}"
VERIFY_IMAGE="${KARMA_BACKUP_VERIFY_IMAGE:-postgres:16-alpine}"

DO_VERIFY=false
VERIFY_LATEST=false
DO_OFFSITE=false
DO_JSON=false

usage() { sed -n '3,33p' "$0" | sed 's/^# \{0,1\}//'; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --verify)        DO_VERIFY=true ;;
    --verify-latest) VERIFY_LATEST=true ;;
    --offsite)       DO_OFFSITE=true ;;
    --json)          DO_JSON=true ;;
    --keep)          KEEP="${2:-14}"; shift ;;
    --out)           BK_ROOT="${2:-}"; shift ;;
    -h|--help)       usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 4 ;;
  esac
  shift
done

log()  { echo "[$(date '+%H:%M:%S')] $*"; }
say()  { if [[ "$DO_JSON" == "false" ]]; then echo "$*"; else echo "$*" >&2; fi; }
warn() { echo "[$(date '+%H:%M:%S')] WARN $*" >&2; }
die()  { echo "[$(date '+%H:%M:%S')] ERROR $*" >&2; exit "${2:-1}"; }

need() { command -v "$1" > /dev/null 2>&1 || die "missing required command: $1"; }
need docker
need gzip
need tar

SHA=""
if command -v sha256sum > /dev/null 2>&1; then SHA="sha256sum"; elif command -v shasum > /dev/null 2>&1; then SHA="shasum -a 256"; fi

# 这台机器上有没有能用的 python3（离站上传要用）。Windows 上的 python3 可能是
# Store 占位程序：command -v 找得到、一执行就 Permission denied，所以真跑一次再选。
PY=""
for cand in python3 python; do
  if command -v "$cand" > /dev/null 2>&1 && "$cand" -c 'import sys' > /dev/null 2>&1; then PY="$cand"; break; fi
done

# --------------------------------------------------------------------------
# 读 .env 里的 POSTGRES_USER / POSTGRES_DB（只用来连库，别的不需要）
# --------------------------------------------------------------------------
PG_USER="karma"; PG_DB="karma"
if [[ -r "$ENV_FILE" ]]; then
  PG_USER="$(sed -n 's/^[[:space:]]*POSTGRES_USER=//p' "$ENV_FILE" | tail -1 | tr -d '"'"'"' \r')"
  PG_DB="$(sed -n 's/^[[:space:]]*POSTGRES_DB=//p' "$ENV_FILE" | tail -1 | tr -d '"'"'"' \r')"
fi
[[ -n "$PG_USER" ]] || PG_USER="karma"
[[ -n "$PG_DB" ]] || PG_DB="karma"

pg() { docker exec -i "$PG_CONTAINER" "$@"; }

sha()   { [[ -f "$1" && -n "$SHA" ]] && $SHA "$1" | cut -d' ' -f1 || echo "-"; }
fbytes() { [[ -f "$1" ]] && stat -c '%s' "$1" 2>/dev/null || echo 0; }

# 生成「每张表一行计数」的 UNION ALL 查询（不执行）
counts_sql() {
  pg psql -U "$PG_USER" -d "$1" -tAc \
    "SELECT string_agg(format('SELECT %L AS t, count(*) AS n FROM %I.%I', schemaname||'.'||tablename, schemaname, tablename), ' UNION ALL ' ORDER BY tablename) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema')"
}

# 在某个 postgres 客户端上下文里执行 counts 查询。$1=容器名("" = 本机 pg 容器), $2=查询文件
run_counts() {
  local c="$1" qf="$2"
  docker cp "$qf" "$c:/tmp/_karma_counts.sql" > /dev/null 2>&1
  docker exec -i "$c" psql -U "$PG_USER" -d "$PG_DB" -q -tAF'|' -f /tmp/_karma_counts.sql \
    | sed '/^$/d' | sort
}

latest_snapshot() { ls -1dt "$BK_ROOT"/*/ 2>/dev/null | head -1 | sed 's:/$::'; }

# --------------------------------------------------------------------------
# 恢复演练：把 dump 恢复进一次性容器，逐表比对行数
# --------------------------------------------------------------------------
run_verify() {
  local snap="$1"
  local dump="$snap/karma-db.sql.gz"
  [[ -f "$dump" ]] || { warn "no dump at $dump"; return 3; }
  if ! docker image inspect "$VERIFY_IMAGE" > /dev/null 2>&1; then
    docker pull "$VERIFY_IMAGE" > /dev/null 2>&1 \
      || { warn "cannot obtain $VERIFY_IMAGE (no local image, pull failed) - verify skipped"; return 3; }
  fi

  local cname="karma-backup-verify-$$"
  local logf="$snap/verify.restore.log"
  say "==> restore drill: $(basename "$snap") -> throwaway $VERIFY_IMAGE"
  docker rm -f "$cname" > /dev/null 2>&1 || true
  docker run -d --name "$cname" --network none \
    -e POSTGRES_PASSWORD=verifyonly -e POSTGRES_USER="$PG_USER" -e POSTGRES_DB="$PG_DB" \
    -v "$snap:/b:ro" "$VERIFY_IMAGE" > /dev/null 2>&1 \
    || { warn "cannot start verify container"; return 3; }

  local i ok=1
  for i in $(seq 1 60); do
    docker exec "$cname" pg_isready -U "$PG_USER" -d "$PG_DB" > /dev/null 2>&1 && { ok=0; break; }
    sleep 1
  done
  if [[ "$ok" != "0" ]]; then
    warn "verify container never became ready"
    docker logs "$cname" > "$logf" 2>&1 || true
    docker rm -f "$cname" > /dev/null 2>&1 || true
    return 2
  fi

  # 恢复日志留档：出问题时证据在快照里，不用再猜
  : > "$logf"
  local rc=0
  set +e
  docker exec -i "$cname" psql -q -v ON_ERROR_STOP=1 -U "$PG_USER" -d "$PG_DB" \
      -c "SELECT 1" > /dev/null 2>&1
  gunzip -c "$dump" | docker exec -i "$cname" psql -q -v ON_ERROR_STOP=1 -U "$PG_USER" -d "$PG_DB" \
      > "$logf" 2>&1
  rc=$?
  set -e
  if [[ "$rc" != "0" ]]; then
    warn "restore failed (psql rc=$rc) - see $logf"
    tail -20 "$logf" >&2 || true
    docker rm -f "$cname" > /dev/null 2>&1 || true
    return 2
  fi

  local qf="$snap/verify.counts.sql"
  counts_sql "$PG_DB" > "$qf"
  local live_txt="$snap/verify.live_rows.txt" rest_txt="$snap/verify.restored_rows.txt"
  run_counts "$PG_CONTAINER" "$qf" > "$live_txt"
  run_counts "$cname" "$qf" > "$rest_txt"
  docker rm -f "$cname" > /dev/null 2>&1 || true

  local live_n rest_n diff_n
  live_n="$(wc -l < "$live_txt")"
  rest_n="$(wc -l < "$rest_txt")"
  if ! diff -q "$live_txt" "$rest_txt" > /dev/null 2>&1; then
    diff_n="$(diff "$live_txt" "$rest_txt" | grep -c '^[<>]' || true)"
    warn "restore drill MISMATCH: live=$live_n tables, restored=$rest_n tables, ${diff_n} differing rows"
    diff "$live_txt" "$rest_txt" | head -20 >&2 || true
    return 2
  fi
  say "==> restore drill OK: ${live_n} tables, every row count identical"
  return 0
}

# --------------------------------------------------------------------------
# 离站
# --------------------------------------------------------------------------
run_offsite() {
  local snap="$1"
  case "$OFFSITE" in
    none)
      warn "OFFSITE not configured (KARMA_BACKUP_OFFSITE=none)"
      warn "  -> this snapshot lives on the same disk as the database; set KARMA_BACKUP_OFFSITE to s3/rsync/scp"
      return 4 ;;
    s3)
      [[ -n "$PY" ]] || { warn "s3 offsite needs a working python3"; return 3; }
      local ep="${KARMA_BACKUP_S3_ENDPOINT:-}" bucket="${KARMA_BACKUP_S3_BUCKET:-}"
      local prefix="${KARMA_BACKUP_S3_PREFIX:-karma-backups}"
      local region="${KARMA_BACKUP_S3_REGION:-us-east-1}"
      local ak="${KARMA_BACKUP_S3_ACCESS_KEY:-${MINIO_ACCESS_KEY:-}}"
      local sk="${KARMA_BACKUP_S3_SECRET_KEY:-${MINIO_SECRET_KEY:-}}"
      if [[ -z "$ep" || -z "$bucket" || -z "$ak" || -z "$sk" ]]; then
        warn "s3 offsite missing config (need endpoint/bucket/access_key/secret_key)"; return 3
      fi
      local name f; name="$(basename "$snap")"
      for f in karma-db.sql.gz redis-dump.rdb manifest.txt; do
        [[ -f "$snap/$f" ]] || continue
        say "==> offsite s3://$bucket/$prefix/$name/$f"
        "$PY" "$SELF_DIR/s3_put.py" \
          --endpoint "$ep" --bucket "$bucket" --key "$prefix/$name/$f" \
          --file "$snap/$f" --access-key "$ak" --secret-key "$sk" --region "$region" \
          || { warn "s3 upload failed: $f"; return 3; }
      done
      return 0 ;;
    rsync|scp)
      local target="${KARMA_BACKUP_OFFSITE_TARGET:-}"
      [[ -n "$target" ]] || { warn "$OFFSITE offsite needs KARMA_BACKUP_OFFSITE_TARGET"; return 3; }
      if [[ "$OFFSITE" == "rsync" ]]; then
        command -v rsync > /dev/null 2>&1 || { warn "rsync not installed"; return 3; }
        say "==> offsite rsync -> $target"
        rsync -a --partial --include='karma-db.sql.gz' --include='redis-dump.rdb' \
              --include='manifest.txt' --exclude='*' "$snap/" "$target/" \
          || { warn "rsync failed"; return 3; }
      else
        command -v scp > /dev/null 2>&1 || { warn "scp not installed"; return 3; }
        say "==> offsite scp -> $target"
        scp -q "$snap/karma-db.sql.gz" "$snap/redis-dump.rdb" "$snap/manifest.txt" "$target/" \
          || { warn "scp failed"; return 3; }
      fi
      return 0 ;;
    *) warn "unknown KARMA_BACKUP_OFFSITE='$OFFSITE'"; return 3 ;;
  esac
}

# --------------------------------------------------------------------------
# --verify-latest：只演练，不备份
# --------------------------------------------------------------------------
if [[ "$VERIFY_LATEST" == "true" ]]; then
  snap="$(latest_snapshot)"
  [[ -n "$snap" ]] || die "no snapshot under $BK_ROOT"
  vrc=0
  set +e; run_verify "$snap"; vrc=$?; set -e
  case "$vrc" in
    0) echo "VERIFY ok snapshot=$snap" ;;
    3) echo "VERIFY skipped snapshot=$snap" ;;
    *) echo "VERIFY failed snapshot=$snap" >&2; exit 2 ;;
  esac
  exit 0
fi

# --------------------------------------------------------------------------
# 打快照
# --------------------------------------------------------------------------
TS="$(date +%Y%m%d-%H%M%S)"
BK="$BK_ROOT/$TS"
mkdir -p "$BK" || die "cannot create $BK"

say "==> snapshot: $BK"
say "[1/7] env"
if [[ "${KARMA_BACKUP_SKIP_ENV:-0}" != "1" && -r "$ENV_FILE" ]]; then
  cp -a "$ENV_FILE" "$BK/env.backup"
  chmod 600 "$BK/env.backup"
  say "      env.backup (600) - production secrets; never sync this file offsite"
else
  say "      skipped"
fi

say "[2/7] working tree (tar.gz)"
tar czf "$BK/repo-worktree.tar.gz" -C "$(dirname "$REPO_DIR")" \
  --exclude="$(basename "$REPO_DIR")/.git" "$(basename "$REPO_DIR")" 2> /dev/null \
  || warn "worktree tar failed (continuing)"

say "[3/7] git refs / diff"
if [[ -d "$REPO_DIR/.git" || -f "$REPO_DIR/.git" ]]; then
  (cd "$REPO_DIR" && git diff > "$BK/worktree.patch" 2>/dev/null) || true
  (cd "$REPO_DIR" && git status --porcelain > "$BK/worktree.status.txt" 2>/dev/null) || true
  (cd "$REPO_DIR" && git bundle create "$BK/repo-refs.bundle" --all > /dev/null 2>&1) \
    || rm -f "$BK/repo-refs.bundle"
else
  warn "$REPO_DIR is not a git checkout - skipping bundle"
fi

say "[4/7] postgres dump"
if docker exec -i "$PG_CONTAINER" pg_dump -U "$PG_USER" -d "$PG_DB" --no-owner \
     2> "$BK/pg_dump.stderr" | gzip > "$BK/karma-db.sql.gz"; then
  rm -f "$BK/pg_dump.stderr"
else
  warn "pg_dump failed - see $BK/pg_dump.stderr"
fi

say "[5/7] redis snapshot"
docker exec "$REDIS_CONTAINER" redis-cli SAVE > /dev/null 2>&1 || warn "redis SAVE failed"
docker cp "$REDIS_CONTAINER:/data/dump.rdb" "$BK/redis-dump.rdb" > /dev/null 2>&1 \
  || warn "redis dump.rdb copy failed"

say "[6/7] manifest"
DB_TABLES=0
if [[ -s "$BK/karma-db.sql.gz" ]]; then
  qf="$BK/verify.counts.sql"
  counts_sql "$PG_DB" > "$qf" 2>/dev/null || true
  if [[ -s "$qf" ]]; then DB_TABLES="$(run_counts "$PG_CONTAINER" "$qf" | wc -l)"; else rm -f "$qf"; fi
fi
GIT_REV="unknown"; GIT_DIRTY="unknown"
if [[ -d "$REPO_DIR/.git" || -f "$REPO_DIR/.git" ]]; then
  GIT_REV="$(cd "$REPO_DIR" && git rev-parse HEAD 2>/dev/null || echo unknown)"
  if [[ -n "$(cd "$REPO_DIR" && git status --porcelain 2>/dev/null)" ]]; then GIT_DIRTY="true"; else GIT_DIRTY="false"; fi
fi
{
  echo "created_at=$(date -Iseconds)"
  echo "host=$(hostname)"
  echo "snapshot=$BK"
  echo "git_rev=$GIT_REV"
  echo "git_dirty=$GIT_DIRTY"
  echo "db_tables=$DB_TABLES"
  echo "db_dump_bytes=$(fbytes "$BK/karma-db.sql.gz")"
  echo "verify_status=pending"
  echo "offsite_status=pending"
  echo "offsite_target=$OFFSITE"
  for _f in env.backup repo-worktree.tar.gz worktree.patch worktree.status.txt \
            karma-db.sql.gz redis-dump.rdb repo-refs.bundle; do
    [[ -f "$BK/$_f" ]] || continue
    echo "file=$_f bytes=$(fbytes "$BK/$_f") sha256=$(sha "$BK/$_f")"
  done
} > "$BK/manifest.txt"

say "[7/7] contents"
ls -la "$BK" 2>/dev/null | sed 's/^/      /' || true
say "      size: $(du -sh "$BK" 2>/dev/null | cut -f1)"

# --------------------------------------------------------------------------
# 演练 + 离站（快照已经落盘，这两步失败不回滚快照）
# --------------------------------------------------------------------------
verify_status="skipped"
if [[ "$DO_VERIFY" == "true" ]]; then
  vrc=0; set +e; run_verify "$BK"; vrc=$?; set -e
  case "$vrc" in
    0) verify_status="ok" ;;
    3) verify_status="skipped-no-docker-image" ;;
    *) verify_status="failed" ;;
  esac
fi
sed -i "s/^verify_status=.*/verify_status=$verify_status/" "$BK/manifest.txt" 2>/dev/null || true

offsite_status="skipped"
if [[ "$DO_OFFSITE" == "true" || "$OFFSITE" != "none" ]]; then
  orc=0; set +e; run_offsite "$BK"; orc=$?; set -e
  case "$orc" in
    0) offsite_status="ok" ;;
    4) offsite_status="not-configured" ;;
    *) offsite_status="failed" ;;
  esac
fi
sed -i "s/^offsite_status=.*/offsite_status=$offsite_status/" "$BK/manifest.txt" 2>/dev/null || true

# --------------------------------------------------------------------------
# 轮转：留最新 KEEP 份
# --------------------------------------------------------------------------
if [[ -d "$BK_ROOT" && "$KEEP" -gt 0 ]]; then
  while read -r old; do
    [[ -n "$old" ]] || continue
    rm -rf "$old" && say "==> rotated out: $old"
  done < <(ls -1dt "$BK_ROOT"/*/ 2>/dev/null | tail -n "+$((KEEP + 1))")
fi

if [[ "$DO_JSON" == "true" ]]; then
  printf '{"snapshot":"%s","ts":"%s","git_rev":"%s","db_tables":%s,"verify":"%s","offsite":"%s","bytes":%s}\n' \
    "$BK" "$(date -Iseconds)" "$GIT_REV" "${DB_TABLES:-0}" "$verify_status" "$offsite_status" \
    "$(du -sb "$BK" 2>/dev/null | cut -f1 || echo 0)"
else
  say "==> done ($BK)"
fi

if [[ "$verify_status" == "failed" ]]; then exit 2; fi
if [[ "$offsite_status" == "failed" ]]; then exit 3; fi
exit 0