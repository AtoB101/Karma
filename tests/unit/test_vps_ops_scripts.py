# -*- coding: utf-8 -*-
"""VPS 运维脚本：能解析 + 「不许静默」的几条 guard 还在。

2026-10-08 的教训：`karma deploy` 因为 bash 自我改写后的旧偏移，把刷新安装副本那段
代码静默跳过，CI 全绿而机器上的 CLI 落后两周。顺着这条线翻出另外几个同类问题：

* ``deploy/vps/deploy.sh`` 的 ``git reset --hard`` 会一声不吭抹掉本地改动，而且部署完
  没有任何「线上跑的就是这次提交」的自证（``ci-deploy.sh`` 早就有）；
* ``deploy/vps/bootstrap.sh`` 头部声称「密钥登录、禁密码」，实际只打印一句提示、从没
  核对过；``dpkg-reconfigure ... || true`` 把失败直接吞掉；``ufw --force reset`` 之后
  硬编码只放行 22 端口 —— sshd 换过端口就等于把自己锁在门外。

这里钉两件事：每个脚本都能解析（真的跑 ``bash -n``），以及上面这些 guard 还在。
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
VPS = ROOT / "deploy" / "vps"
SCRIPTS = sorted(VPS.glob("*.sh")) + [ROOT / "deploy" / "karma"]


def _run(args):
    return subprocess.run(args, capture_output=True, check=False,
                          encoding="utf-8", errors="replace", timeout=60)


def _bash():
    return shutil.which("bash")


@pytest.mark.skipif(_bash() is None, reason="需要 bash 才能做语法检查")
@pytest.mark.parametrize("path", SCRIPTS, ids=lambda p: p.name)
def test_shell_scripts_parse(path):
    proc = _run([_bash(), "-n", str(path)])
    assert proc.returncode == 0, proc.stderr


def test_deploy_sh_does_not_silently_discard_local_edits():
    text = (VPS / "deploy.sh").read_text(encoding="utf-8")
    reset = text.index("git reset --hard origin/main")
    assert "git status --porcelain" in text[:reset], "reset 之前先看清楚有什么会被丢"
    assert "已停下" in text[:reset], "默认必须停下来，而不是直接抹掉"
    assert "--force" in text[:reset], "要丢弃得明确 --force"


def test_deploy_sh_proves_the_deployed_revision():
    text = (VPS / "deploy.sh").read_text(encoding="utf-8")
    assert "git rev-parse HEAD" in text
    assert "deployed revision verified" in text


def test_deploy_sh_installs_the_operator_cli():
    text = (VPS / "deploy.sh").read_text(encoding="utf-8")
    assert 'install -m 0755' in text and "/usr/local/bin/karma" in text


def test_bootstrap_never_swallows_the_unattended_upgrades_step():
    text = (VPS / "bootstrap.sh").read_text(encoding="utf-8")
    assert "unattended-upgrades || true" not in text, "|| true 会把失败吞掉"
    assert "systemctl is-active --quiet unattended-upgrades" in text, "要验证它真的在跑"


def test_bootstrap_allows_the_real_ssh_port_before_resetting_ufw():
    text = (VPS / "bootstrap.sh").read_text(encoding="utf-8")
    # 注释里也提到了 "ufw --force reset"，所以只认行首的命令本体。
    reset = text.index("\nufw --force reset")
    assert text.index("\nSSH_PORT=") < reset, "先读 sshd 的实际端口，再 reset 规则"
    assert 'ufw allow "${SSH_PORT}/tcp"' in text
    assert "ufw allow 22/tcp" not in text, "硬编码 22 会把换过端口的机器锁死"


def test_bootstrap_verifies_the_baseline_it_claims():
    text = (VPS / "bootstrap.sh").read_text(encoding="utf-8")
    for key in ("passwordauthentication", "permitrootlogin", "pubkeyauthentication"):
        assert key in text, "头部声称的安全基线要逐条核对：%s" % key
    assert "BASELINE_OK" in text
    assert "exit 2" in text, "基线不达标就不能报「完成」"
