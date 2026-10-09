"""EIP-191 personal message verification for Runtime Key wallet-bound actions."""
from __future__ import annotations

from datetime import datetime

from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi import HTTPException


def _normalize_sig(sig: str) -> bytes:
    s = (sig or "").strip()
    if s.startswith("0x"):
        s = s[2:]
    if len(s) != 130:
        raise HTTPException(status_code=400, detail="wallet_signature must be 65-byte hex (0x + 130 hex chars)")
    try:
        return bytes.fromhex(s)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="wallet_signature is not valid hex") from exc


def verify_personal_message(*, message: str, wallet_address: str, wallet_signature: str) -> None:
    """Recover signer and require it to match ``wallet_address`` (case-insensitive)."""
    wa = (wallet_address or "").strip()
    if not wa.startswith("0x") or len(wa) != 42:
        raise HTTPException(status_code=400, detail="wallet_address must be a 0x-prefixed 20-byte address")
    try:
        recovered = Account.recover_message(
            encode_defunct(text=message),
            signature=_normalize_sig(wallet_signature),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail="wallet_signature verification failed") from exc
    if recovered.lower() != wa.lower():
        raise HTTPException(status_code=403, detail="wallet_signature does not match wallet_address")


def build_create_key_message(
    *,
    karma_identity_id: str,
    wallet_address: str,
    permissions: list[str],
    single_limit: float,
    daily_limit: float,
    expire_time: datetime | str | None,
    agent_name: str,
    agent_binding: str | None,
    agent_public_key_fingerprint: str | None = None,
) -> str:
    # 不填到期时间 = 长期有效。写进签名消息的是固定字面量 "never"，两边都能重建。
    if expire_time is None or (isinstance(expire_time, str) and not expire_time.strip()):
        expire_line = "never"
    elif isinstance(expire_time, str):
        expire_line = expire_time.strip()
    else:
        expire_line = expire_time.isoformat()
    lines = [
        "Karma Runtime Key Create",
        f"karma_identity_id:{karma_identity_id}",
        f"wallet_address:{wallet_address}",
        f"permissions:{','.join(sorted(permissions))}",
        f"single_limit:{single_limit}",
        f"daily_limit:{daily_limit}",
        f"expire_time:{expire_line}",
        f"agent_name:{agent_name}",
        f"agent_binding:{agent_binding or ''}",
        # 把「这把钱钥匙是铸给哪把 agent 公钥」也钉进钱包签名里：主人签的是
        # 「授权给这个指纹对应的 agent」，而不再只是一个可以随手改写的名字。
        # 绑定那一刻服务端会拿 agent 交上来的公钥重算指纹，对不上直接拒绝。
        f"agent_public_key_fingerprint:{agent_public_key_fingerprint or ''}",
    ]
    return "\n".join(lines)


def build_agent_request_message(
    *,
    key_id: str,
    method: str,
    path: str,
    timestamp: str,
    nonce: str,
    body_sha256: str,
) -> str:
    """已绑定公钥的 key 每个请求签的就是这段文字。

    时间戳是规范化后的 UTC 秒（YYYY-MM-DDTHH:MM:SSZ），路径不含查询串，
    body_sha256 是对原始请求体字节取 sha256 —— 服务端按同样的规则重算，对不上就 401。
    """
    return "\n".join(
        [
            "Karma Runtime Request",
            f"key_id:{key_id}",
            f"method:{method.upper()}",
            f"path:{path}",
            f"timestamp:{timestamp}",
            f"nonce:{nonce}",
            f"body_sha256:{body_sha256}",
        ]
    )


def build_agent_pairing_request_message(
    *, agent_name: str, public_key: str, nonce: str, timestamp: str
) -> str:
    """agent 申请接入时，用它自己的 Ed25519 私钥签的这段文字。

    服务端拿申请里的公钥重算同一段文字验签 —— 公钥从「申报」变成「持有证明」。
    时间戳是规范化后的 UTC 秒（YYYY-MM-DDTHH:MM:SSZ）。
    """
    return "\n".join(
        [
            "Karma Agent Pairing Request",
            f"agent_name:{agent_name}",
            f"public_key:{public_key}",
            f"nonce:{nonce}",
            f"timestamp:{timestamp}",
        ]
    )


def build_revoke_key_message(*, key_id: str, karma_identity_id: str, wallet_address: str) -> str:
    return "\n".join(
        [
            "Karma Runtime Key Revoke",
            f"key_id:{key_id}",
            f"karma_identity_id:{karma_identity_id}",
            f"wallet_address:{wallet_address}",
        ]
    )


def build_confirm_bind_message(
    *,
    key_id: str,
    karma_identity_id: str,
    wallet_address: str,
    activation_code: str,
    client_nonce: str,
) -> str:
    """用户在操作台敲下匹配码那一下签的就是这段文字 —— 把码也钉进签名里。"""
    return "\n".join(
        [
            "Karma Runtime Key Bind Confirm",
            f"key_id:{key_id}",
            f"karma_identity_id:{karma_identity_id}",
            f"wallet_address:{wallet_address}",
            f"activation_code:{activation_code}",
            f"client_nonce:{client_nonce}",
        ]
    )


def build_reject_bind_message(
    *,
    key_id: str,
    karma_identity_id: str,
    wallet_address: str,
    client_nonce: str,
) -> str:
    """用户拒绝这次接入时签的那段文字。"""
    return "\n".join(
        [
            "Karma Runtime Key Bind Reject",
            f"key_id:{key_id}",
            f"karma_identity_id:{karma_identity_id}",
            f"wallet_address:{wallet_address}",
            f"client_nonce:{client_nonce}",
        ]
    )


def build_list_bind_requests_message(
    *, karma_identity_id: str, wallet_address: str, client_nonce: str
) -> str:
    """操作台拉取「待确认接入请求」时签的那段文字。"""
    return "\n".join(
        [
            "Karma Runtime Key Bind List",
            f"karma_identity_id:{karma_identity_id}",
            f"wallet_address:{wallet_address}",
            f"client_nonce:{client_nonce}",
        ]
    )

def build_list_keys_message(*, karma_identity_id: str, wallet_address: str, client_nonce: str) -> str:
    return "\n".join(
        [
            "Karma Runtime Key List",
            f"karma_identity_id:{karma_identity_id}",
            f"wallet_address:{wallet_address}",
            f"client_nonce:{client_nonce}",
        ]
    )


def build_unbind_key_message(
    *, key_id: str, karma_identity_id: str, wallet_address: str, client_nonce: str
) -> str:
    """主人在设置页点「取消绑定」时签的那段文字。"""
    return "\n".join(
        [
            "Karma Runtime Key Unbind",
            f"key_id:{key_id}",
            f"karma_identity_id:{karma_identity_id}",
            f"wallet_address:{wallet_address}",
            f"client_nonce:{client_nonce}",
        ]
    )
