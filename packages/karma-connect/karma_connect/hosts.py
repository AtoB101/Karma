"""Detect agent hosts on this machine and write Karma's MCP server into them.

Every host gets the same treatment: read its config, upsert one named MCP server
entry, leave everything else alone. Writes are idempotent, so running the
command twice changes nothing the second time.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_NAME = "karma"
#: 默认指向通用薄接入层 ``packages/karma-mcp-server``。**不要**改回老包 ``karma-mcp``：
#: 那个包把 ``KARMA_PRIVATE_KEY`` 注进 MCP 进程（安全审计判定作废），而
#: ``karma-mcp-server`` 启动时发现私钥类键就直接拒绝启动（红线 R1）。
DEFAULT_COMMAND = "karma-mcp-server"

#: ``karma-mcp-server`` 真正会读的键（契约见 packages/karma-mcp-server/README.md）。
#: 只用于提示「这个环境变量它根本不认」，不参与任何校验。
KNOWN_ENV_KEYS = (
    "KARMA_RUNTIME_URL",
    "KARMA_RUNTIME_KEY",
    "KARMA_API_KEY",
    "KARMA_AGENT_ID",
    "KARMA_AGENT_PRIVATE_KEY",
    "KARMA_AGENT_ENV_PATH",
    "KARMA_MCP_STATE_DIR",
    "KARMA_MCP_ENABLE_TIER2",
    "KARMA_MCP_ENABLE_TIER3",
    "KARMA_MCP_ENABLE_HTTP",
    "KARMA_MCP_HTTP_TOKEN",
    "KARMA_MCP_ISSUER_URL",
    "KARMA_MCP_RESOURCE_URL",
    "PYTHONPATH",
    "PYTHONIOENCODING",
)

#: 绝不能写进宿主配置的键：``karma-mcp-server`` 启动时会检查它们并**拒绝启动**，
#: 写进去等于给宿主配一个起不来的 server。所以安装时直接拒绝（fail-closed）。
#: 老 ``karma-mcp`` 那套链上私钥模型（KARMA_PRIVATE_KEY / KARMA_MNEMONIC）一并列入。
FORBIDDEN_ENV_KEYS = (
    "KARMA_PRIVATE_KEY",
    "KARMA_MNEMONIC",
    "MNEMONIC",
    "USER_PRIVATE_KEY",
    "DEPLOYER_PRIVATE_KEY",
)


def _home() -> Path:
    return Path(os.path.expanduser("~"))


def xdg_config_home() -> Path:
    value = os.environ.get("XDG_CONFIG_HOME")
    return Path(value) if value else _home() / ".config"


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or (_home() / ".codex"))


def parse_env(pairs):
    """["KEY=VALUE", ...] -> dict, insertion order kept."""
    out = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise ValueError("--env expects KEY=VALUE, got %r" % (pair,))
        key, _, value = pair.partition("=")
        key = key.strip()
        if not key:
            raise ValueError("--env expects KEY=VALUE, got %r" % (pair,))
        out[key] = value
    return out


# ---------------------------------------------------------------- TOML helpers

def _toml_string(value: str) -> str:
    return json.dumps(value)


def _toml_array(values) -> str:
    return "[" + ", ".join(_toml_string(v) for v in values) + "]"


def upsert_toml_table(text: str, table: str, body) -> str:
    """Insert or replace [table], preserving every other line."""
    header = "[%s]" % table
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip() == header), None)
    if start is None:
        out = text.rstrip("\n")
        prefix = out + "\n\n" if out else ""
        return prefix + "\n".join([header, *body]) + "\n"
    end = len(lines)
    for j in range(start + 1, len(lines)):
        stripped = lines[j].strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if stripped.startswith(header[:-1] + "."):
                continue
            end = j
            break
    merged = [*lines[:start], header, *body]
    tail = lines[end:]
    if tail:
        merged.append("")
        merged.extend(tail)
    return "\n".join(merged).rstrip("\n") + "\n"


# ---------------------------------------------------------------- JSON helpers

def read_json_object(path: Path) -> dict:
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("%s does not hold a JSON object" % path)
    return data


def write_json_object(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def json_upsert(data: dict, dotted: str, name: str, entry: dict) -> None:
    node = data
    parts = dotted.split(".")
    for part in parts[:-1]:
        child = node.get(part)
        if not isinstance(child, dict):
            child = {}
            node[part] = child
        node = child
    bucket = node.get(parts[-1])
    if not isinstance(bucket, dict):
        bucket = {}
        node[parts[-1]] = bucket
    bucket[name] = entry


# ------------------------------------------------------------------- host spec

def build_entry(command: str, args, env: dict, style: str) -> dict:
    if style == "muse":
        return {"type": "stdio", "command": command, "args": list(args),
                "env": dict(env), "mode": "optional"}
    if style == "vscode":
        return {"type": "stdio", "command": command, "args": list(args), "env": dict(env)}
    if style == "openclaw":
        return {"transport": "stdio", "command": command, "args": list(args), "env": dict(env)}
    return {"command": command, "args": list(args), "env": dict(env)}


@dataclass
class Host:
    key: str
    label: str
    style: str
    config_path: Path
    json_bucket: str = "mcpServers"
    toml_table: str = "mcp_servers"
    format: str = "json"
    detect_paths: tuple = field(default_factory=tuple)

    def detected(self) -> bool:
        if not self.detect_paths:
            return True
        return any(path.exists() for path in self.detect_paths)

    def render(self, name: str, command: str, args, env: dict):
        """-> (path, new_text). Pure: no disk writes."""
        if self.format == "toml":
            current = (self.config_path.read_text(encoding="utf-8")
                       if self.config_path.exists() else "")
            body = ["command = %s" % _toml_string(command),
                    "args = %s" % _toml_array(args)]
            if env:
                body.append("[%s.%s.env]" % (self.toml_table, name))
                body.extend("%s = %s" % (k, _toml_string(v)) for k, v in env.items())
            text = upsert_toml_table(current, "%s.%s" % (self.toml_table, name), body)
            return self.config_path, text
        data = read_json_object(self.config_path)
        json_upsert(data, self.json_bucket, name, build_entry(command, args, env, self.style))
        if self.style == "muse" and "schema_version" not in data:
            data = {"schema_version": 1, **data}
        return self.config_path, json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def default_hosts(workspace=None):
    home = _home()
    cfg = xdg_config_home()
    openclaw_state = Path(os.environ.get("OPENCLAW_STATE_DIR") or (home / ".openclaw"))
    hosts = [
        Host("codex", "Codex CLI", "plain", codex_home() / "config.toml",
             toml_table="mcp_servers", format="toml", detect_paths=(codex_home(),)),
        Host("claude", "Claude Code", "plain", home / ".claude.json",
             detect_paths=(home / ".claude.json",)),
        Host("cursor", "Cursor", "plain", home / ".cursor" / "mcp.json",
             detect_paths=(home / ".cursor",)),
        Host("muse", "Muse Code (Meta)", "muse", cfg / "muse" / "settings.json",
             detect_paths=(cfg / "muse",)),
        Host("openclaw", "OpenClaw", "openclaw", openclaw_state / "openclaw.json",
             json_bucket="mcp.servers", detect_paths=(openclaw_state,)),
    ]
    if workspace is not None:
        hosts.append(Host("vscode", "VS Code (this workspace)", "vscode",
                          Path(workspace) / ".vscode" / "mcp.json",
                          json_bucket="servers", detect_paths=(Path(workspace),)))
    return hosts


def install(host: Host, name: str, command: str, args, env: dict, dry_run: bool = False):
    """-> dict describing what happened."""
    path, new_text = host.render(name, command, args, env)
    if dry_run:
        return {"host": host.key, "path": str(path), "changed": True, "dry_run": True}
    before = path.read_text(encoding="utf-8") if path.exists() else None
    if before == new_text:
        return {"host": host.key, "path": str(path), "changed": False}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new_text, encoding="utf-8")
    return {"host": host.key, "path": str(path), "changed": True}
