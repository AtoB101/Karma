"""节点自有 key 的签名校验（``VERIFIER_REQUIRE_NODE_SIGNATURE``）。

``/v1/verifiers`` 的写接口以前只要求「有一个已登录的会话」，请求体里的
``wallet_address`` 只是一串自报的地址 —— 谁登录谁就能替别人的节点登记、改质押、出证。
这一层补上「节点自己的 key 签了名」，并钉住三件容易漂的事：

* 签名消息格式（服务端 / 节点程序两边各写一份，这里用字面量钉死）；
* 没签名 401、签名对不上钱包 403、nonce 重放 409；
* 开关关着时老客户端照常能用（测试网先跑通，生产由 settings 校验强制打开）。
"""
from __future__ import annotations

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from config.settings import settings
from decentralized_verifier.models import VerifierNode
from services import verifier_wallet


def _sign(key, message: str) -> str:
    signed = Account.sign_message(encode_defunct(text=message), private_key=key.key)
    return "0x" + signed.signature.hex()


def _wallet(seed: int) -> str:
    return "0x" + ("%040x" % seed)


@pytest.fixture
def node_signature_required():
    """把开关打开（默认关 = 测试网口径）；用例结束还原，别污染别的用例。"""
    saved = settings.verifier_require_node_signature
    settings.verifier_require_node_signature = True
    try:
        yield
    finally:
        settings.verifier_require_node_signature = saved


# ---------------------------------------------------------------- 消息格式


def test_register_message_format_is_pinned():
    assert verifier_wallet.build_node_register_message(
        wallet_address=_wallet(0xAB), stake_amount=500.0,
        endpoint_url="https://v.example", nonce="n-1",
    ) == "\n".join([
        "Karma Verifier Node Register",
        "wallet_address:" + _wallet(0xAB),
        "stake_amount:500",
        "endpoint_url:https://v.example",
        "nonce:n-1",
    ])


def test_stake_and_attestation_message_formats_are_pinned():
    assert verifier_wallet.build_node_stake_message(
        verifier_id="v1", wallet_address=_wallet(1), stake_amount=0.02, nonce="n-2",
    ) == "\n".join([
        "Karma Verifier Node Stake",
        "verifier_id:v1",
        "wallet_address:" + _wallet(1),
        "stake_amount:0.02",
        "nonce:n-2",
    ])
    assert verifier_wallet.build_node_attestation_message(
        verifier_id="v1", wallet_address=_wallet(1), task_id="t1", decision="ATTESTED_OK",
        bundle_id=None, bundle_cid="cid", checks_passed=5, checks_total=7, nonce="n-3",
    ) == "\n".join([
        "Karma Verifier Node Attestation",
        "verifier_id:v1",
        "wallet_address:" + _wallet(1),
        "task_id:t1",
        "decision:ATTESTED_OK",
        "bundle_id:",
        "bundle_cid:cid",
        "checks_passed:5",
        "checks_total:7",
        "nonce:n-3",
    ])


def test_challenge_message_formats_are_pinned():
    assert verifier_wallet.build_node_challenge_message(
        wallet_address=_wallet(2), task_id="t2", bundle_id=None, reason="r",
        quorum_size=3, nonce="n-4",
    ) == "\n".join([
        "Karma Verifier Node Challenge",
        "wallet_address:" + _wallet(2),
        "task_id:t2",
        "bundle_id:",
        "reason:r",
        "quorum_size:3",
        "nonce:n-4",
    ])
    assert verifier_wallet.build_node_challenge_resolve_message(
        wallet_address=_wallet(2), challenge_id="c1", status="RESOLVED",
        resolution="ok", nonce="n-5",
    ) == "\n".join([
        "Karma Verifier Node Challenge Resolve",
        "wallet_address:" + _wallet(2),
        "challenge_id:c1",
        "status:RESOLVED",
        "resolution:ok",
        "nonce:n-5",
    ])


def test_numbers_are_written_the_same_way_on_both_sides():
    """数字口径：定点、最多 6 位小数、去尾零 —— 500.0 写 ``500``，不是 ``500.0``。"""
    def amount(value):
        message = verifier_wallet.build_node_stake_message(
            verifier_id="v", wallet_address=_wallet(3), stake_amount=value, nonce="n",
        )
        return [line for line in message.split("\n") if line.startswith("stake_amount:")][0]

    assert amount(500.0) == "stake_amount:500"
    assert amount(500.5) == "stake_amount:500.5"
    assert amount(0.020000) == "stake_amount:0.02"
    assert amount(1e-9) == "stake_amount:0"
    assert amount(None) == "stake_amount:0"


# ---------------------------------------------------------------- 待签文字接口


@pytest.mark.anyio
async def test_sign_message_endpoint_returns_the_canonical_text(client):
    payload = {"wallet_address": _wallet(9), "stake_amount": 300.0, "signature_nonce": "n-9"}
    resp = await client.post(
        "/v1/verifiers/sign-message", json={"kind": "register", "payload": payload}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["nonce"] == "n-9"
    assert body["message"] == verifier_wallet.build_node_register_message(
        wallet_address=_wallet(9), stake_amount=300.0, endpoint_url=None, nonce="n-9"
    )


@pytest.mark.anyio
async def test_sign_message_endpoint_rejects_unknown_kind(client):
    resp = await client.post("/v1/verifiers/sign-message", json={"kind": "nope", "payload": {}})
    assert resp.status_code == 422


# ---------------------------------------------------------------- 闸门


@pytest.mark.anyio
async def test_gate_off_keeps_existing_clients_working(client):
    """开关关着（默认）时行为与升级前完全一致 —— 不能把已经在跑的节点打掉。"""
    assert settings.verifier_require_node_signature is False
    resp = await client.post(
        "/v1/verifiers/register", json={"wallet_address": _wallet(0x33), "stake_amount": 1.0}
    )
    assert resp.status_code == 201, resp.text


def _register_body(acct, nonce):
    return {
        "wallet_address": acct.address,
        "stake_amount": 500.0,
        "signature_nonce": nonce,
    }


def _register_message(acct, nonce):
    return verifier_wallet.build_node_register_message(
        wallet_address=acct.address, stake_amount=500.0, endpoint_url=None, nonce=nonce
    )


@pytest.mark.anyio
async def test_register_needs_a_signature_from_the_node_wallet(client, node_signature_required):
    acct = Account.create()

    unsigned = await client.post("/v1/verifiers/register", json=_register_body(acct, "reg-nonce-1"))
    assert unsigned.status_code == 401, unsigned.text

    # 乱码签名是「请求体坏了」（恢复不出地址 → 400），不是「你不是本人」（403）。
    malformed = dict(_register_body(acct, "reg-nonce-2"), signature="0x" + "11" * 65)
    resp = await client.post("/v1/verifiers/register", json=malformed)
    assert resp.status_code == 400, resp.text

    # 格式对、但不是这个钱包签的 → 403。
    wrong = dict(
        _register_body(acct, "reg-nonce-3"),
        signature=_sign(Account.create(), _register_message(acct, "reg-nonce-3")),
    )
    resp = await client.post("/v1/verifiers/register", json=wrong)
    assert resp.status_code == 403, resp.text

    ok = dict(
        _register_body(acct, "reg-nonce-4"),
        signature=_sign(acct, _register_message(acct, "reg-nonce-4")),
    )
    resp = await client.post("/v1/verifiers/register", json=ok)
    assert resp.status_code == 201, resp.text
    assert resp.json()["wallet_address"] == acct.address


@pytest.mark.anyio
async def test_a_signature_over_a_tampered_body_is_rejected(client, node_signature_required):
    """签名盖的是「钱包 + 金额 + nonce」整段：改了金额，签名就对不上。"""
    acct = Account.create()
    nonce = "tamper-nonce-1"
    signature = _sign(
        acct,
        verifier_wallet.build_node_register_message(
            wallet_address=acct.address, stake_amount=1.0, endpoint_url=None, nonce=nonce
        ),
    )
    resp = await client.post(
        "/v1/verifiers/register",
        json={
            "wallet_address": acct.address,
            "stake_amount": 999999.0,
            "signature": signature,
            "signature_nonce": nonce,
        },
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.anyio
async def test_another_key_cannot_sign_for_someone_elses_node(client, node_signature_required):
    owner = Account.create()
    intruder = Account.create()
    nonce = "intruder-nonce-1"
    resp = await client.post(
        "/v1/verifiers/register",
        json={
            "wallet_address": owner.address,
            "stake_amount": 10.0,
            "signature": _sign(
                intruder,
                verifier_wallet.build_node_register_message(
                    wallet_address=owner.address, stake_amount=10.0,
                    endpoint_url=None, nonce=nonce,
                ),
            ),
            "signature_nonce": nonce,
        },
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.anyio
async def test_replayed_nonce_is_rejected(client, db_session, node_signature_required):
    acct = Account.create()
    node = VerifierNode(wallet_address=acct.address, stake_amount=1.0)
    db_session.add(node)
    await db_session.commit()

    nonce = "replay-nonce-1"
    body = {
        "stake_amount": 200.0,
        "signature_nonce": nonce,
        "signature": _sign(
            acct,
            verifier_wallet.build_node_stake_message(
                verifier_id=node.id, wallet_address=acct.address,
                stake_amount=200.0, nonce=nonce,
            ),
        ),
    }
    first = await client.post("/v1/verifiers/%s/stake" % node.id, json=body)
    assert first.status_code == 200, first.text
    second = await client.post("/v1/verifiers/%s/stake" % node.id, json=body)
    assert second.status_code == 409, second.text


@pytest.mark.anyio
async def test_attestation_and_challenge_are_signed_too(client, db_session, node_signature_required):
    acct = Account.create()
    node = VerifierNode(wallet_address=acct.address, is_active=True)
    db_session.add(node)
    await db_session.commit()

    attestation = {
        "task_id": "task-sig-1",
        "verifier_id": node.id,
        "decision": "ATTESTED_OK",
        "checks_passed": 1,
        "checks_total": 1,
        "signature_nonce": "att-nonce-1",
    }
    unsigned = await client.post("/v1/verifiers/attestations", json=attestation)
    assert unsigned.status_code == 401, unsigned.text

    attestation["signature"] = _sign(
        acct,
        verifier_wallet.build_node_attestation_message(
            verifier_id=node.id, wallet_address=acct.address, task_id="task-sig-1",
            decision="ATTESTED_OK", bundle_id=None, bundle_cid=None,
            checks_passed=1, checks_total=1, nonce="att-nonce-1",
        ),
    )
    ok = await client.post("/v1/verifiers/attestations", json=attestation)
    assert ok.status_code == 201, ok.text

    challenge = {
        "task_id": "task-sig-1",
        "wallet_address": acct.address,
        "reason": "recheck",
        "quorum_size": 3,
        "signature_nonce": "chal-nonce-1",
    }
    challenge["signature"] = _sign(
        acct,
        verifier_wallet.build_node_challenge_message(
            wallet_address=acct.address, task_id="task-sig-1", bundle_id=None,
            reason="recheck", quorum_size=3, nonce="chal-nonce-1",
        ),
    )
    opened = await client.post("/v1/verifiers/challenges", json=challenge)
    assert opened.status_code == 201, opened.text
