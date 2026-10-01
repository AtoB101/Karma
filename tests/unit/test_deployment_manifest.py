"""deployment-manifest.json 的自检。

清单本身是个「链上事实的声明」，声明错了比没有更糟 —— 没有的话人会去查链，声明错了
人会信它。所以形状、地址格式、绑定变量名、单测里全部钉住。

这里**不联网**：链上那一项归 scripts/acceptance/verify-manifest.sh --onchain 管。
"""

from __future__ import annotations

import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "deployment-manifest.json"
SCRIPT = ROOT / "scripts" / "acceptance" / "verify_manifest.py"


def _load():
    spec = importlib.util.spec_from_file_location("karma_verify_manifest", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


vm = _load()


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _shape(manifest):
    buf = io.StringIO()
    with redirect_stdout(buf):
        fails = vm.check_shape(manifest)
    return fails, buf.getvalue()


# --------------------------------------------------------------------------
# 仓库里这一份
# --------------------------------------------------------------------------


def test_manifest_parses_and_passes_shape_check():
    fails, output = _shape(_manifest())
    assert fails == 0, output


def test_manifest_pins_the_deployed_sepolia_addresses():
    contracts = _manifest()["contracts"]
    assert contracts["erc20_token"]["address"] == "0x6AF606f5B071BF649DC136fCd308ed0c9ADf38FF"
    assert contracts["bilateral"]["address"] == "0x496d178a5D32E9410E52bD5800602BDEe81B2A91"
    assert contracts["allowance_escrow"]["address"] == "0x65eb82058F4ea707B1a0aFb2A5872eb95076b6F2"
    assert contracts["settlement_operator"]["address"] == "0x1D147c9eefd9D1d4C4725700a05EDc6ca13975Cc"
    assert _manifest()["chain_id"] == 11155111


def test_settlement_operator_is_marked_as_an_eoa():
    # 它是钱包不是合约：链上本来就没有代码，写成 contract 会让链上核对永远红。
    entry = _manifest()["contracts"]["settlement_operator"]
    assert entry["kind"] == "eoa"


def test_manifest_never_contains_key_material():
    text = MANIFEST.read_text(encoding="utf-8").lower()
    for marker in ("private_key", "privkey", "mnemonic", "seed_phrase", "secret"):
        assert marker not in text, marker


# --------------------------------------------------------------------------
# 判据本身：坏的清单必须判红
# --------------------------------------------------------------------------


def test_shape_rejects_a_short_address():
    manifest = _manifest()
    manifest["contracts"]["bilateral"]["address"] = "0x496d178a"
    fails, output = _shape(manifest)
    assert fails == 1
    assert "bilateral" in output


def test_shape_rejects_a_duplicated_address():
    manifest = _manifest()
    manifest["contracts"]["allowance_escrow"]["address"] = manifest["contracts"]["bilateral"]["address"]
    fails, output = _shape(manifest)
    assert fails == 1
    assert "reuses the address" in output


def test_shape_rejects_an_unknown_kind():
    manifest = _manifest()
    manifest["contracts"]["bilateral"]["kind"] = "wallet"
    fails, output = _shape(manifest)
    assert fails == 1
    assert "kind" in output


def test_shape_rejects_a_bad_env_binding_name():
    manifest = _manifest()
    manifest["contracts"]["bilateral"]["env"] = "karma bilateral address"
    fails, output = _shape(manifest)
    assert fails == 1
    assert "env" in output


def test_shape_rejects_a_missing_chain_id():
    manifest = _manifest()
    manifest.pop("chain_id")
    fails, output = _shape(manifest)
    assert fails == 1
    assert "chain_id" in output


# --------------------------------------------------------------------------
# 环境比对
# --------------------------------------------------------------------------


def test_env_check_is_case_insensitive_on_addresses():
    manifest = _manifest()
    env = {entry["env"]: entry["address"].lower() for entry in manifest["contracts"].values()}
    env["TESTNET_CHAIN_ID"] = "11155111"
    fails, output = _env(manifest, env)
    assert fails == 0, output


def test_env_check_flags_a_different_address():
    manifest = _manifest()
    env = {entry["env"]: entry["address"] for entry in manifest["contracts"].values()}
    env["TESTNET_CHAIN_ID"] = "11155111"
    env["KARMA_BILATERAL_ADDRESS"] = "0x0000000000000000000000000000000000000001"
    fails, output = _env(manifest, env)
    assert fails == 1
    assert "KARMA_BILATERAL_ADDRESS" in output


def test_env_check_flags_a_different_chain_id():
    manifest = _manifest()
    env = {entry["env"]: entry["address"] for entry in manifest["contracts"].values()}
    env["TESTNET_CHAIN_ID"] = "1"
    fails, output = _env(manifest, env)
    assert fails == 1
    assert "TESTNET_CHAIN_ID" in output


def test_env_check_skips_variables_that_are_not_there():
    manifest = _manifest()
    fails, output = _env(manifest, {})
    assert fails == 0
    assert output.count("SKIP") == len(manifest["contracts"]) + 1


def _env(manifest, env):
    buf = io.StringIO()
    with redirect_stdout(buf):
        fails = vm.check_env(manifest, env)
    return fails, buf.getvalue()


# --------------------------------------------------------------------------
# 链上核对（这里用假的 rpc_call，不联网）
# --------------------------------------------------------------------------


def _fake_rpc(responses):
    def call(rpc_url, method, params, timeout=25):
        key = method
        if key not in responses:
            raise AssertionError("unexpected rpc call: %s %s" % (method, params))
        value = responses[key]
        return value(params) if callable(value) else value
    return call


def test_onchain_accepts_code_on_contracts_and_funds_on_the_eoa(monkeypatch):
    manifest = _manifest()
    monkeypatch.setattr(vm, "rpc_call", _fake_rpc({
        "eth_chainId": "0xaa36a7",
        "eth_getCode": lambda params: "0x" + "00" * 32,
        "eth_getBalance": "0x1bc16d674ec80000",
    }))
    buf = io.StringIO()
    with redirect_stdout(buf):
        fails = vm.check_onchain(manifest, "https://rpc.invalid")
    assert fails == 0, buf.getvalue()


def test_onchain_flags_a_contract_with_no_code(monkeypatch):
    manifest = _manifest()
    monkeypatch.setattr(vm, "rpc_call", _fake_rpc({
        "eth_chainId": "0xaa36a7",
        "eth_getCode": "0x",
        "eth_getBalance": "0x1bc16d674ec80000",
    }))
    buf = io.StringIO()
    with redirect_stdout(buf):
        fails = vm.check_onchain(manifest, "https://rpc.invalid")
    assert fails == 3  # 三个合约地址都没有代码
    assert "has no code" in buf.getvalue()


def test_onchain_flags_an_unfunded_operator_wallet(monkeypatch):
    manifest = _manifest()
    monkeypatch.setattr(vm, "rpc_call", _fake_rpc({
        "eth_chainId": "0xaa36a7",
        "eth_getCode": "0x" + "00" * 8,
        "eth_getBalance": "0x0",
    }))
    buf = io.StringIO()
    with redirect_stdout(buf):
        fails = vm.check_onchain(manifest, "https://rpc.invalid")
    assert fails == 1
    assert "0 wei" in buf.getvalue()


def test_onchain_flags_a_chain_id_mismatch(monkeypatch):
    manifest = _manifest()
    monkeypatch.setattr(vm, "rpc_call", _fake_rpc({
        "eth_chainId": "0x1",
        "eth_getCode": "0x" + "00" * 8,
        "eth_getBalance": "0x1bc16d674ec80000",
    }))
    buf = io.StringIO()
    with redirect_stdout(buf):
        fails = vm.check_onchain(manifest, "https://rpc.invalid")
    assert fails == 1
    assert "chain id mismatch" in buf.getvalue()


def test_unreachable_rpc_is_not_reported_as_a_mismatch(monkeypatch):
    monkeypatch.setattr(vm, "rpc_call", _fake_rpc({}))
    monkeypatch.setattr(vm, "load_manifest", lambda path: _manifest())
    monkeypatch.setattr(vm, "load_env", lambda cmd: {})
    monkeypatch.setattr(vm, "check_shape", lambda manifest: 0)

    def boom(rpc_url, method, params, timeout=25):
        raise vm.Unreachable("HTTP 503")

    monkeypatch.setattr(vm, "rpc_call", boom)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = vm.main(["--onchain", "--rpc", "https://rpc.invalid"])
    assert rc == 3
    assert "UNREACHABLE" in buf.getvalue()


def test_unreachable_rpc_does_not_hide_an_env_mismatch(monkeypatch):
    """链上探不到只是「这一项没查成」，已经查出来的不一致照样要判红。"""
    manifest = _manifest()
    env = {entry["env"]: entry["address"] for entry in manifest["contracts"].values()}
    env["TESTNET_CHAIN_ID"] = "11155111"
    env["KARMA_BILATERAL_ADDRESS"] = "0x0000000000000000000000000000000000000001"

    monkeypatch.setattr(vm, "load_manifest", lambda path: manifest)
    monkeypatch.setattr(vm, "load_env", lambda cmd: env)
    monkeypatch.setattr(vm, "check_shape", lambda m: 0)

    def boom(rpc_url, method, params, timeout=25):
        raise vm.Unreachable("HTTP 403")

    monkeypatch.setattr(vm, "rpc_call", boom)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = vm.main(["--onchain", "--rpc", "https://rpc.invalid"])
    assert rc == 1
    assert "KARMA_BILATERAL_ADDRESS" in buf.getvalue()
