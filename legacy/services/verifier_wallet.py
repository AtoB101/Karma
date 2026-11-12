"""节点自有 key 的签名校验：``/v1/verifiers`` 的写接口到底是不是节点本人发的。

背景
----
``/v1/verifiers`` 的写接口（登记节点 / 改质押 / 出证 / 开挑战 / 裁决挑战）以前只要求
「有一个已登录的会话」，请求体里的 ``wallet_address`` 只是一串自报的地址 ——
谁登录谁就能替别人的节点登记、改质押、出证。节点网络是资金相关面，这一层必须补上
「节点自己的 key 签了名」才算数。

设计（与 services/runtime_wallet.py 同一套路）
------------------------------
- 签名是 EIP-191 personal message，恢复出来的地址必须等于这条请求里指向的节点钱包；
- 签名消息由本模块**唯一**生成（``build_*_message``），节点程序按同一份格式重建
  （操作台不自己拼消息：跟 ``POST /v1/verifiers/sign-message`` 要一段待签文字）；
- 每条签名都带一个 ``signature_nonce``，服务端按（钱包, 端点, nonce）去重，防重放；
- 开关 ``VERIFIER_REQUIRE_NODE_SIGNATURE`` 默认关（测试网先跑通），生产强制打开。

一句话：**光有会话不够，得是节点自己的 key 签的**。

签名消息格式（一行一个字段，顺序固定，LF 换行）
------------------------------
第一行是动作名，之后每行 ``字段:值``，最后一行是 ``nonce:<一次性随机串>``。
数字按 ``%.6f`` 取消尾零（500.0 -> ``500``）—— 两边都按这个口径才能重建出同一串字节。
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from services.runtime_key_service import check_replay_nonce
from services.runtime_wallet import verify_personal_message

#: 可以要求签名的写动作。
SIGN_MESSAGE_KINDS = (
    "register",
    "stake",
    "unstake",
    "attestation",
    "challenge",
    "challenge_resolve",
)


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _dec(value: Any) -> str:
    """数字在签名消息里的唯一写法：定点、最多 6 位小数、去尾零。

    500 -> ``500``，0.02 -> ``0.02``，1e-9 -> ``0``。用 ``repr(float)`` 会得到 ``500.0``，
    节点程序（Node/Go 都是）拼不出同样的串，所以统一走这一个口径。
    """
    text = "%.6f" % float(value or 0.0)
    text = text.rstrip("0").rstrip(".")
    return text or "0"


def build_node_register_message(
    *, wallet_address: str, stake_amount: Any, endpoint_url: str | None, nonce: str
) -> str:
    return "\n".join(
        [
            "Karma Verifier Node Register",
            f"wallet_address:{_text(wallet_address)}",
            f"stake_amount:{_dec(stake_amount)}",
            f"endpoint_url:{_text(endpoint_url)}",
            f"nonce:{_text(nonce)}",
        ]
    )


def build_node_stake_message(
    *, verifier_id: str, wallet_address: str, stake_amount: Any, nonce: str
) -> str:
    return "\n".join(
        [
            "Karma Verifier Node Stake",
            f"verifier_id:{_text(verifier_id)}",
            f"wallet_address:{_text(wallet_address)}",
            f"stake_amount:{_dec(stake_amount)}",
            f"nonce:{_text(nonce)}",
        ]
    )


def build_node_unstake_message(
    *, verifier_id: str, wallet_address: str, amount: Any, nonce: str
) -> str:
    """退出动作也签名：**退出是单方面改变担保额**，比加押更需要是节点本人。"""
    return "\n".join(
        [
            "Karma Verifier Node Unstake",
            f"verifier_id:{_text(verifier_id)}",
            f"wallet_address:{_text(wallet_address)}",
            f"amount:{_dec(amount)}",
            f"nonce:{_text(nonce)}",
        ]
    )


def build_node_attestation_message(
    *,
    verifier_id: str,
    wallet_address: str,
    task_id: str,
    decision: str,
    bundle_id: str | None,
    bundle_cid: str | None,
    checks_passed: Any,
    checks_total: Any,
    nonce: str,
) -> str:
    return "\n".join(
        [
            "Karma Verifier Node Attestation",
            f"verifier_id:{_text(verifier_id)}",
            f"wallet_address:{_text(wallet_address)}",
            f"task_id:{_text(task_id)}",
            f"decision:{_text(decision)}",
            f"bundle_id:{_text(bundle_id)}",
            f"bundle_cid:{_text(bundle_cid)}",
            f"checks_passed:{_dec(checks_passed)}",
            f"checks_total:{_dec(checks_total)}",
            f"nonce:{_text(nonce)}",
        ]
    )


def build_node_challenge_message(
    *,
    wallet_address: str,
    task_id: str,
    bundle_id: str | None,
    reason: str | None,
    quorum_size: Any,
    nonce: str,
) -> str:
    return "\n".join(
        [
            "Karma Verifier Node Challenge",
            f"wallet_address:{_text(wallet_address)}",
            f"task_id:{_text(task_id)}",
            f"bundle_id:{_text(bundle_id)}",
            f"reason:{_text(reason)}",
            f"quorum_size:{_dec(quorum_size)}",
            f"nonce:{_text(nonce)}",
        ]
    )


def build_node_challenge_resolve_message(
    *,
    wallet_address: str,
    challenge_id: str,
    status: str,
    resolution: str | None,
    nonce: str,
) -> str:
    return "\n".join(
        [
            "Karma Verifier Node Challenge Resolve",
            f"wallet_address:{_text(wallet_address)}",
            f"challenge_id:{_text(challenge_id)}",
            f"status:{_text(status)}",
            f"resolution:{_text(resolution)}",
            f"nonce:{_text(nonce)}",
        ]
    )


def build_message(kind: str, payload: dict[str, Any] | None = None) -> str:
    """按动作组签名消息（供 ``POST /v1/verifiers/sign-message`` 使用）。

    ``payload`` 就是客户端即将发出的请求体（加上 ``signature_nonce``）。
    格式只有这一处，两边不会漂。
    """
    data = dict(payload or {})
    nonce = _text(data.get("signature_nonce"))
    if kind == "register":
        return build_node_register_message(
            wallet_address=data.get("wallet_address"),
            stake_amount=data.get("stake_amount"),
            endpoint_url=data.get("endpoint_url"),
            nonce=nonce,
        )
    if kind == "stake":
        return build_node_stake_message(
            verifier_id=data.get("verifier_id"),
            wallet_address=data.get("wallet_address"),
            stake_amount=data.get("stake_amount"),
            nonce=nonce,
        )
    if kind == "unstake":
        return build_node_unstake_message(
            verifier_id=data.get("verifier_id"),
            wallet_address=data.get("wallet_address"),
            amount=data.get("amount"),
            nonce=nonce,
        )
    if kind == "attestation":
        return build_node_attestation_message(
            verifier_id=data.get("verifier_id"),
            wallet_address=data.get("wallet_address"),
            task_id=data.get("task_id"),
            decision=data.get("decision"),
            bundle_id=data.get("bundle_id"),
            bundle_cid=data.get("bundle_cid"),
            checks_passed=data.get("checks_passed"),
            checks_total=data.get("checks_total"),
            nonce=nonce,
        )
    if kind == "challenge":
        return build_node_challenge_message(
            wallet_address=data.get("wallet_address"),
            task_id=data.get("task_id"),
            bundle_id=data.get("bundle_id"),
            reason=data.get("reason"),
            quorum_size=data.get("quorum_size"),
            nonce=nonce,
        )
    if kind == "challenge_resolve":
        return build_node_challenge_resolve_message(
            wallet_address=data.get("wallet_address"),
            challenge_id=data.get("challenge_id"),
            status=data.get("status"),
            resolution=data.get("resolution"),
            nonce=nonce,
        )
    raise HTTPException(400, "unknown node sign-message kind: %s" % kind)


def enforce_node_signature(
    *,
    enabled: bool,
    message: str,
    wallet_address: str,
    signature: str | None,
    nonce: str | None,
    endpoint: str,
) -> None:
    """写接口的签名闸门。

    开关关着时直接放行（测试网先跑通，不把已在跑的节点打掉）；
    打开后：没签名 401、没 nonce 400、nonce 重放 409、签名对不上地址 403。
    """
    if not enabled:
        return
    if not (signature or "").strip():
        raise HTTPException(
            401,
            "node signature required: sign the message from POST /v1/verifiers/sign-message "
            "with the node wallet and send it as signature + signature_nonce",
        )
    if not (nonce or "").strip():
        raise HTTPException(400, "signature_nonce is required when node signatures are enforced")
    check_replay_nonce(
        key_id=(wallet_address or "").strip().lower(), endpoint=endpoint, nonce=nonce
    )
    verify_personal_message(
        message=message, wallet_address=wallet_address, wallet_signature=signature
    )
