# -*- coding: utf-8 -*-
"""scripts/ops/verifier_bond_vault.py：编码口径与后端一致 + 不泄密 + 参数 fail-closed。

这 CLI 能把治理动作（罚没 / 分池）真签出去，所以钉三件事：

1. 它编出的 ``slash`` calldata 必须和后端 ``services.chain.verifier_bond_vault`` 用的是
   同一份 ABI、同一套理由哈希、同一个小数位 —— 链下台账和链上分账看同一串数据，
   不允许有第二份实现；
2. 私钥绝不进 stdout / stderr（dry-run 会打印参数，也不能把密钥带出来）；
3. 参数错就 fail-closed（退出码 2 / 3），而不是猜个默认值发出去。

全部离线：只跑 ``--dry-run`` 与纯函数，不连 RPC、不发交易。
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

from services import verifier_bond
from services.chain.verifier_bond_vault import VAULT_ABI, reason_hash
from services.chain.wallet_lock import usdc_to_wei

ROOT = pathlib.Path(__file__).resolve().parents[2]
CLI_PATH = ROOT / "scripts" / "ops" / "verifier_bond_vault.py"

VAULT = "0x8eBCF8668a6B54872A4e747d82dB152095B21027"
VERIFIER = "0x1D147c9eefd9D1d4C4725700a05EDc6ca13975Cc"
VICTIM = "0xB151BbC65B18F81bd31198733CD129116b982a22"
WINNER_B = "0xEf3A7590E3b6528B07ffD5fa5CDe61Ccf857D5F4"
ZERO = "0x0000000000000000000000000000000000000000"
#: 只用来说明「密钥不会被打出来」的假钥匙，不指向任何真实账户。
DUMMY_KEY = "0x" + "11" * 32

_cli = None


def _load_cli():
    global _cli
    if _cli is None:
        spec = importlib.util.spec_from_file_location("ops_verifier_bond_vault", CLI_PATH)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        _cli = module
    return _cli


def _encode(abi, fn, args):
    from web3 import Web3

    data = Web3().eth.contract(address=VAULT, abi=abi).encode_abi(fn, args=args)
    return data if data.startswith("0x") else "0x" + data


def _selector(signature: str) -> str:
    from eth_utils import keccak

    return "0x" + keccak(text=signature)[:4].hex()


# ---------------------------------------------------------------------------
# 编码口径
# ---------------------------------------------------------------------------
def test_slash_dry_run_calldata_matches_backend_abi(capsys):
    rc = _load_cli().main([
        "slash", "--vault", VAULT, "--dry-run",
        "--verifier", VERIFIER, "--amount", "6", "--victim", VICTIM,
        "--reason", "challenge 42 upheld",
    ])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    expected = _encode(
        VAULT_ABI,
        "slash",
        [VERIFIER, VICTIM, usdc_to_wei(6), reason_hash("challenge 42 upheld")],
    )
    assert payload["calldata"] == expected
    assert payload["calldata"].startswith(_selector("slash(address,address,uint256,bytes32)"))
    assert payload["to"].lower() == VAULT.lower()
    assert payload["amount_wei"] == 6_000_000
    assert payload["broadcast"] == "skipped (dry-run)"


def test_slash_without_victim_zero_fills_the_victim_word(capsys):
    rc = _load_cli().main([
        "slash", "--vault", VAULT, "--dry-run", "--verifier", VERIFIER, "--amount", "6",
    ])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["victim"] == ZERO
    expected = _encode(VAULT_ABI, "slash", [VERIFIER, ZERO, usdc_to_wei(6), reason_hash("")])
    assert payload["calldata"] == expected
    # 第二个参数（victim）整字为零。
    assert payload["calldata"][10 + 64:10 + 128] == "0" * 64


def test_slash_need_not_know_the_vault_for_a_dry_run(capsys, monkeypatch):
    """没配金库时 dry-run 仍应给出 calldata（用零地址占位），只是标不出 to。"""
    monkeypatch.setattr(verifier_bond, "vault_address", lambda: "")
    rc = _load_cli().main(["slash", "--dry-run", "--verifier", VERIFIER, "--amount", "6"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["to"] == "<VERIFIER_BOND_VAULT_ADDRESS>"
    assert payload["calldata"] == _encode(
        VAULT_ABI, "slash", [VERIFIER, ZERO, usdc_to_wei(6), reason_hash("")]
    )


def test_distribute_dry_run_encodes_and_dedups_winners(capsys):
    rc = _load_cli().main([
        "distribute", "--vault", VAULT, "--dry-run",
        "--winners", "%s,%s,%s" % (VICTIM, WINNER_B, VICTIM), "--amount", "1",
    ])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["winners"] == [VICTIM, WINNER_B], "重复地址要丢掉"
    expected = _encode(VAULT_ABI, "distributePool", [[VICTIM, WINNER_B], usdc_to_wei(1)])
    assert payload["calldata"] == expected
    assert payload["calldata"].startswith(_selector("distributePool(address[],uint256)"))


# ---------------------------------------------------------------------------
# 不泄密
# ---------------------------------------------------------------------------
def test_cli_never_prints_the_signing_key(capsys, monkeypatch):
    monkeypatch.setenv("VERIFIER_BOND_OPS_PRIVATE_KEY", DUMMY_KEY)
    rc = _load_cli().main([
        "slash", "--vault", VAULT, "--dry-run",
        "--verifier", VERIFIER, "--amount", "6", "--victim", VICTIM,
    ])
    captured = capsys.readouterr()
    assert rc == 0
    blob = captured.out + captured.err
    assert DUMMY_KEY not in blob
    assert DUMMY_KEY[2:] not in blob
    assert "1111111111111111" not in blob


def test_deploy_dry_run_never_connects_and_hides_the_key(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("VERIFIER_BOND_OPS_PRIVATE_KEY", DUMMY_KEY)
    artifact = tmp_path / "KarmaVerifierBond.json"
    artifact.write_text(json.dumps({"abi": VAULT_ABI, "bytecode": "0x6000"}), encoding="utf-8")
    rc = _load_cli().main([
        "deploy", "--dry-run",
        # 明显连不上的 RPC：dry-run 若去连了，这条就会以退出码 3 失败。
        "--rpc", "http://127.0.0.1:1",
        "--artifact", str(artifact),
        "--token", "0x6AF606f5B071BF649DC136fCd308ed0c9ADf38FF",
        "--min-bond", "5", "--cooldown-hours", "72", "--min-pool-payout", "1",
    ])
    captured = capsys.readouterr()
    assert rc == 0
    payload = json.loads(captured.out)
    assert payload["min_bond_wei"] == 5_000_000
    assert payload["unbond_cooldown_seconds"] == 259_200
    assert payload["min_pool_payout_wei"] == 1_000_000
    assert payload["broadcast"] == "skipped (dry-run)"
    assert DUMMY_KEY not in captured.out + captured.err


# ---------------------------------------------------------------------------
# fail-closed
# ---------------------------------------------------------------------------
def test_slash_rejects_a_nonpositive_amount(capsys):
    rc = _load_cli().main([
        "slash", "--vault", VAULT, "--dry-run", "--verifier", VERIFIER, "--amount", "0",
    ])
    captured = capsys.readouterr()
    assert rc == 2
    assert "必须 > 0" in captured.err
    assert captured.out == "", "参数错时不该往 stdout 打任何东西"


def test_slash_rejects_a_garbage_verifier(capsys):
    rc = _load_cli().main([
        "slash", "--vault", VAULT, "--dry-run", "--verifier", "not-an-address", "--amount", "6",
    ])
    assert rc == 2
    assert "不是合法地址" in capsys.readouterr().err


def test_slash_requires_a_key_before_broadcasting(capsys, monkeypatch):
    """不是 dry-run 又没有密钥：退出码 3，且绝不从别处兜底取密钥。"""
    monkeypatch.delenv("VERIFIER_BOND_OPS_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("SETTLEMENT_OPERATOR_PRIVATE_KEY", raising=False)
    rc = _load_cli().main([
        "slash", "--vault", VAULT, "--rpc", "http://127.0.0.1:1",
        "--verifier", VERIFIER, "--amount", "6",
    ])
    assert rc == 3
    assert "VERIFIER_BOND_OPS_PRIVATE_KEY" in capsys.readouterr().err


def test_deploy_needs_token_and_artifact(capsys):
    cli = _load_cli()
    assert cli.main(["deploy", "--dry-run"]) == 2
    assert "artifact" in capsys.readouterr().err
    assert cli.main(["deploy", "--dry-run", "--artifact", "nope.json"]) == 2
    assert "--token" in capsys.readouterr().err


def test_status_without_a_configured_vault_is_failed_closed(capsys, monkeypatch):
    monkeypatch.setattr(verifier_bond, "vault_address", lambda: "")
    rc = _load_cli().main(["status"])
    assert rc == 3
    assert "金库" in capsys.readouterr().err


def test_status_dry_run_reports_the_resolved_vault(capsys):
    rc = _load_cli().main(["status", "--vault", VAULT, "--dry-run"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["vault"] == VAULT
    assert payload["chain_read"] == "skipped (dry-run)"


# ---------------------------------------------------------------------------
# 纯函数
# ---------------------------------------------------------------------------
def test_parse_addresses_checksums_and_dedups():
    cli = _load_cli()
    lower = WINNER_B.lower()
    out = cli.parse_addresses("%s,%s" % (lower, WINNER_B))
    assert out == [WINNER_B], "大小写不同的同一个地址要去重成 checksum 形式"


@pytest.mark.parametrize("text", ["", "   ", ",,", "0x1234", "hello"])
def test_parse_addresses_rejects_bad_input(text):
    cli = _load_cli()
    with pytest.raises(cli.UsageError):
        cli.parse_addresses(text)


def test_usdc_to_wei_uses_six_decimals():
    cli = _load_cli()
    assert cli.usdc_to_wei(1) == 1_000_000
    assert cli.usdc_to_wei(0.5) == 500_000


# ---------------------------------------------------------------------------
# 广播路径：建交易必须带 from
# ---------------------------------------------------------------------------
from types import SimpleNamespace

from hexbytes import HexBytes

TOKEN = "0x6AF606f5B071BF649DC136fCd308ed0c9ADf38FF"
STAKE_WALLET = "0x9C479392C27ac5f44cBF50ceB2f099aDD665475f"
TX_HASH = HexBytes("0x" + "ab" * 32)


class _ViewFn:
    """只读调用：``fn(x).call()``。"""

    def __init__(self, value):
        self._value = value

    def call(self):
        return self._value


class _WriteFn:
    """写调用：记录 build_transaction 的入参。"""

    def __init__(self, name, built):
        self._name = name
        self._built = built

    def build_transaction(self, overrides):
        self._built.append((self._name, dict(overrides)))
        return {"to": VAULT, "data": "0xdead"}


class _Fns:
    def __init__(self, built, values):
        self._built = built
        self._values = values

    def __getattr__(self, name):
        if name in self._values:
            value = self._values[name]

            def _view(*_args):
                return _ViewFn(value)

            return _view

        def _write(*_args):
            return _WriteFn(name, self._built)

        return _write


class _Contract:
    def __init__(self, built, values):
        self.functions = _Fns(built, values)


class _Receipt(dict):
    """web3 的回执既能下标取，也能点取（``receipt.status``）。"""

    def __getattr__(self, name):
        return self[name]


class _Eth:
    chain_id = 11155111
    gas_price = 1_000_000_000

    def __init__(self, built, signed):
        self._built = built
        self._signed = signed

    def contract(self, address=None, abi=None, **_kw):
        if address == TOKEN:
            return _Contract(self._built, {"allowance": 0})
        return _Contract(
            self._built,
            {"bondAmount": 10_000_000, "isRegistered": True, "isActive": True},
        )

    def get_transaction_count(self, _address):
        return 5

    def estimate_gas(self, _tx):
        return 60_000

    def send_raw_transaction(self, _raw):
        return TX_HASH

    def wait_for_transaction_receipt(self, _tx_hash, timeout=None):
        return _Receipt(status=1, gasUsed=55_000, blockNumber=11915205)


def _stake_rig(monkeypatch, cli):
    built, signed = [], []

    def _sign(tx):
        signed.append(dict(tx))
        return SimpleNamespace(raw_transaction=b"\x02")

    w3 = SimpleNamespace(eth=_Eth(built, signed))
    signer = SimpleNamespace(address=STAKE_WALLET, sign_transaction=_sign)
    monkeypatch.setattr(cli, "_connect", lambda _rpc: w3)
    monkeypatch.setattr(cli, "_signer", lambda _key_env, _env: signer)
    return built, signed


def test_stake_broadcasts_with_the_signer_as_from(capsys, monkeypatch):
    """不带 from 的话 web3 会拿零地址估算 gas，approve / stake 会在估算处就 revert。"""
    cli = _load_cli()
    built, signed = _stake_rig(monkeypatch, cli)
    rc = cli.main([
        "stake", "--vault", VAULT, "--token", TOKEN, "--amount", "10",
        "--key-env", "DRILL_SELLER_KEY", "--rpc", "http://127.0.0.1:1",
    ])
    captured = capsys.readouterr()
    assert rc == 0
    assert [name for name, _ in built] == ["approve", "stake"]
    for name, overrides in built:
        assert overrides.get("from") == STAKE_WALLET, name
    assert [tx["from"] for tx in signed] == [STAKE_WALLET, STAKE_WALLET]
    assert "stake_tx=%s" % TX_HASH.hex() in captured.out
    assert "bond_amount_wei=10000000" in captured.out


def test_cli_builds_every_transaction_through_the_from_helper():
    """源码守卫：只允许一个 build_transaction 调用点，且必须带 from。"""
    lines = [
        line.strip()
        for line in CLI_PATH.read_text(encoding="utf-8").splitlines()
        if "build_transaction(" in line
    ]
    assert lines == ['return fn.build_transaction({"from": signer.address})']
