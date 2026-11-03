"""Batch settlement coordinator — validate, order, DA, calldata."""
from __future__ import annotations

import pytest
from eth_abi import decode
from eth_utils import keccak
from fastapi import HTTPException

from services import batch_settlement, proof_availability, settlement_channel
from eth_account import Account

KEY_A = "0x3333333333333333333333333333333333333333333333333333333333333333"
KEY_B = "0x4444444444444444444444444444444444444444444444444444444444444444"
ADDR_A = Account.from_key(KEY_A).address
ADDR_B = Account.from_key(KEY_B).address

SELECTOR = keccak(text="batchSettle((uint256,bytes32)[])")[:4]


def _item(binding_id: int, seq: int, payload: str, key=KEY_A, signer=ADDR_A):
    proof_hash = proof_availability.compute_proof_hash(payload)
    state = {
        "channel_id": f"ch-{binding_id}",
        "seq": seq,
        "balances": {ADDR_A: "10.0", ADDR_B: "0.0"},
        "meta_hash": proof_hash,
    }
    signature = settlement_channel.sign_state(private_key=key, **state)
    return {
        "binding_id": binding_id,
        "proof_hash": proof_hash,
        "state": state,
        "signature": signature,
        "signer_address": signer,
    }


def test_validate_rejects_empty():
    with pytest.raises(HTTPException) as exc:
        batch_settlement.validate_batch_items([])
    assert exc.value.status_code == 422


def test_validate_rejects_bad_binding_id():
    item = _item(0, 1, "payload-0")
    with pytest.raises(HTTPException) as exc:
        batch_settlement.validate_batch_items([item])
    assert exc.value.status_code == 422


def test_validate_rejects_duplicate_binding_id():
    items = [_item(7, 1, "p1"), _item(7, 2, "p2")]
    with pytest.raises(HTTPException) as exc:
        batch_settlement.validate_batch_items(items)
    assert exc.value.status_code == 409


def test_validate_rejects_wrong_signer():
    item = _item(1, 1, "p1", key=KEY_A, signer=ADDR_B)
    with pytest.raises(HTTPException) as exc:
        batch_settlement.validate_batch_items([item])
    assert exc.value.status_code == 403


def test_validate_rejects_bad_proof_hash():
    item = _item(1, 1, "p1")
    item["proof_hash"] = "0x1234"
    with pytest.raises(HTTPException) as exc:
        batch_settlement.validate_batch_items([item])
    assert exc.value.status_code == 422


def test_validate_sorts_by_binding_id():
    items = [_item(3, 1, "p3"), _item(1, 1, "p1"), _item(2, 1, "p2")]
    normalized = batch_settlement.validate_batch_items(items)
    assert [i["binding_id"] for i in normalized] == [1, 2, 3]


def test_calldata_encodes_and_decodes_roundtrip():
    items = batch_settlement.validate_batch_items([_item(2, 1, "p2"), _item(1, 1, "p1")])
    calldata = batch_settlement.encode_batch_settle_calldata(items)
    assert calldata.startswith("0x")
    assert bytes.fromhex(calldata[2:10]) == SELECTOR
    decoded = decode(["(uint256,bytes32)[]"], bytes.fromhex(calldata[10:]))[0]
    assert [d[0] for d in decoded] == [1, 2]
    assert [d[1] for d in decoded] == [
        bytes.fromhex(items[0]["proof_hash"][2:]),
        bytes.fromhex(items[1]["proof_hash"][2:]),
    ]


def test_build_returns_anchor_and_calldata():
    items = [_item(2, 1, "p2"), _item(1, 1, "p1")]
    result = batch_settlement.build_batch_settlement(items)
    assert result["count"] == 2
    assert result["anchor_hash"] == settlement_channel.state_batch_hash(
        [i["state"] for i in batch_settlement.validate_batch_items(items)]
    )
    assert result["calldata"].startswith("0x")


@pytest.mark.asyncio
async def test_assert_proofs_available_rejects_bare_hash(db_session):
    items = batch_settlement.validate_batch_items([_item(1, 1, "p1")])
    with pytest.raises(HTTPException) as exc:
        await batch_settlement.assert_batch_proofs_available(db_session, items)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_assert_proofs_available_passes_when_stored(db_session):
    payload = "p1"
    items = batch_settlement.validate_batch_items([_item(1, 1, payload)])
    await proof_availability.store_proof(
        db_session, payload=payload, proof_hash=items[0]["proof_hash"]
    )
    await db_session.commit()
    await batch_settlement.assert_batch_proofs_available(db_session, items)

@pytest.mark.asyncio
async def test_build_route_end_to_end(client):
    payload = '{"delivery": "POD-2026-001", "inspected": true}'
    proof_hash = proof_availability.compute_proof_hash(payload)

    store = await client.post(
        "/v1/proofs", json={"payload": payload, "proof_hash": proof_hash}
    )
    assert store.status_code == 201, store.text

    resp = await client.post(
        "/v1/settlement-batch/build", json={"items": [_item(2, 1, payload)]}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 1
    assert body["anchor_hash"].startswith("0x")
    assert body["calldata"].startswith("0x")
    assert body["items"][0]["binding_id"] == 2


@pytest.mark.asyncio
async def test_build_route_rejects_unavailable_proof(client):
    resp = await client.post(
        "/v1/settlement-batch/build", json={"items": [_item(1, 1, "never-stored")]}
    )
    assert resp.status_code == 409, resp.text


@pytest.mark.asyncio
async def test_build_route_rejects_bad_signature(client):
    payload = "stored-payload"
    proof_hash = proof_availability.compute_proof_hash(payload)
    await client.post("/v1/proofs", json={"payload": payload, "proof_hash": proof_hash})

    item = _item(3, 1, payload, key=KEY_B, signer=ADDR_A)
    resp = await client.post("/v1/settlement-batch/build", json={"items": [item]})
    assert resp.status_code == 403, resp.text

