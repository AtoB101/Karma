# -*- coding: utf-8 -*-
"""\u2463-B1\uff1a\u8d28\u62bc\u5fc5\u987b\u771f\u7684\u9501\u5728\u94fe\u4e0a\u91d1\u5e93\uff08KarmaVerifierBond\uff09\u91cc\u3002

\u4e3a\u4ec0\u4e48\u5355\u72ec\u9489\u8fd9\u4e00\u6761
------------------
\u6b64\u524d\u300c\u8d28\u62bc\u5373\u51c6\u5165\u300d\u53ea\u770b\u8d26\u9762\u80cc\u4e66\uff08``capacity.total_locked_usdc``\uff09\uff0c\u4f46\u94fe\u4e0a ``slash()``
\u53ea\u80fd\u5212\u91d1\u5e93\u91cc\u90a3\u7b14 ``Bond``\uff1a\u62bc\u91d1\u4e0d\u5728\u91d1\u5e93\uff0c\u300c\u5224\u8d1f\u5f53\u573a\u751f\u6548\u300d\u5c31\u53ea\u5269\u4e00\u5f20\u7a7a\u5934\u627f\u8bfa\u3002
\u540c\u65f6\uff0c``/overturn`` \u6b64\u524d\u8bb0\u7684\u662f ``wallet_address=None``\uff0c\u4e8e\u662f\u300c\u7f5a\u8c01\u300d\u5728\u94fe\u4e0a\u65e0\u4ece\u6307\u8ba4\u3002

\u8fd9\u91cc\u9489\u4e09\u4ef6\u4e8b\uff1a

1. **\u94fe\u4e0a\u8bfb**\uff08``read_bonds``\uff09\uff1a\u91d1\u989d\u53ea\u4ece\u94fe\u4e0a ``bondAmount`` \u6765\uff1b\u8bfb\u4e0d\u5230\u5c31\u629b
   ``BondVaultUnavailable``\uff0c**\u7edd\u4e0d\u5f53\u6210 0**\uff08\u5f53\u6210 0 \u4f1a\u8bef\u505c\u5408\u683c\u7684\u5c97\uff1b\u5f53\u6210\u6709 \u4f1a\u653e\u884c\u6ca1\u94b1\u7684\u4eba\uff09\u3002
2. **\u95f8\u95e8**\uff08``arbitration_require_vault_bond`` / ``verifier_require_vault_bond``\uff09\uff1a\u6253\u5f00\u540e\u5165\u6c60\u4e0e\u6295\u7968\u90fd
   \u56de\u94fe\u4e0a\u6838\u5bf9\uff1b\u5173\u7740\u65f6\u4e0e\u5386\u53f2\u884c\u4e3a\u4e00\u81f4\uff08\u96f6\u884c\u4e3a\u53d8\u5316\uff09\u3002
3. **\u6307\u8ba4**\uff1a``/overturn`` \u8bb0\u7684\u662f\u8be5\u4ef2\u88c1\u5458\u5728 Console \u7ed1\u5b9a\u7684\u94b1\u5305 \u2014\u2014 \u8fd9\u6837
   ``slash_instructions()`` \u624d\u4ea7\u5f97\u51fa\u4e00\u7b14\u80fd\u771f\u53d1\u7684\u94fe\u4e0a\u8bf4\u660e\u3002
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from config.settings import settings
from db.models.orm import (
    ArbitrationAssignmentModel,
    ArbitrationCaseModel,
    ArbitrationPoolMemberModel,
    IdentityProfileModel,
    IdentityRoleProfile,
    TaskContractModel,
)
from decentralized_verifier.models import BondSlash
from services import arbitration_rules as arb_rules
from services import bond_slash, verifier_bond
from services.chain import verifier_bond_vault as vbv

VAULT = "0x8eBCF8668a6B54872A4e747d82dB152095B21027"
WALLET = "0x444b6E82249149D50D0F9ca49DCf7cdC3B73FFd6"
OTHER_WALLET = "0xEf3A7590E3b6528B07ffD5fa5CDe61Ccf857D5F4"

IDENTITY = "arb-b1"
RPC = "https://rpc.invalid"


# ---------------------------------------------------------------------------
# \u5047\u94fe\uff1a\u53ea\u586b ``read_bonds_sync`` \u771f\u6b63\u7528\u5230\u7684\u90a3\u51e0\u4e2a\u51fd\u6570
# ---------------------------------------------------------------------------
class _Call:
    def __init__(self, value):
        self._value = value

    def call(self):
        return self._value


class _Fns:
    """``contract.functions.<name>(address).call()``\u3002"""

    def __init__(self, readings):
        self._readings = readings

    def __getattr__(self, name):
        def _fn(address):
            key = str(address).strip().lower()
            row = self._readings.get(key)
            if row is None:
                raise AssertionError("unexpected wallet read: %r" % address)
            return _Call(row[name])

        return _fn


class _Contract:
    def __init__(self, readings):
        self.functions = _Fns(readings)


class _Eth:
    def __init__(self, readings, receipt=None, tx=None):
        self._readings = readings
        self._receipt = receipt
        self._tx = tx

    def contract(self, address, abi):
        return _Contract(self._readings)

    def get_transaction_receipt(self, tx_hash):
        return self._receipt

    def get_transaction(self, tx_hash):
        return self._tx


def _fake_web3_module(readings=None, *, explode=False, receipt=None, tx=None):
    class _FakeWeb3:
        def __init__(self, provider=None, **kwargs):
            pass

        eth = _Eth(readings or {}, receipt, tx)

        @staticmethod
        def to_checksum_address(value):
            return value

        @staticmethod
        def HTTPProvider(url, request_kwargs=None):
            return url

    if explode:
        def _boom(address, abi):
            raise RuntimeError("rpc exploded")

        _FakeWeb3.eth = SimpleNamespace(contract=_boom)
    return SimpleNamespace(Web3=_FakeWeb3)


def _readings(wallet=WALLET, *, registered=True, active=True, bond=0.0):
    return {
        wallet.lower(): {
            "isRegistered": registered,
            "isActive": active,
            "bondAmount": round(float(bond) * 1_000_000),
        }
    }


@pytest.fixture(autouse=True)
def _chain_config(monkeypatch):
    """\u9ed8\u8ba4\uff1a\u91d1\u5e93\u914d\u597d\u3001RPC \u6709\u5730\u5740\u3001\u4e24\u4e2a\u95f8\u95e8\u90fd\u5173\u3002\u6bcf\u6761\u7528\u4f8b\u5404\u81ea\u8986\u76d6\u3002"""
    monkeypatch.setattr(settings, "verifier_bond_vault_address", VAULT)
    monkeypatch.setattr(settings, "testnet_rpc_url", RPC)
    monkeypatch.setattr(settings, "arbitration_require_vault_bond", False)
    monkeypatch.setattr(settings, "verifier_require_vault_bond", False)
    yield


async def _bind_wallet(db, identity_id=IDENTITY, wallet=WALLET):
    db.add(
        IdentityProfileModel(
            identity_id=identity_id,
            display_id="Karma-ID-B1",
            legal_identity_status="unbound",
            status="active",
            bound_wallet_address=wallet,
        )
    )
    await db.commit()


# ---------------------------------------------------------------------------
# 1) \u94fe\u4e0a\u8bfb\uff1a\u91d1\u989d\u53ea\u4ece\u94fe\u4e0a\u6765\uff0c\u8bfb\u4e0d\u5230\u5c31 fail-closed
# ---------------------------------------------------------------------------
def test_read_bonds_takes_the_amount_from_the_chain(monkeypatch):
    monkeypatch.setitem(sys.modules, "web3", _fake_web3_module(_readings(bond=5.0)))
    out = vbv.read_bonds_sync([WALLET.upper()])
    row = out[WALLET.lower()]
    assert row["bond_usdc"] == 5.0
    assert row["registered"] is True and row["active"] is True
    assert row["vault"] == VAULT


def test_read_bonds_is_fail_closed_without_a_vault(monkeypatch):
    monkeypatch.setattr(settings, "verifier_bond_vault_address", "")
    with pytest.raises(vbv.BondVaultUnavailable, match="VERIFIER_BOND_VAULT_ADDRESS"):
        vbv.read_bonds_sync([WALLET])


def test_read_bonds_is_fail_closed_without_rpc(monkeypatch):
    monkeypatch.setattr(settings, "testnet_rpc_url", "")
    with pytest.raises(vbv.BondVaultUnavailable, match="TESTNET_RPC_URL"):
        vbv.read_bonds_sync([WALLET])


def test_read_bonds_maps_an_rpc_error_to_unavailable_never_to_zero(monkeypatch):
    monkeypatch.setitem(sys.modules, "web3", _fake_web3_module(explode=True))
    with pytest.raises(vbv.BondVaultUnavailable):
        vbv.read_bonds_sync([WALLET])


def test_read_bonds_ignores_blank_wallets():
    assert vbv.read_bonds_sync(["", "   "]) == {}


# ---------------------------------------------------------------------------
# 2) \u72b6\u6001\u673a\uff1a\u516d\u79cd code\uff0c\u53ea\u6709 active \u7b97\u8fc7
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_vault_bond_state_reports_an_unconfigured_vault(db_session, monkeypatch):
    monkeypatch.setattr(settings, "verifier_bond_vault_address", "")
    state = await verifier_bond.vault_bond_state(
        db_session, identity_id=IDENTITY, stake_amount=5.0
    )
    assert state["code"] == "vault_unconfigured"
    assert state["ok"] is False


@pytest.mark.asyncio
async def test_vault_bond_state_requires_a_bound_wallet(db_session):
    state = await verifier_bond.vault_bond_state(
        db_session, identity_id="nobody", stake_amount=5.0
    )
    assert state["code"] == "no_wallet"
    assert state["ok"] is False


@pytest.mark.asyncio
async def test_vault_bond_state_is_active_only_when_the_chain_says_so(
    db_session, monkeypatch
):
    await _bind_wallet(db_session)
    monkeypatch.setitem(sys.modules, "web3", _fake_web3_module(_readings(bond=5.0)))
    state = await verifier_bond.vault_bond_state(
        db_session, identity_id=IDENTITY, stake_amount=5.0
    )
    assert state["code"] == "active" and state["ok"] is True
    assert state["onchain_bond_usdc"] == 5.0
    assert state["wallet"] == WALLET.lower()


@pytest.mark.asyncio
async def test_vault_bond_state_flags_a_wallet_with_no_stake(db_session, monkeypatch):
    await _bind_wallet(db_session)
    monkeypatch.setitem(
        sys.modules, "web3", _fake_web3_module(_readings(registered=False, active=False))
    )
    state = await verifier_bond.vault_bond_state(
        db_session, identity_id=IDENTITY, stake_amount=5.0
    )
    assert state["code"] == "not_registered"
    assert state["ok"] is False


@pytest.mark.asyncio
async def test_vault_bond_state_flags_a_short_bond(db_session, monkeypatch):
    await _bind_wallet(db_session)
    monkeypatch.setitem(sys.modules, "web3", _fake_web3_module(_readings(bond=4.0)))
    state = await verifier_bond.vault_bond_state(
        db_session, identity_id=IDENTITY, stake_amount=5.0
    )
    assert state["code"] == "below_bond"
    assert state["ok"] is False


@pytest.mark.asyncio
async def test_vault_bond_state_fails_closed_when_the_chain_is_unreachable(
    db_session, monkeypatch
):
    await _bind_wallet(db_session)

    async def _boom(*args, **kwargs):
        raise vbv.BondVaultUnavailable("rpc down")

    monkeypatch.setattr(vbv, "read_bond", _boom)
    state = await verifier_bond.vault_bond_state(
        db_session, identity_id=IDENTITY, stake_amount=5.0
    )
    assert state["code"] == "vault_unavailable"
    assert state["ok"] is False
    assert state["onchain_bond_usdc"] == 0.0, "unreadable must not be reported as a number"


# ---------------------------------------------------------------------------
# 3) \u5165\u6c60 / \u6295\u7968\u95f8\u95e8
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_pool_join_does_not_touch_the_chain_while_the_gate_is_off(
    db_session, monkeypatch
):
    """\u9ed8\u8ba4\u5173\u7740\uff1a\u4e0e\u5386\u53f2\u884c\u4e3a\u5b8c\u5168\u4e00\u81f4\uff08\u4e00\u6b21\u94fe\u4e0a\u8bfb\u90fd\u4e0d\u8be5\u53d1\u751f\uff09\u3002"""

    async def _must_not_be_called(*args, **kwargs):
        raise AssertionError("the vault must not be read while the gate is off")

    monkeypatch.setattr(vbv, "read_bond", _must_not_be_called)
    monkeypatch.setattr(settings, "arbitration_require_backed_stake", False)
    await arb_rules.assert_stake_acceptable(db_session, identity_id=IDENTITY, stake_amount=5.0)


@pytest.mark.asyncio
async def test_pool_join_requires_an_onchain_bond(db_session, monkeypatch):
    await _bind_wallet(db_session)
    monkeypatch.setattr(settings, "arbitration_require_vault_bond", True)
    monkeypatch.setattr(settings, "arbitration_require_backed_stake", False)
    monkeypatch.setitem(sys.modules, "web3", _fake_web3_module(_readings(bond=1.0)))
    with pytest.raises(HTTPException) as exc:
        await arb_rules.assert_stake_acceptable(
            db_session, identity_id=IDENTITY, stake_amount=5.0
        )
    assert exc.value.status_code == 409
    assert "on-chain bond" in exc.value.detail


@pytest.mark.asyncio
async def test_pool_join_passes_with_an_onchain_bond(db_session, monkeypatch):
    await _bind_wallet(db_session)
    monkeypatch.setattr(settings, "arbitration_require_vault_bond", True)
    monkeypatch.setattr(settings, "arbitration_require_backed_stake", False)
    monkeypatch.setitem(sys.modules, "web3", _fake_web3_module(_readings(bond=5.0)))
    await arb_rules.assert_stake_acceptable(db_session, identity_id=IDENTITY, stake_amount=5.0)


@pytest.mark.asyncio
async def test_the_vault_gate_is_independent_of_the_backed_stake_switch(
    db_session, monkeypatch
):
    """\u5173\u6389\u8d26\u9762\u80cc\u4e66\u4e0d\u80fd\u987a\u5e26\u628a\u94fe\u4e0a\u95f8\u95e8\u4e5f\u5173\u6389\u3002"""
    monkeypatch.setattr(settings, "arbitration_require_vault_bond", True)
    monkeypatch.setattr(settings, "arbitration_require_backed_stake", False)
    with pytest.raises(HTTPException) as exc:
        await arb_rules.assert_stake_acceptable(
            db_session, identity_id="nobody", stake_amount=5.0
        )
    assert exc.value.status_code == 409
    assert "no_wallet" in exc.value.detail


@pytest.mark.asyncio
async def test_vote_rechecks_the_onchain_bond(db_session, monkeypatch):
    db_session.add(
        ArbitrationPoolMemberModel(
            arbitrator_identity_id=IDENTITY, stake_amount=5.0, status="active"
        )
    )
    await db_session.commit()
    monkeypatch.setattr(settings, "arbitration_require_vault_bond", True)
    case_row = SimpleNamespace(task_id="task-with-no-settlement")
    with pytest.raises(HTTPException) as exc:
        await arb_rules.assert_arbitrator_covers_case(
            db_session, case_row=case_row, identity_id=IDENTITY, what="arbitration vote"
        )
    assert exc.value.status_code == 409
    assert "arbitration vote" in exc.value.detail


# ---------------------------------------------------------------------------
# 4) \u6307\u8ba4\uff1a/overturn \u8bb0\u771f\u5b9e\u94b1\u5305\uff0c\u7f5a\u6ca1\u8bf4\u660e\u624d\u53d1\u5f97\u51fa\u94fe\u4e0a tx
# ---------------------------------------------------------------------------
async def _seed_executed_case(db, *, case_id: str, task_id: str, case_value: float = 100.0):
    db.add(
        TaskContractModel(
            task_id=task_id,
            client_agent_id="buyer-agent",
            title="b1 overturn case",
            description="d",
            expected_output_schema={},
            expected_step_count=1,
            escrow_amount=case_value,
            deadline_at=datetime.utcnow() + timedelta(days=1),
        )
    )
    db.add(
        ArbitrationCaseModel(
            case_id=case_id,
            task_id=task_id,
            opened_by="buyer-agent",
            status="executed",
            required_arbitrators=3,
            decided_outcome="buyer_wins",
        )
    )
    db.add(
        ArbitrationAssignmentModel(case_id=case_id, arbitrator_identity_id=IDENTITY)
    )
    db.add(
        IdentityRoleProfile(
            owner_identity_id=IDENTITY,
            class_="arbitrator",
            kyc_status="verified",
            stake_amount=10.0,
        )
    )
    await db.commit()


@pytest.mark.asyncio
async def test_overturn_records_the_bound_wallet(client_sec, db_session, monkeypatch):
    monkeypatch.setattr(settings, "arbitration_slash_multiple", 2.0)
    await _seed_executed_case(db_session, case_id="case-b1-a", task_id="task-b1-a")
    await _bind_wallet(db_session)

    resp = await client_sec.post(
        "/v1/arbitration/cases/case-b1-a/overturn",
        json={"reason": "bench overturned", "victim_wallet_address": OTHER_WALLET},
    )
    assert resp.status_code == 200, resp.text

    rows = (await db_session.execute(select(BondSlash))).scalars().all()
    assert len(rows) == 1
    # 钱包大小写看身份里存的写法（testnet 就是混合大小写）—— 比对时不区分大小写。
    assert (rows[0].wallet_address or "").lower() == WALLET.lower(), "the slash must name a wallet"
    assert (rows[0].victim_wallet_address or "").lower() == OTHER_WALLET.lower()

    # \u53f0\u8d26 -> \u94fe\u4e0a\u8bf4\u660e\uff1a\u8fd9\u4e00\u6b65\u624d\u662f\u8d28\u62bc\u771f\u6b63\u53d8\u6210\u53ef\u6267\u884c\u7684\u94fe\u4e0a\u8bf4\u660e
    instructions = bond_slash.slash_instructions(rows)
    assert instructions and (instructions[0]["verifier"] or "").lower() == WALLET.lower()
    assert (instructions[0]["victim"] or "").lower() == OTHER_WALLET.lower()


@pytest.mark.asyncio
async def test_overturn_never_invents_a_wallet(client_sec, db_session, monkeypatch):
    monkeypatch.setattr(settings, "arbitration_slash_multiple", 2.0)
    await _seed_executed_case(db_session, case_id="case-b1-b", task_id="task-b1-b")

    resp = await client_sec.post(
        "/v1/arbitration/cases/case-b1-b/overturn",
        json={"reason": "bench overturned"},
    )
    assert resp.status_code == 200, resp.text

    rows = (await db_session.execute(select(BondSlash))).scalars().all()
    assert len(rows) == 1, "the liability is still recorded"
    assert rows[0].wallet_address is None, "no bound wallet -> no invented payee"
    assert rows[0].status == "pending"
    assert bond_slash.slash_instructions(rows)[0]["verifier"] is None
    with pytest.raises(ValueError, match="tx hash"):
        await bond_slash.settle_slash(
            db_session, slash_id=rows[0].id, status="settled"
        )


# ---------------------------------------------------------------------------
# 5) \u7f16\u7801\uff1astake \u4e0e slash \u540c\u4e00\u4e2a\u5c0f\u6570\u53e3\u5f84
# ---------------------------------------------------------------------------
def test_encode_stake_calldata_uses_the_uint256_selector():
    from eth_utils import keccak

    data = vbv.encode_stake_calldata(amount_usdc=150, vault_address=VAULT)
    assert data.startswith("0x" + keccak(text="stake(uint256)")[:4].hex())
    assert int(data[10:], 16) == 150_000_000


# ---------------------------------------------------------------------------
# 6) 出账回写：没有链上 tx 就不许写 settled
# ---------------------------------------------------------------------------
async def _pending_slash(db, *, source_id: str = "case-b1-c"):
    row, _ = await bond_slash.record_slash(
        db,
        subject_kind=bond_slash.SUBJECT_ARBITRATOR_ROLE,
        subject_id=IDENTITY,
        wallet_address=WALLET,
        victim_wallet_address=OTHER_WALLET,
        source_kind=bond_slash.SOURCE_ARBITRATION_OVERTURN,
        source_id=source_id,
        amount=3.0,
    )
    await db.commit()
    return row


def _proof(monkeypatch):
    async def _ok(tx_hash, **kwargs):
        return {"tx_hash": tx_hash, "vault": VAULT, "block": 123, "selector": vbv.SLASH_SELECTOR}

    monkeypatch.setattr(vbv, "verify_slash_tx", _ok)


@pytest.mark.asyncio
async def test_settled_needs_the_tx_hash(client_sec, db_session, monkeypatch):
    row = await _pending_slash(db_session)
    resp = await client_sec.post(
        f"/v1/verifiers/slashes/{row.id}/status", json={"status": "settled"}
    )
    assert resp.status_code == 422, resp.text
    assert (await db_session.get(BondSlash, row.id)).status == "pending"


@pytest.mark.asyncio
async def test_settled_requires_an_onchain_slash_tx(client_sec, db_session, monkeypatch):
    """手拄一个 tx hash：链上核不过 → 409，台账继续停 pending。"""

    async def _boom(tx_hash, **kwargs):
        raise vbv.BondVaultUnavailable("transaction is not mined yet")

    monkeypatch.setattr(vbv, "verify_slash_tx", _boom)
    row = await _pending_slash(db_session, source_id="case-b1-d")
    resp = await client_sec.post(
        f"/v1/verifiers/slashes/{row.id}/status",
        json={"status": "settled", "tx_hash": "0x" + "ab" * 32},
    )
    assert resp.status_code == 409, resp.text
    assert "could not be verified" in resp.text
    assert (await db_session.get(BondSlash, row.id)).status == "pending"


@pytest.mark.asyncio
async def test_settled_lands_when_the_chain_confirms_the_slash(
    client_sec, db_session, monkeypatch
):
    _proof(monkeypatch)
    row = await _pending_slash(db_session, source_id="case-b1-e")
    tx = "0x" + "cd" * 32
    resp = await client_sec.post(
        f"/v1/verifiers/slashes/{row.id}/status",
        json={"status": "settled", "tx_hash": tx},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "settled"
    assert body["tx_hash"] == tx
    assert body["settled_at"] is not None

    fresh = await db_session.get(BondSlash, row.id)
    await db_session.refresh(fresh)
    assert fresh.status == "settled" and fresh.tx_hash == tx


@pytest.mark.asyncio
async def test_submitted_and_failed_do_not_need_a_chain_check(
    client_sec, db_session, monkeypatch
):
    """没出账的中间态不该强制回链上读（链上还没有东西可读）。"""

    async def _must_not_be_called(*args, **kwargs):
        raise AssertionError("only 'settled' is verified on-chain")

    monkeypatch.setattr(vbv, "verify_slash_tx", _must_not_be_called)
    row = await _pending_slash(db_session, source_id="case-b1-f")
    resp = await client_sec.post(
        f"/v1/verifiers/slashes/{row.id}/status", json={"status": "submitted"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "submitted"


@pytest.mark.asyncio
async def test_status_writeback_requires_a_platform_admin(client, db_session):
    """没凭证：401/403。"""
    row = await _pending_slash(db_session, source_id="case-b1-g")
    resp = await client.post(
        f"/v1/verifiers/slashes/{row.id}/status", json={"status": "failed"}
    )
    assert resp.status_code in (401, 403), resp.text
    assert (await db_session.get(BondSlash, row.id)).status == "pending"


@pytest.mark.asyncio
async def test_status_writeback_is_admin_only_not_arbitrator(
    client_sec, db_session, monkeypatch
):
    """出账回写是**管理员**动作：只在仲裁员白名单里不够。"""
    monkeypatch.setattr(settings, "admin_actor_ids", "somebody-else")
    row = await _pending_slash(db_session, source_id="case-b1-h")
    resp = await client_sec.post(
        f"/v1/verifiers/slashes/{row.id}/status", json={"status": "failed"}
    )
    assert resp.status_code == 403, resp.text
    assert (await db_session.get(BondSlash, row.id)).status == "pending"


def test_verify_slash_tx_is_fail_closed_without_a_vault(monkeypatch):
    monkeypatch.setattr(settings, "verifier_bond_vault_address", "")
    with pytest.raises(vbv.BondVaultUnavailable, match="VERIFIER_BOND_VAULT_ADDRESS"):
        vbv.verify_slash_tx_sync("0x" + "ab" * 32)


def _verify_with(monkeypatch, *, status=1, to=VAULT, data=None):
    """用假链跑一遍 ``verify_slash_tx_sync``。"""
    tx_hash = "0x" + "ab" * 32
    monkeypatch.setitem(
        sys.modules,
        "web3",
        _fake_web3_module(
            receipt={"status": status, "to": to, "blockNumber": 4242},
            tx={"input": data if data is not None else (vbv.SLASH_SELECTOR + "00" * 64)},
        ),
    )
    return vbv.verify_slash_tx_sync(tx_hash)


def test_verify_slash_tx_accepts_a_real_slash_call(monkeypatch):
    proof = _verify_with(monkeypatch)
    assert proof["block"] == 4242
    assert proof["selector"] == vbv.SLASH_SELECTOR


@pytest.mark.parametrize(
    "kwargs, match",
    [
        ({"status": 0}, "reverted"),
        ({"to": OTHER_WALLET}, "not to the bond vault"),
        ({"data": "0xdeadbeef"}, "does not call slash"),
    ],
)
def test_verify_slash_tx_rejects_everything_else(monkeypatch, kwargs, match):
    with pytest.raises(vbv.BondVaultUnavailable, match=match):
        _verify_with(monkeypatch, **kwargs)
