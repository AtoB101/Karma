# -*- coding: utf-8 -*-
"""生产必填闸门清单的一致性门禁（清单 <-> settings 强制项 <-> 模板/脚本）。

背景：2026-10-08 新增 ``VERIFIER_REQUIRE_NODE_SIGNATURE`` 时漏改了门禁脚本那一处，
CI 的 "Full-chain audit gate" 和线上部署（alembic 导入 settings）同时挂掉。这条
门禁用**行为**而不是手写名单来判定「生产闸门」：

1. 动态枚举：``Settings`` 在 ``APP_ENV=production`` 下拒绝、在 ``test`` 下不拒绝的
   字段 —— 这就是生产闸门的权威定义；
2. 其中「模型默认值本身不安全」（不写进 .env 就起不来）的，必须出现在
   ``config/production_gates.py`` 里；漏一个就红（本次事故的直接守护）；
3. 反方向：清单里的每个键必须是真实字段、且确实被 production 拒绝（拼错 / 闸门
   已删但清单没删，都红）；
4. ``PRODUCTION_GATE_TEMPLATES`` 里每份模板/文档逐键在场，且布尔/枚举开关的取值
   必须合法（防止模板教人把生产闸门关掉，或者写个 settings 不支持的值）。
"""

from __future__ import annotations

import functools
import io
import pathlib
import re

import pytest

from config.production_gates import (
    PRODUCTION_GATE_ALLOWED_VALUES,
    PRODUCTION_GATE_FLAGS,
    PRODUCTION_GATE_PLACEHOLDERS,
    PRODUCTION_GATE_SCRIPTS,
    PRODUCTION_GATE_TEMPLATES,
    audit_env,
    parse_env,
)
from config.settings import Settings

ROOT = pathlib.Path(__file__).resolve().parents[2]
MANIFEST: dict[str, str] = {**PRODUCTION_GATE_FLAGS, **PRODUCTION_GATE_PLACEHOLDERS}


def _coerce(value: str):
    if value == "true":
        return True
    if value == "false":
        return False
    return value


def _base_kwargs() -> dict:
    """清单本身就是一套能起得来的生产配置（这正是「必填」的含义）。"""
    kwargs = {name.lower(): _coerce(value) for name, value in MANIFEST.items()}
    kwargs["app_env"] = "production"
    return kwargs


def _error(kwargs: dict) -> str | None:
    try:
        # _env_file=None：不受仓库/本机 .env 干扰，只有显式给的 kwargs 生效。
        Settings(_env_file=None, **kwargs)
    except ValueError as exc:
        return str(exc)
    return None


def _probes(value):
    if isinstance(value, bool):
        return [not value]
    if isinstance(value, str):
        return ["", "mock", "local"]
    if isinstance(value, (int, float)):
        return [0, -1]
    return []


@functools.lru_cache(maxsize=1)
def _production_gates() -> tuple[frozenset[str], frozenset[str]]:
    """(全部生产闸门字段, 其中「默认值不安全 = 必须写进 .env」的字段)。"""
    base = _base_kwargs()
    gates: set[str] = set()
    explicit: set[str] = set()
    for name, field in Settings.model_fields.items():
        for probe in _probes(base.get(name, field.default)):
            kwargs = dict(base)
            kwargs[name] = probe
            message = _error(kwargs)
            if not message:
                continue
            # 同样的值在非生产环境下不报错 -> 这条限制只在 production 生效。
            if _error({**kwargs, "app_env": "test"}) is not None:
                continue
            gates.add(name)
            without = {k: v for k, v in base.items() if k != name}
            if _error(without) is not None:
                explicit.add(name)
            break
    assert gates, "没有枚举到任何生产闸门：settings.py 的 production 分支是不是被改没了？"
    return frozenset(gates), frozenset(explicit)


def test_manifest_itself_is_a_bootable_production_config():
    assert _error(_base_kwargs()) is None


def test_every_explicit_production_gate_is_in_the_manifest():
    _, explicit = _production_gates()
    missing = sorted(name for name in explicit if name.upper() not in MANIFEST)
    assert not missing, (
        "config/settings.py 在 APP_ENV=production 下会拒绝这些字段，但它们没写进 "
        "config/production_gates.py：%s\n"
        "→ 开关/枚举加进 PRODUCTION_GATE_FLAGS，密钥/白名单加进 "
        "PRODUCTION_GATE_PLACEHOLDERS，再给 PRODUCTION_GATE_TEMPLATES 里每个文件补上这个键。"
        % ", ".join(missing)
    )


def test_manifest_keys_are_real_and_actually_gated():
    gates, _ = _production_gates()
    unknown = sorted(key for key in MANIFEST if key.lower() not in Settings.model_fields)
    assert not unknown, "清单里有 settings 不认识的键（拼错了？）：%s" % ", ".join(unknown)
    stale = sorted(key for key in MANIFEST if key.lower() not in gates)
    assert not stale, (
        "清单里有字段已经不再被 production 拒绝了（闸门删了/改名了？）：%s" % ", ".join(stale)
    )


@pytest.mark.parametrize("rel_path", PRODUCTION_GATE_TEMPLATES)
def test_production_templates_list_every_gate(rel_path):
    path = ROOT / rel_path
    assert path.is_file(), "模板不见了：%s" % rel_path
    text = path.read_text(encoding="utf-8")
    # 只认「生效行」（行首可选空白 + KEY=），注释掉的键不算数：照抄注释进 .env 起不来。
    present = {m.group(1): m.group(2) for m in re.finditer(r"^[ \t]*([A-Z][A-Z0-9_]*)[ \t]*=(.*)$", text, re.M)}
    missing = sorted(key for key in MANIFEST if key not in present)
    assert not missing, "%s 少了生产必填键：%s（照抄这份模板会起不来）" % (rel_path, ", ".join(missing))

    bad: list[str] = []
    for key, expected in MANIFEST.items():
        actual = re.split(r"[ \t#]", present[key], 1)[0].strip()
        allowed = PRODUCTION_GATE_ALLOWED_VALUES.get(key)
        if allowed is not None:
            if actual not in allowed:
                bad.append("%s=%s（只能是 %s）" % (key, actual, " | ".join(allowed)))
        elif expected in ("true", "false") and actual != expected:
            bad.append("%s=%s（生产必须 %s）" % (key, actual, expected))
    assert not bad, "%s 里的闸门取值不对：%s" % (rel_path, "; ".join(bad))


@pytest.mark.parametrize("rel_path", PRODUCTION_GATE_SCRIPTS)
def test_gate_scripts_use_the_manifest(rel_path):
    text = (ROOT / rel_path).read_text(encoding="utf-8")
    assert "from config.production_gates import PRODUCTION_GATE_DEFAULTS" in text, (
        "%s 必须直接用 config/production_gates.py 的清单，不要手抄一份 dict" % rel_path
    )
    assert "defaults = dict(PRODUCTION_GATE_DEFAULTS)" in text, (
        "%s 应该 defaults = dict(PRODUCTION_GATE_DEFAULTS)" % rel_path
    )
    # 脚本里自己补的键（不是闸门的那种）也不能写错。
    for literal in sorted(set(re.findall(r'"([A-Z][A-Z0-9_]{3,})"', text))):
        assert literal.lower() in Settings.model_fields, (
            "%s 里出现了 settings 不认识的键 %s" % (rel_path, literal)
        )

# ---------------------------------------------------------------------------
# 运维侧自查（karma env-gates 用的就是这几个函数）
# ---------------------------------------------------------------------------


def test_parse_env_reads_the_shapes_our_env_files_use():
    text = (
        "# comment\n"
        "export A=\"x y\"\n"
        "B='z z'\n"
        "C=\n"
        "D=value   # inline comment\n"
        "E=0xabc#notacomment\n"
        "\n"
        "not a key value pair\n"
    )
    assert parse_env(text) == {
        "A": "x y",
        "B": "z z",
        "C": "",
        "D": "value",
        "E": "0xabc#notacomment",
    }


def test_audit_env_accepts_the_manifest_and_flags_every_kind_of_problem():
    good = "".join("%s=%s\n" % item for item in MANIFEST.items())
    assert audit_env(good) == []

    text = good.replace("VERIFIER_REQUIRE_NODE_SIGNATURE=true", "VERIFIER_REQUIRE_NODE_SIGNATURE=false")
    text = text.replace("MINIO_SECRET_KEY=%s\n" % MANIFEST["MINIO_SECRET_KEY"], "")
    text += "CHAIN_ALLOW_HOT_WALLET_PAYER=maybe\n"
    tags = {item[0]: item[1] for item in audit_env(text)}
    assert tags["DIFF"] in ("VERIFIER_REQUIRE_NODE_SIGNATURE", "CHAIN_ALLOW_HOT_WALLET_PAYER")
    assert "MINIO_SECRET_KEY" in set(item[1] for item in audit_env(text))


def test_audit_env_treats_allowed_enum_values_as_ok():
    text = "".join("%s=%s\n" % item for item in MANIFEST.items())
    text = text.replace("X402_PAYMENT_BACKEND=sepolia", "X402_PAYMENT_BACKEND=env")
    text = text.replace("KARMA_SIGNING_BACKEND=client_only", "KARMA_SIGNING_BACKEND=external")
    assert audit_env(text) == []


def test_audit_env_never_echoes_values():
    text = "".join("%s=%s\n" % item for item in MANIFEST.items())
    text = text.replace("VERIFIER_REQUIRE_NODE_SIGNATURE=true", "VERIFIER_REQUIRE_NODE_SIGNATURE=super-secret-value")
    report = repr(audit_env(text))
    assert "super-secret-value" not in report


def test_module_main_reports_tsv_and_exit_code(monkeypatch, capsys):
    import config.production_gates as manifest

    # 整份好清单只改一个闸门：应当只有一条 DIFF，并且退出码 1。
    text = "".join("%s=%s\n" % item for item in MANIFEST.items())
    text = text.replace("VERIFIER_REQUIRE_NODE_SIGNATURE=true", "VERIFIER_REQUIRE_NODE_SIGNATURE=false")
    monkeypatch.setattr("sys.stdin", io.StringIO(text))
    assert manifest.main([]) == 1
    printed = capsys.readouterr().out.splitlines()
    assert printed == [
        "DIFF\tVERIFIER_REQUIRE_NODE_SIGNATURE\ttrue",
        "SUMMARY\tflags=%d placeholders=%d problems=1" % (len(PRODUCTION_GATE_FLAGS), len(PRODUCTION_GATE_PLACEHOLDERS)),
    ]

    monkeypatch.setattr("sys.stdin", io.StringIO("".join("%s=%s\n" % i for i in MANIFEST.items())))
    assert manifest.main([]) == 0


def test_ops_cli_reuses_the_manifest():
    # 运维侧必须以同一份清单为准，不能自己抄一份（否则清单变了两边会脱节）。
    text = (ROOT / "deploy/karma").read_text(encoding="utf-8")
    assert "python -m config.production_gates" in text
    assert re.search(r"^\s*cmd_env_gates\(\)", text, re.M)
    assert re.search(r"^\s*env-gates\)\s+cmd_env_gates", text, re.M)
    assert "env-gates" in text.split("${B}Observe${N}")[1].split("${B}Operate${N}")[0]

