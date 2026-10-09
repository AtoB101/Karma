"""Agent 侧 Runtime Key 请求签名。

与 ``services/runtime_wallet.build_agent_request_message``（服务端）**逐字对齐**。
两边由测试钉死，格式不得漂移。

私钥只在本进程内存里使用，永不外露、永不进日志。
"""

from __future__ import annotations

import base64
import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

_NEWLINE = chr(10)


def runtime_key_id(token: str) -> str:
    """从 ``KRM_RT_<key_id>_<secret>`` 取出 key_id（签名消息需要它）。"""
    raw = (token or "").strip()
    if not raw.startswith("KRM_RT_"):
        return ""
    head, _, _ = raw[len("KRM_RT_") :].partition("_")
    return head


def agent_key_from_seed(seed: str) -> Any:
    """base64(32 raw bytes) 或 64 位 hex → Ed25519PrivateKey。"""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    text = (seed or "").strip()
    if not text:
        raise ValueError("agent private key is empty")
    if len(text) == 64 and all(c in "0123456789abcdefABCDEF" for c in text):
        raw = bytes.fromhex(text)
    else:
        raw = base64.b64decode(text, validate=True)
    if len(raw) != 32:
        raise ValueError("agent private key must be 32 raw bytes (base64 or hex seed)")
    return Ed25519PrivateKey.from_private_bytes(raw)


def agent_public_key_b64(key: Any) -> str:
    from cryptography.hazmat.primitives import serialization

    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode()


def canonical_public_key_b64(public_key: str) -> str:
    """收敛成 canonical base64(raw 32 bytes)；不是 32 字节裸公钥就返回空串。

    fingerprint 必须先把 base64 / hex 两种写法收敛成同一个值，否则同一把钥匙
    在两处会显示成两串不同的 hex，主人核对就失去意义。
    """
    text = (public_key or "").strip()
    if not text:
        return ""
    compact = "".join(text.split())
    if compact[:2].lower() == "0x":
        compact = compact[2:]
    try:
        if len(compact) == 64 and all(c in "0123456789abcdefABCDEF" for c in compact):
            raw = bytes.fromhex(compact)
        else:
            raw = base64.b64decode(compact, validate=True)
    except Exception:  # noqa: BLE001 - 形状不对就当没有指纹
        return ""
    if len(raw) != 32:
        return ""
    return base64.b64encode(raw).decode()


def agent_public_key_fingerprint(public_key_b64: str, *, length: int = 16) -> str:
    """与后端 ``runtime_key_service.agent_binding_fingerprint`` 同口径（sha256 前 16 位）。

    口径：先收敛成 canonical base64(raw 32 bytes)，再对**那串 base64 文本**取
    sha256。配对卡片、key 列表、agent 自报三处必须是同一串 hex —— 差一个编码
    方式，主人核对的就是两串对不上的数。
    """
    canonical = canonical_public_key_b64(public_key_b64)
    if not canonical:
        return ""
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:length]


def build_agent_request_message(
    *, key_id: str, method: str, path: str, timestamp: str, nonce: str, body_sha256: str
) -> str:
    """服务端重算的那段文字。**不要**改动行序。"""
    return _NEWLINE.join(
        [
            "Karma Runtime Request",
            "key_id:" + key_id,
            "method:" + method.upper(),
            "path:" + path,
            "timestamp:" + timestamp,
            "nonce:" + nonce,
            "body_sha256:" + body_sha256,
        ]
    )


def sign_runtime_request(
    *, key: Any, key_id: str, method: str, path: str, body: bytes
) -> dict[str, str]:
    """已绑公钥的 key 每个请求必须带上的三个头。"""
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    nonce = uuid.uuid4().hex
    message = build_agent_request_message(
        key_id=key_id,
        method=method,
        path=path,
        timestamp=timestamp,
        nonce=nonce,
        body_sha256=hashlib.sha256(body or b"").hexdigest(),
    )
    signature = base64.b64encode(key.sign(message.encode("utf-8"))).decode()
    return {
        "X-Karma-Agent-Signature": signature,
        "X-Karma-Runtime-Timestamp": timestamp,
        "X-Karma-Runtime-Nonce": nonce,
    }


def build_agent_pairing_request_message(
    *, agent_name: str, public_key: str, nonce: str, timestamp: str
) -> str:
    """与 ``services/runtime_wallet.build_agent_pairing_request_message`` 逐字对齐。"""
    return _NEWLINE.join(
        [
            "Karma Agent Pairing Request",
            "agent_name:" + agent_name,
            "public_key:" + public_key,
            "nonce:" + nonce,
            "timestamp:" + timestamp,
        ]
    )


def sign_pairing_request(*, key: Any, agent_name: str, public_key: str) -> dict[str, str]:
    """申请接入要带的三件套：签名 + nonce + 时间戳。

    公钥从此不再是「申报」：服务端用这段签名证明申请方真的持有那把私钥。
    """
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    nonce = uuid.uuid4().hex
    message = build_agent_pairing_request_message(
        agent_name=agent_name, public_key=public_key, nonce=nonce, timestamp=timestamp
    )
    return {
        "signature": base64.b64encode(key.sign(message.encode("utf-8"))).decode(),
        "nonce": nonce,
        "timestamp": timestamp,
    }


def ensure_local_agent_key() -> Any | None:
    """本机 agent 私钥：有就用，没有就现生成一把并落盘（0600）。

    这把私钥是「光有钥匙字符串花不了钱」的全部依据，它必须只存在于 agent 本机 ——
    Karma 服务端从头到尾看不到它，只收到公钥，用来把 Runtime Key 钉在这次的 agent 身上。
    """
    from karma_mcp_server.credentials import credential

    seed = credential("KARMA_AGENT_PRIVATE_KEY")
    if seed:
        try:
            return agent_key_from_seed(seed)
        except Exception:  # noqa: BLE001, S110 - 种子坏了就当没有，重新生成会把旧的覆盖掉
            pass
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        from karma_mcp_server.credential_store import upsert_credential

        key = Ed25519PrivateKey.generate()
        upsert_credential(
            "KARMA_AGENT_PRIVATE_KEY", base64.b64encode(key.private_bytes_raw()).decode()
        )
        return key
    except Exception:  # noqa: BLE001 - 落不了盘就当没有，退回「领取时再绑」那条老路
        return None
