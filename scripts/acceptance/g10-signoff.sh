#!/usr/bin/env bash
# G10 人工签核台账（发布负责人用）。
#
# G10 = docs/SECURITY_RELEASE_GATES.md 里那几条脚本判不了的条目。它们不在这个公开
# 仓库里明文打勾 —— 台账是**发布机上**的一份 600 权限 JSON：谁、什么时候、证据在哪
# 能看到（证据一栏只写「在哪能看到」，个人信息 / 私有仓库 / 联系方式不进门）。
#
# 用法（在发布机上）:
#   bash scripts/acceptance/g10-signoff.sh --show
#   bash scripts/acceptance/g10-signoff.sh --sign E4b --by "YMZAI" --evidence "见 /opt/karma/state/oncall-2026-10-12.txt"
#   bash scripts/acceptance/g10-signoff.sh --revoke E4b --by "YMZAI"
#   KARMA_G10_SIGNOFF=/tmp/g10.json bash scripts/acceptance/g10-signoff.sh --list
#
# 台账默认 /opt/karma/state/g10-sign-off.json（600）。public-beta-security-gate.sh
# 读到 status=signed 的条目就把那一条按 PASS 计；没签、读不到，仍然是 HUMAN。
# 本仓库里只有 security/audit/g10-sign-off.example.json 这份样例。
set -euo pipefail

ITEMS="A4d E4b E6b H2 H3 H9 H10 H11 H12"
LEDGER="${KARMA_G10_SIGNOFF:-/opt/karma/state/g10-sign-off.json}"
ACTION="show"; ITEM=""; BY=""; EVIDENCE=""

die()   { echo "ERR  $*" >&2; exit 2; }
usage() { sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --sign)     ACTION="sign";   ITEM="${2:-}"; shift ;;
    --revoke)   ACTION="revoke"; ITEM="${2:-}"; shift ;;
    --list)     ACTION="list" ;;
    --show)     ACTION="show" ;;
    --ledger)   LEDGER="${2:-}"; shift ;;
    --by)       BY="${2:-}"; shift ;;
    --evidence) EVIDENCE="${2:-}"; shift ;;
    -h|--help)  usage; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
  shift
done

case "$ACTION" in
  sign|revoke)
    [[ -n "$ITEM" ]] || die "--sign / --revoke needs an item id"
    case " $ITEMS " in
      *" $ITEM "*) ;;
      *) die "unknown G10 item '${ITEM}' (known: ${ITEMS})" ;;
    esac
    [[ -n "$BY" ]] || die "--sign / --revoke needs --by \"<who signs>\""
    ;;
esac

PY=""
for cand in python3 python; do
  if command -v "$cand" > /dev/null 2>&1 && "$cand" -c 'import json' > /dev/null 2>&1; then
    PY="$cand"; break
  fi
done
[[ -n "$PY" ]] || die "no usable python3 / python on PATH"

G10_LEDGER="$LEDGER" G10_ACTION="$ACTION" G10_ITEM="$ITEM" \
G10_BY="$BY" G10_EVIDENCE="$EVIDENCE" G10_ITEMS="$ITEMS" \
  "$PY" - <<'PYEOF'
import datetime, json, os

ledger = os.environ["G10_LEDGER"]
action = os.environ["G10_ACTION"]
item = os.environ["G10_ITEM"]
who = os.environ["G10_BY"]
evidence = os.environ["G10_EVIDENCE"]
known = os.environ["G10_ITEMS"].split()

# 台账是签名本体：不跟着符号链接写（免得有人把台账指到别处），也不是「读坏了就覆盖」。
if os.path.islink(ledger):
    print("ERR  %s is a symlink - refusing to write through it" % ledger)
    raise SystemExit(2)
data = {"version": 1, "items": []}
if os.path.exists(ledger):
    try:
        loaded = json.load(open(ledger, encoding="utf-8"))
    except Exception as exc:
        print("ERR  %s is not readable JSON (%s) - fix it by hand, refusing to overwrite" % (ledger, exc))
        raise SystemExit(2)
    if isinstance(loaded, dict):
        data["version"] = loaded.get("version", 1)
        if isinstance(loaded.get("items"), list):
            data["items"] = loaded["items"]


def record_for(recs, key):
    for rec in recs:
        if isinstance(rec, dict) and rec.get("item") == key:
            return rec
    rec = {"item": key}
    recs.append(rec)
    return rec


if action in ("list", "show"):
    print("G10 ledger: %s" % ledger)
    if not os.path.exists(ledger):
        print("  (not created yet - every item is unsigned)")
    for key in known:
        rec = record_for(data["items"], key) if os.path.exists(ledger) else {"item": key}
        status = rec.get("status", "pending")
        if status == "signed":
            print("  %-4s signed   by %s on %s   evidence: %s"
                  % (key, rec.get("signed_by", "?"), rec.get("signed_at", "?"), rec.get("evidence") or "-"))
        elif status == "revoked":
            print("  %-4s REVOKED  by %s on %s" % (key, rec.get("revoked_by", "?"), rec.get("revoked_at", "?")))
        else:
            print("  %-4s pending" % key)
    for rec in data["items"]:
        if isinstance(rec, dict) and rec.get("item") not in known:
            print("  %s unknown item in the ledger - left untouched" % rec.get("item"))
    raise SystemExit(0)

now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
rec = record_for(data["items"], item)
if action == "sign":
    rec.update({"item": item, "status": "signed", "signed_by": who, "signed_at": now,
                "evidence": evidence or ""})
    for stale in ("revoked_by", "revoked_at"):
        rec.pop(stale, None)
    did = "SIGNED"
else:
    rec.update({"item": item, "status": "revoked", "revoked_by": who, "revoked_at": now})
    did = "REVOKED"

folder = os.path.dirname(os.path.abspath(ledger))
if not os.path.isdir(folder):
    os.makedirs(folder, mode=0o700)
tmp = "%s.tmp.%d" % (ledger, os.getpid())
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(data, fh, ensure_ascii=False, indent=2)
    fh.write("\n")
os.chmod(tmp, 0o600)
os.replace(tmp, ledger)
print("%s %s by %s at %s -> %s" % (did, item, who, now, ledger))
PYEOF
