# -*- coding: utf-8 -*-
"""alembic 版本列宽：迁移/盖章之前先摆正，别让部署卡在「写版本号」那一下。

背景（2026-10-13 沙箱库 karma_testnet 实测）：alembic 自建 ``alembic_version`` 时把
``version_num`` 定成 VARCHAR(32)，而本仓库的 revision id 比这长（当前的 head 就有 35
个字符）。0050 起每个迁移都「顺带」放宽一次，但表结构由 ``create_all`` 建、迁移历史靠
``karma db-baseline`` 盖章出来的库从没跑过那句 ALTER —— 于是 ``upgrade head`` 会在最后
一步炸：

    UPDATE alembic_version SET version_num='0065_runtime_safety_manual_override'
    -> StringDataRightTruncation: value too long for type character varying(32)

表全建完、整个事务回滚、``alembic current`` 仍停在 0064，而且这个库之后**永远**迁不动。

这里直接用仓库里真实的 ``deploy/karma`` 跑回归（``docker`` / ``compose`` 都换成假的
shell 脚本），断言：窄列要放宽、255 不折腾、没有版本表时按 255 建、以及 ``cmd_migrate``
「没有版本表 -> 提示先 db-baseline」那道闸不能被建表动作架空。
"""

from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
CLI = ROOT / "deploy" / "karma"

FAKE_DOCKER = """#!/usr/bin/env bash
# 假的 docker：deploy/karma 里这些 helper 只用到 psql 查询与 ps/ inspect。
args="$*"
case "$args" in
  *character_maximum_length*)
    [ -n "${FAKE_WIDTH:-}" ] && printf '%s\\n' "$FAKE_WIDTH"
    exit 0 ;;
  *"create table if not exists alembic_version"*) echo "CREATE" >> "${FAKE_LOG:-/dev/null}"; exit 0 ;;
  *"alter table alembic_version"*) echo "ALTER" >> "${FAKE_LOG:-/dev/null}"; exit 0 ;;
  *information_schema.tables*)
    [ -n "${FAKE_HAS_TABLE:-}" ] && echo 1
    exit 0 ;;
  *"image inspect"*) exit 0 ;;
  *"ps --format"*) echo karma-postgres; exit 0 ;;
esac
exit 0
"""

DRIVER = r"""
set -u
REAL_CLI="$1"; T="$2"
KARMA_CLI_LIB_ONLY=1
export KARMA_CLI_LIB_ONLY
[ -d "$T" ] || { echo "SETUP-FAILED $T" >&2; exit 9; }
# 一定要 source **副本**：这个文件里的 sync_cli 会把它自己装回原位。
CLI_FILE="$T/sourced-cli"
cp "$REAL_CLI" "$CLI_FILE" || exit 9
. "$CLI_FILE"
real_fp=$(cli_fingerprint "$REAL_CLI")

FAKE_LOG="$T/psql.log"
: > "$FAKE_LOG"
export FAKE_LOG
PATH="$T/bin:$PATH"
export PATH
REPO_DIR="$T/repo"
ENV_FILE="$T/.env"
export REPO_DIR ENV_FILE
: > "$ENV_FILE"

# compose 换成记录调用，别真的去碰 docker
compose() { echo "COMPOSE $*" >> "$FAKE_LOG"; return 0; }

flat() { printf '%s' "$1" | tr '\n' '|'; }
loglines() { tr '\n' '|' < "$FAKE_LOG"; }
reset_log() { : > "$FAKE_LOG"; }

# A) 窄列 -> 放宽
FAKE_WIDTH=32; export FAKE_WIDTH; reset_log
oA=$(ensure_alembic_version_width 2>&1 || true)
echo "A<<$(flat "$oA")>>"
echo "A2<<$(loglines)>>"

# B) 已经是 255 -> 空操作（线上就是这种，不该刷屏）
FAKE_WIDTH=255; export FAKE_WIDTH; reset_log
oB=$(ensure_alembic_version_width 2>&1 || true)
echo "B<<$(flat "$oB")>>"
echo "B2<<$(loglines)>>"

# C) 没有版本表 -> 自己按 255 建出来（别让 alembic 建出 32 的那个）
FAKE_WIDTH=; export FAKE_WIDTH; reset_log
oC=$(ensure_alembic_version_width 2>&1 || true)
echo "C<<$(flat "$oC")>>"
echo "C2<<$(loglines)>>"

# D) cmd_migrate：没有版本表时必须照旧停下并提示 db-baseline，不能自己把表建出来
FAKE_WIDTH=; FAKE_HAS_TABLE=; export FAKE_WIDTH FAKE_HAS_TABLE; reset_log
oD=$( ( cmd_migrate ) 2>&1 || true )
echo "D<<$(flat "$oD")>>"
echo "D2<<$(loglines)>>"

# E) cmd_migrate：窄列必须先放宽，再跑 upgrade head
FAKE_WIDTH=32; FAKE_HAS_TABLE=1; export FAKE_WIDTH FAKE_HAS_TABLE; reset_log
oE=$( ( cmd_migrate ) 2>&1 || true )
echo "E<<$(flat "$oE")>>"
echo "E2<<$(loglines)>>"

# F) db-baseline：没有版本表时先按 255 建，再盖章
FAKE_WIDTH=; export FAKE_WIDTH; reset_log
oF=$( ( cmd_db_baseline 0047_identity_provider ) 2>&1 || true )
echo "F<<$(flat "$oF")>>"
echo "F2<<$(loglines)>>"

# Z) 整个实验不许碰仓库里的真文件
if [ "$(cli_fingerprint "$REAL_CLI")" = "$real_fp" ]; then
  echo "Z<<intact>>"
else
  echo "Z<<MUTATED>>"
fi
"""


def _posix(path) -> str:
    """Git Bash / MSYS 认 ``/c/...``，CI 的 Linux 原样返回。"""
    s = str(path)
    if os.name == "nt":
        s = s.replace("\\", "/")
        if len(s) > 1 and s[1] == ":":
            s = "/" + s[0].lower() + s[2:]
    return s


def _run(args, **kw):
    kw.setdefault("capture_output", True)
    kw.setdefault("encoding", "utf-8")
    kw.setdefault("errors", "replace")
    kw.setdefault("timeout", 300)
    return subprocess.run(args, check=False, **kw)


def _bash_usable() -> bool:
    if not shutil.which("bash"):
        return False
    try:
        probe = _run(["bash", "-c", "command -v tr cp cmp cksum"])
    except OSError:
        return False
    return probe.returncode == 0


pytestmark = pytest.mark.skipif(
    not _bash_usable(), reason="需要能跑 bash + coreutils 的环境（CI 上是 ubuntu）")


@pytest.fixture(scope="module")
def cli_probe(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("cli-alembic-width")
    (tmp / "repo" / ".git").mkdir(parents=True, exist_ok=True)
    (tmp / "bin").mkdir(parents=True, exist_ok=True)
    fake = tmp / "bin" / "docker"
    fake.write_bytes(FAKE_DOCKER.encode("utf-8"))
    fake.chmod(0o755)
    driver = tmp / "driver.sh"
    driver.write_bytes(DRIVER.encode("utf-8"))
    env = dict(os.environ)
    env["FAKE_LOG"] = str(tmp / "psql.log")
    proc = _run(["bash", _posix(driver), _posix(CLI), _posix(tmp)], env=env)
    assert proc.returncode == 0, proc.stderr
    out = {}
    for line in proc.stdout.splitlines():
        m = re.match(r"^([A-Z]\d?)<<(.*)>>$", line)
        if m:
            out[m.group(1)] = m.group(2)
    assert "A" in out, proc.stdout
    return out


def test_narrow_version_column_is_widened(cli_probe):
    assert "ALTER" in cli_probe["A2"], cli_probe["A2"]
    assert "widened" in cli_probe["A"], cli_probe["A"]


def test_wide_version_column_is_left_alone(cli_probe):
    assert cli_probe["B2"] == "", cli_probe["B2"]
    assert cli_probe["B"].strip() == ""


def test_missing_version_table_is_created_wide(cli_probe):
    assert "CREATE" in cli_probe["C2"], cli_probe["C2"]
    assert "created alembic_version" in cli_probe["C"], cli_probe["C"]


def test_migrate_still_refuses_without_a_version_table(cli_probe):
    d = cli_probe["D"]
    assert "db-baseline" in d, d
    # 建表动作绝不能抢在那道闸前面 —— 否则 upgrade head 会从 base 重放全部迁移
    assert "CREATE" not in cli_probe["D2"], cli_probe["D2"]
    assert "COMPOSE" not in cli_probe["D2"], cli_probe["D2"]


def test_migrate_widens_before_upgrading(cli_probe):
    e = cli_probe["E2"]
    assert "ALTER" in e, e
    assert "alembic upgrade head" in e, e
    assert e.index("ALTER") < e.index("alembic upgrade head"), e


def test_baseline_creates_the_version_table_wide(cli_probe):
    f = cli_probe["F2"]
    assert "CREATE" in f, f
    assert "alembic stamp 0047_identity_provider" in f, f


def test_the_probe_left_the_real_cli_alone(cli_probe):
    assert cli_probe["Z"] == "intact"