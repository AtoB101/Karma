"""karma-connect CLI: detect agent hosts, install the Karma MCP server, verify it."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

from karma_connect.hosts import (DEFAULT_COMMAND, DEFAULT_NAME, FORBIDDEN_ENV_KEYS,
                                 KNOWN_ENV_KEYS, default_hosts, install, parse_env)

DEFAULT_MODULE = "karma_mcp_server"
#: Without KARMA_RUNTIME_URL the MCP server falls back to http://localhost:8000 and every
#: call dies with "All connection attempts failed" -- no user_code, no matching code.
#: Bake the public node in so an out-of-the-box install actually talks to Karma.
DEFAULT_ENV = {"KARMA_RUNTIME_URL": "https://karma-network.ai"}
#: GUI 之外的兜底：直接 ``python -m karma_mcp_server``（同一个包，不必装 console script）。
#: 老 ``karma_mcp``（私钥进进程）刻意不列 —— 装了也不能用。
FALLBACK_MODULES = ("karma_mcp_server",)


def _module_command(module: str, extra, env: dict):
    """Run the MCP server as `<this python> -m <module>` and make it importable."""
    top = module.split(".")[0]
    spec = importlib.util.find_spec(top)
    if spec is None or not spec.origin:
        raise ValueError("module %r is not importable by %s" % (module, sys.executable))
    root = str(Path(spec.origin).resolve().parents[1])
    existing = [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p]
    if root not in existing:
        env["PYTHONPATH"] = os.pathsep.join([root, *existing])
    return sys.executable, ["-m", module, *extra]


def _resolve(args):
    env = parse_env(getattr(args, "env", None))
    applied_defaults = []
    for key, value in DEFAULT_ENV.items():
        if not env.get(key):
            env[key] = value
            applied_defaults.append("%s=%s" % (key, value))
    name = args.name or DEFAULT_NAME
    command = args.command
    extra = list(args.arg or [])

    if args.module:
        command, extra = _module_command(args.module, extra, env)
    elif command is None:
        if shutil.which(DEFAULT_COMMAND):
            command = DEFAULT_COMMAND
        else:
            for module in FALLBACK_MODULES:
                if importlib.util.find_spec(module.split(".")[0]) is not None:
                    command, extra = _module_command(module, extra, env)
                    break
            else:
                command = DEFAULT_COMMAND
    return name, command, extra, env, applied_defaults


def result_path(host):
    return str(host.config_path)


def hint_for(exc, host):
    if isinstance(exc, PermissionError):
        return "permission denied - this shell cannot write %s" % host.config_path
    return "%s: %s" % (type(exc).__name__, exc)


def cmd_detect(args) -> int:
    rows = []
    for host in default_hosts(workspace=args.workspace):
        rows.append({"host": host.key, "label": host.label,
                     "detected": host.detected(), "config": str(host.config_path)})
    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return 0
    print("agent hosts found on this machine:")
    for row in rows:
        print("  [%s] %-9s %-20s %s" % ("yes" if row["detected"] else "no ", row["host"],
                                        row["label"], row["config"]))
    return 0


def cmd_install(args) -> int:
    name, command, extra, env, defaults = _resolve(args)
    hosts = default_hosts(workspace=args.workspace)
    if args.host and args.host != "all":
        wanted = {h.strip() for h in args.host.split(",") if h.strip()}
        unknown = wanted - {host.key for host in hosts}
        if unknown:
            print("unknown host(s): %s" % ", ".join(sorted(unknown)), file=sys.stderr)
            return 2
        hosts = [host for host in hosts if host.key in wanted]
    else:
        hosts = [host for host in hosts if host.detected()]

    forbidden_env = sorted(key for key in env if key in FORBIDDEN_ENV_KEYS)
    if forbidden_env:
        print("refusing to install: %s must never be written into an MCP host config."
              % ", ".join(forbidden_env), file=sys.stderr)
        print("  karma-mcp-server refuses to start when private key material is in its "
              "environment, so this entry would be dead on arrival.", file=sys.stderr)
        print("  Karma wallet signatures always come from the owner's own wallet; the "
              "agent side only ever holds a Runtime Key.", file=sys.stderr)
        return 2
    unknown_env = [key for key in env if key not in KNOWN_ENV_KEYS]
    if unknown_env:
        print("warning: unrecognized env key(s): %s" % ", ".join(unknown_env), file=sys.stderr)
        print("  karma-mcp-server ignores these; pairing writes KARMA_RUNTIME_KEY on its own.",
              file=sys.stderr)
    if not hosts:
        print("no agent host detected on this machine.", file=sys.stderr)
        return 3
    if not os.path.isabs(command) and shutil.which(command) is None:
        print("warning: %r is not on PATH yet - the host will fail to start the server."
              % command, file=sys.stderr)
        print("  install it first: pip install ./packages/karma-mcp-server", file=sys.stderr)

    print("server: %s %s" % (command, " ".join(extra)))
    for key in defaults:
        print("  default env: %s" % key)
    changed = 0
    failed = []
    for host in hosts:
        try:
            result = install(host, name, command, extra, env, dry_run=args.dry_run)
        except Exception as exc:
            failed.append((host, exc))
            print("  %-9s %-12s %s" % (host.key, "FAILED", result_path(host)))
            print("  %-9s   %s" % ("", hint_for(exc, host)))
            continue
        if args.dry_run:
            state = "would write"
        else:
            state = "updated" if result["changed"] else "already set"
        print("  %-9s %-12s %s" % (host.key, state, result["path"]))
        changed += 1 if result["changed"] else 0

    print()
    if failed:
        print("%d host(s) could not be written (the rest are done)." % len(failed))
        print("Re-run the same command in a normal terminal (not the sandbox) to finish those.")
    if args.dry_run:
        print("dry run: %d file(s) would change. Re-run without --dry-run to apply." % changed)
        return 0
    print("done. %d file(s) changed." % changed)
    print("next: restart the agent host so it reloads MCP servers, then have the agent call")
    print("      karma_connect; check the agent_fingerprint against the Console card, approve")
    print("      it there - that approval IS the activation - then have it call")
    print("      karma_connect_claim.")
    print("      credentials land in ~/.karma/agent.env (0600) - nothing secret in chat.")
    return 0


def _local_runtime_key() -> str:
    """本机凭据文件里的 Runtime Key（配对批准后由 karma_connect_claim 落盘）。"""
    override = os.environ.get("KARMA_AGENT_ENV_PATH")
    path = Path(override) if override else Path.home() / ".karma" / "agent.env"
    try:
        text = path.expanduser().read_text(encoding="utf-8")
    except OSError:
        return ""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("KARMA_RUNTIME_KEY="):
            return line.partition("=")[2].strip()
    return ""


def cmd_doctor(args) -> int:
    name, command, extra, env, _defaults = _resolve(args)
    problems = []
    notes = []
    if not os.path.isabs(command) and shutil.which(command) is None:
        problems.append("%r is not on PATH - pip install ./packages/karma-mcp-server first"
                        % command)
    if not env.get("KARMA_RUNTIME_URL"):
        problems.append("no KARMA_RUNTIME_URL: pairing would hit http://localhost:8000")
    forbidden_env = sorted(key for key in env if key in FORBIDDEN_ENV_KEYS)
    if forbidden_env:
        problems.append("private key material in env (%s): karma-mcp-server refuses to start "
                        "with those" % ", ".join(forbidden_env))
    if not env.get("KARMA_RUNTIME_KEY") and not _local_runtime_key():
        notes.append("not paired yet - the agent can still call karma_connect, and the Runtime "
                     "Key lands in ~/.karma/agent.env once the owner approves")
    for host in default_hosts(workspace=args.workspace):
        if not host.detected():
            continue
        try:
            path, _ = host.render(name, command, extra, env)
        except Exception as exc:
            problems.append("%s: %s" % (host.key, exc))
            continue
        print("  ok   %-9s %s" % (host.key, path))
    if problems or notes:
        print()
        for problem in problems:
            print("  warn %s" % problem)
        for note in notes:
            print("  note %s" % note)
    if problems:
        return 1
    print()
    print("configs look good." if notes else "no problems found.")
    return 0


def _add_common(parser):
    parser.add_argument("--host", default="all",
                        help="all (default) or a comma list: codex,claude,cursor,muse,openclaw,vscode")
    parser.add_argument("--name", default=DEFAULT_NAME, help="MCP server name (default %s)" % DEFAULT_NAME)
    parser.add_argument("--command", default=None,
                        help="server command; default is %s if on PATH, else this python"
                             % DEFAULT_COMMAND)
    parser.add_argument("--module", default=None,
                        help="run the server as `python -m <module>` (default: %s)"
                             % DEFAULT_MODULE)
    parser.add_argument("--arg", action="append", default=[],
                        help="argument for the server command (repeatable)")
    parser.add_argument("--env", action="append", default=[],
                        help="KEY=VALUE passed to the server (repeatable)")
    parser.add_argument("--workspace", default=None, help="workspace path, enables the vscode host")


def cmd_sign_check(args) -> int:
    """逐请求签名的自检 —— 实现在 karma_connect.signcheck，这里只转发参数。"""
    from karma_connect import signcheck

    argv = ["--path", args.path]
    if args.runtime_url:
        argv += ["--runtime-url", args.runtime_url]
    if args.json:
        argv.append("--json")
    return signcheck.main(argv)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="karma-connect",
        description="Wire the Karma MCP server into every agent host on this machine.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    detect = sub.add_parser("detect", help="list agent hosts found on this machine")
    detect.add_argument("--json", action="store_true")
    detect.add_argument("--workspace", default=None)
    detect.set_defaults(func=cmd_detect)

    inst = sub.add_parser("install", help="write the Karma MCP server into each detected host")
    _add_common(inst)
    inst.add_argument("--dry-run", action="store_true")
    inst.set_defaults(func=cmd_install)

    doctor = sub.add_parser("doctor", help="check that the install can work")
    _add_common(doctor)
    doctor.set_defaults(func=cmd_doctor)

    sign = sub.add_parser(
        "sign-check",
        help="check the per-request Ed25519 signing path against a live node")
    sign.add_argument("--runtime-url", default=None)
    sign.add_argument("--path", default="/runtime/permissions")
    sign.add_argument("--json", action="store_true")
    sign.set_defaults(func=cmd_sign_check)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
