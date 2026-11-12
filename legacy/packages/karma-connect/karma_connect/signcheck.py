# -*- coding: utf-8 -*-
"""karma-connect sign-check —— 逐请求签名这条「最后一公里」的自检。

绑定生效之后，``/runtime/*`` 每个请求都要带三个头：
``X-Karma-Agent-Signature`` / ``X-Karma-Runtime-Timestamp`` / ``X-Karma-Runtime-Nonce``。
任何一个环节不对，服务端只会回一句 401，看不出是钥匙、私钥、消息格式还是时钟的问题。

这个命令把四步拆开打印：

    [1] 本机握着什么（runtime key / agent 私钥 / agent id）
    [2] 不带签名打一次 —— 用来判断这把钥匙「绑没绑公钥」
    [3] 带签名打一次，并把签名的那段原文原样打出来（能直接跟服务端对齐）
    [4] 结论：通 / 卡在哪一步 / 下一步做什么

它不写任何凭据、不改任何配置，只读本地凭据 + 发两个 GET。
"""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_RUNTIME_URL = "https://karma-network.ai"


def _ensure_importable() -> None:
    if importlib.util.find_spec("karma_openclaw") is not None:
        return
    here = Path(__file__).resolve()
    for candidate in (here.parents[3] / "karma-openclaw", here.parents[2] / "karma-openclaw"):
        if (candidate / "karma_openclaw" / "__init__.py").is_file():
            sys.path.insert(0, str(candidate))
            return


def local_credentials() -> dict:
    """本机这份凭据：来源、长度、公钥指纹。绝不回显私钥本身。"""
    _ensure_importable()
    from karma_openclaw.agent_binding import agent_id_from_env, agent_key_from_env, runtime_key_id
    from karma_openclaw.agent_env import agent_env_path
    from karma_openclaw.http_client import runtime_base_url, runtime_key

    out: dict = {"runtime_url": runtime_base_url(), "env_file": str(agent_env_path())}
    key = runtime_key()
    out["has_runtime_key"] = bool(key)
    out["runtime_key_id"] = runtime_key_id(key or "")
    out["runtime_key_length"] = len(key or "")
    private = agent_key_from_env()
    out["has_agent_private_key"] = private is not None
    if private is not None:
        pub = private.public_key().public_bytes_raw()
        pub_b64 = base64.b64encode(pub).decode()
        out["agent_public_key_b64"] = pub_b64
        # 指纹口径与操作台 / 服务端同源：canonical base64 文本的 sha256 前 16 位。
        # 主人拿这串去和 Console 待批准卡片上的那串逐字比对，两边必须是同一个值。
        out["agent_public_key_fingerprint"] = hashlib.sha256(pub_b64.encode()).hexdigest()[:16]
    out["agent_id"] = agent_id_from_env()
    return out


def build_probe(*, key_id: str, method: str, path: str, body: bytes = b"") -> tuple[str, dict[str, str]]:
    """按服务端的规范拼出被签的那段原文，并给出三个头。"""
    _ensure_importable()
    from karma_openclaw.agent_binding import build_agent_request_message

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    nonce = uuid.uuid4().hex
    message = build_agent_request_message(
        key_id=key_id,
        method=method,
        path=path,
        timestamp=timestamp,
        nonce=nonce,
        body_sha256=hashlib.sha256(body or b"").hexdigest(),
    )
    return message, {
        "X-Karma-Runtime-Timestamp": timestamp,
        "X-Karma-Runtime-Nonce": nonce,
    }


def verdict(unsigned: tuple[int, str], signed: tuple[int, str]) -> tuple[str, str]:
    """(状态码, detail) -> (结论, 下一步)。纯函数，方便钉测试。"""
    u_code, u_detail = unsigned
    s_code, s_detail = signed
    if u_code == 200:
        return (
            "这把钥匙还没绑 agent 公钥 —— 服务端现在不要求签名，谁拿到它都能花",
            "先在操作台铸一把「指名 agent」的钥匙：agent 调 /runtime/bind-key 出 8 位匹配码，"
            "主人在操作台输入确认之后，签名才生效。",
        )
    if s_code == 200:
        return ("通了：签名被服务端接受，逐请求这条路是活的", "")
    if s_code == 401 and "invalid or revoked runtime key" in s_detail:
        return (
            "服务端不认这把钥匙（不存在或已被吊销）",
            "回操作台核对这把 KRM_RT_… 是不是刚铸的那把、有没有被撤销；必要就重新铸一把。",
        )
    if s_code == 403 and "no bound agent public key" in s_detail:
        return ("这把钥匙没有绑公钥", "先让 agent 调 /runtime/bind-key，再让主人在操作台输匹配码确认。")
    if s_code == 403:
        return ("钥匙没激活（或额度/权限被拒）", "让主人在操作台输一次 8 位匹配码完成激活：%s" % s_detail)
    if s_code == 401 and "X-Karma-Agent-Signature header is required" in s_detail:
        return (
            "服务端要签名，但这次请求没带 —— 本机缺 agent 私钥",
            "把 KARMA_AGENT_PRIVATE_KEY（base64 的 32 字节种子，或 64 位 hex）与 KARMA_AGENT_ID "
            "配进 agent 的运行环境，或写进 " + _env_hint(),
        )
    if s_code == 401 and "verification failed" in s_detail:
        return (
            "签名送到了，但验不过 —— 私钥跟绑定的公钥不是一对，或签名原文没按规范拼",
            "核对两件事：(1) KARMA_AGENT_PRIVATE_KEY 是不是当初 POST /runtime/bind-key 那把；"
            "(2) 被签原文必须逐行是 Karma Runtime Request / key_id:/method:/path:/timestamp:/"
            "nonce:/body_sha256:（下面已把本机拼出来的原文打印出来，可直接比对）。",
        )
    if s_code == 401 and "outside the accepted window" in s_detail:
        return ("时间戳超出 ±300 秒窗口", "同步本机时钟；时间戳用 UTC 的 YYYY-MM-DDTHH:MM:SSZ。")
    if s_code == 401 and "Nonce header is required" in s_detail:
        return ("缺 X-Karma-Runtime-Nonce", "每个请求带一个 ≤128 字符的一次性随机串（本命令用 uuid4 hex）。")
    if s_code == 409:
        return ("nonce 重复被拒（防重放）", "换一个新的 nonce；同一个 nonce 不能被同一个 key+路径用第二次。")
    return ("没通，服务端说：%s (%s)" % (s_detail, s_code), "把上面两行原文和状态码一起发出来。")


def _env_hint() -> str:
    return "~/.karma/agent.env（KEY=VALUE 每行一条）"


def _render(info: dict) -> str:
    lines = [
        "runtime url     : %s" % info["runtime_url"],
        "credential file : %s" % info["env_file"],
        "runtime key     : %s" % ("KRM_RT_%s_… (%d chars)" % (info["runtime_key_id"], info["runtime_key_length"])
                                  if info["has_runtime_key"] else "MISSING"),
        "agent id        : %s" % (info["agent_id"] or "MISSING"),
        "agent pubkey fp : %s" % (info.get("agent_public_key_fingerprint") or "MISSING"),
    ]
    return "\n".join(lines)


async def _probe(*, url: str, key: str, headers: dict[str, str], path: str) -> tuple[int, str]:
    import httpx

    from karma_openclaw.http_client import api_headers

    h = api_headers()
    h["X-Karma-Runtime-Key"] = key
    h.update(headers)
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url + path, headers=h)
    try:
        payload = resp.json()
        detail = str(payload.get("detail") or "") if isinstance(payload, dict) else str(payload)[:300]
    except Exception:  # noqa: BLE001
        detail = (resp.text or "")[:300]
    return resp.status_code, detail


async def run(args) -> int:
    info = local_credentials()
    runtime_url = (getattr(args, "runtime_url", None) or info["runtime_url"]).rstrip("/")
    info["runtime_url"] = runtime_url
    path = getattr(args, "path", None) or "/runtime/permissions"

    print(_render(info))
    if not info["has_runtime_key"]:
        print()
        print("  verdict  : 本机没有 Runtime Key，签名这条链路还谈不上")
        print("  next     : 先在操作台铸一把「指名 agent」的钥匙，交给 agent（KARMA_RUNTIME_KEY）。")
        return 1

    from karma_openclaw.agent_binding import agent_key_from_env, runtime_key_id

    key = None
    if info["has_runtime_key"]:
        _ensure_importable()
        from karma_openclaw.http_client import runtime_key

        key = runtime_key()

    unsigned = await _probe(url=runtime_url, key=key, headers={}, path=path)
    message, headers = build_probe(key_id=info["runtime_key_id"] or runtime_key_id(key or ""),
                                   method="GET", path=path)
    signed_headers: dict[str, str] = {}
    private = agent_key_from_env()
    if private is not None:
        signature = base64.b64encode(private.sign(message.encode("utf-8"))).decode()
        signed_headers = dict(headers)
        signed_headers["X-Karma-Agent-Signature"] = signature
    signed = await _probe(url=runtime_url, key=key, headers=signed_headers, path=path)

    print("")
    print("unsigned GET %s -> %s %s" % (path, unsigned[0], unsigned[1][:120]))
    print("signed   GET %s -> %s %s" % (path, signed[0], signed[1][:120]))
    print("")
    print("signed message (逐行照这个拼，不要改顺序):")
    for line in message.splitlines():
        print("    " + line)
    conclusion, next_step = verdict(unsigned, signed)
    print("")
    print("verdict  : %s" % conclusion)
    if next_step:
        print("next     : %s" % next_step)

    if getattr(args, "json", False):
        print(json.dumps({
            "local": info,
            "unsigned": {"status": unsigned[0], "detail": unsigned[1]},
            "signed": {"status": signed[0], "detail": signed[1]},
            "message": message,
            "verdict": conclusion,
            "next": next_step,
        }, ensure_ascii=False, indent=2))
    return 0 if signed[0] == 200 else 1


def main(argv: list[str] | None = None) -> int:
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(
        prog="karma-connect sign-check",
        description="Check the per-request Ed25519 signing path against a live node.")
    parser.add_argument("--runtime-url", default=None, help="Karma node (default: from credentials)")
    parser.add_argument("--path", default="/runtime/permissions", help="read-only path to probe")
    parser.add_argument("--json", action="store_true", help="also print a machine-readable block")
    args = parser.parse_args(argv)
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
