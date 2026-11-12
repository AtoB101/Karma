"""API 必须单 worker —— 把 ``--workers 4`` 写回去，这条就红。

``deploy/Dockerfile.api`` 里曾经写着 ``--workers 4``。刹车状态现在落库了
（``services/runtime_safety.py`` + migration 0060），多 worker 最坏也只是晚几秒；
但进程内状态不止刹车一处（``runtime_key_service._replay``、
``escrow_settlement._recover_failed_at``），而且这台 1.6 GB 的机器经不起 4 份解释器。
所以「单 worker」是显式钉死的部署约束，不是碰巧。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_compose_pins_a_single_worker():
    text = (ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8")
    assert "--workers 1" in text
    assert "--workers 4" not in text


def test_api_dockerfile_pins_a_single_worker():
    text = (ROOT / "deploy" / "Dockerfile.api").read_text(encoding="utf-8")
    assert '"--workers", "1"' in text
    assert '"--workers", "4"' not in text
