# -*- coding: utf-8 -*-
"""deploy/karma 自我改写之后必须 re-exec，不能带着旧偏移继续跑。

背景（2026-10-08 的静默部署事故）：`karma deploy` 的第一步就是 ``git merge``，而被
merge 掉的文件正是**它自己**。bash 是一边解析一边执行的，它记着自己那个字节偏移；
文件被换掉之后它从旧偏移继续读，后面的代码就成了旧行和新行的混合体 —— 在机器上实测
一个 5 行的自我改写脚本，输出是 ``LINE1-old / LINE2-old / LINE4-new / LINE5-new``。
后果：8ce35d8 给 sync_cli 加的「安装副本也要跟着刷新」在一次完整的 CI 部署里**一行
都没执行**，而 CI 是绿的；机器上的 /usr/local/bin/karma 因此停在两周前的构建上。

这里直接用仓库里真实的 deploy/karma 跑回归：
1. ``reexec_if_cli_changed`` 在文件被改写后 exec 新版本（而不是继续读旧偏移）；
2. ``sync_cli`` 对安装副本的漂移**绝不静默** —— 要么刷新并说出来，要么明确警告。
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
CI_DEPLOY = ROOT / "deploy" / "vps" / "ci-deploy.sh"

DRIVER = r"""
set -u
REAL_CLI="$1"; T="$2"
KARMA_CLI_LIB_ONLY=1
export KARMA_CLI_LIB_ONLY
[ -d "$T" ] || { echo "SETUP-FAILED $T" >&2; exit 9; }
# 一定要 source **副本**：sync_cli 的第一段会把 $src 装回 $self，而 $self 就是我们
# source 进来的那个文件。直接 source 仓库里的真文件，就等于让实验内容覆盖仓库。
CLI_FILE="$T/sourced-cli"
cp "$REAL_CLI" "$CLI_FILE" || exit 9
. "$CLI_FILE"
real_fp=$(cli_fingerprint "$REAL_CLI")
# 输出可能带换行（多行警告），压成一行好让测试逐行解析。
flat() { printf '%s' "$1" | tr '\n' '|'; }

REPO_DIR="$T/repo"
CLI_INSTALLED="$T/installed/karma"
LIVE="$REPO_DIR/deploy/karma"
# 这里不用 `mkdir -p`：MSYS 在沙箱里对深层绝对路径的 mkdir -p 会误报 EACCES。
# 沙箱目录由测试侧建好，这里只确认在。
[ -d "$REPO_DIR/deploy" ] && [ -d "$(dirname "$CLI_INSTALLED")" ] \
  || { echo "SETUP-FAILED $T" >&2; exit 9; }
printf 'probe\n' > "$LIVE"
[ -n "$(cli_fingerprint "$LIVE")" ] || { echo "SETUP-FAILED: $LIVE" >&2; exit 9; }

# A) 文件被 pull 改写 -> 必须 exec 新版本，旧偏移后面那行不能被执行
A=$( printf 'old body\n' > "$LIVE"
     before=$(cli_fingerprint "$LIVE")
     printf '#!/usr/bin/env bash\necho NEW-COPY-RAN "$@"\n' > "$LIVE"
     KARMA_ORIG_ARGS=(deploy)
     reexec_if_cli_changed "$before"
     echo "##A-CONTINUED##" )
echo "A<<$(flat "$A")>>"

# B) 文件没变 -> 放行，继续跑
printf 'old body\n' > "$LIVE"
before=$(cli_fingerprint "$LIVE")
if reexec_if_cli_changed "$before"; then echo "B<<returned-0>>"; else echo "B<<returned-1>>"; fi

# C) 一直被改写 -> 拒绝继续（可见的失败，而不是乱跑）
C=$( printf 'old body\n' > "$LIVE"
     before=$(cli_fingerprint "$LIVE")
     printf 'new body\n' > "$LIVE"
     KARMA_REEXEC_DEPTH=3
     if reexec_if_cli_changed "$before"; then echo "returned-0"; else echo "refused-1"; fi )
echo "C<<$(flat "$C")>>"

# D) 安装副本漂移 -> 必须说话（刷新 / 或明确警告不可写），绝不静默
printf 'repo-body\n' > "$LIVE"
printf 'installed-stale-body\n' > "$CLI_INSTALLED"
D=$(sync_cli 2>&1 || true)
echo "D<<$(flat "$D")>>"
echo "D2<<$(cmp -s "$LIVE" "$CLI_INSTALLED" && echo same || echo differs)>>"

# E) 两边一致 -> 安静（部署日志不该刷屏）
cp "$LIVE" "$CLI_INSTALLED"
E=$(sync_cli 2>&1 || true)
echo "E<<$(flat "$E")>>"

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
        probe = _run(["bash", "-c", "command -v cmp install cksum id"])
    except OSError:
        return False
    return probe.returncode == 0


pytestmark = pytest.mark.skipif(
    not _bash_usable(), reason="需要能跑 bash + coreutils 的环境（CI 上是 ubuntu）")


@pytest.fixture(scope="module")
def cli_probe(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("cli-self-update")
    (tmp / "repo" / "deploy").mkdir(parents=True, exist_ok=True)
    (tmp / "installed").mkdir(parents=True, exist_ok=True)
    driver = tmp / "driver.sh"
    driver.write_bytes(DRIVER.encode("utf-8"))
    proc = _run(["bash", _posix(driver), _posix(CLI), _posix(tmp)])
    assert proc.returncode == 0, proc.stderr
    out = {}
    for line in proc.stdout.splitlines():
        m = re.match(r"^([A-Z]\d?)<<(.*)>>$", line)
        if m:
            out[m.group(1)] = m.group(2)
    assert "A" in out, proc.stdout
    return out


def test_reexecs_the_new_copy_instead_of_a_stale_parse_offset(cli_probe):
    # 没有修复的话，这里会看到旧偏移后面的那句 ##A-CONTINUED##
    assert "NEW-COPY-RAN deploy" in cli_probe["A"]
    assert "##A-CONTINUED##" not in cli_probe["A"]


def test_unchanged_cli_is_left_alone(cli_probe):
    assert cli_probe["B"] == "returned-0"


def test_refuses_after_repeated_rewrites(cli_probe):
    # 连改 3 次说明有东西在反复动这个文件：宁可红一次，也不要继续解析一个移动的文件
    c = cli_probe["C"]
    assert c.endswith("refused-1"), c
    assert "refusing to keep parsing" in c


def test_installed_copy_drift_is_never_silent(cli_probe):
    d = cli_probe["D"]
    assert d.strip(), "sync_cli 对安装副本漂移完全没出声"
    assert ("refreshed" in d) or ("out of date" in d), d
    if "refreshed" in d:
        assert cli_probe["D2"] == "same"


def test_matching_installed_copy_stays_quiet(cli_probe):
    assert cli_probe["E"].strip() == ""


def test_the_probe_itself_left_the_real_cli_alone(cli_probe):
    assert cli_probe["Z"] == "intact"


def test_deploy_and_update_reexec_right_after_the_fast_forward():
    text = CLI.read_text(encoding="utf-8")
    for fn in ("cmd_deploy", "cmd_update"):
        m = re.search(rf"^{fn}\(\) \{{\n(.*?)\n\}}", text, re.MULTILINE | re.DOTALL)
        assert m, f"找不到 {fn}"
        body = m.group(1)
        i_fp = body.index("cli_before=")
        i_merge = body.index("git merge --ff-only origin/main")
        i_reexec = body.index('reexec_if_cli_changed "$cli_before" || return 1')
        i_sync = body.index("sync_cli")
        # 指纹必须取在 merge 之前（否则比的是同一个文件），re-exec 必须紧跟在 merge 之后
        assert i_fp < i_merge < i_reexec < i_sync, fn


def test_ci_deploy_resyncs_the_installed_copy():
    text = CI_DEPLOY.read_text(encoding="utf-8")
    assert "INSTALLED_CLI=/usr/local/bin/karma" in text
    assert re.search(r'cmp -s "\$\{CLI_SRC\}" "\$\{INSTALLED_CLI\}"', text)
    assert 'install -m 0755 "${CLI_SRC}" "${INSTALLED_CLI}"' in text
