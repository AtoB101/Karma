# -*- coding: utf-8 -*-
"""链上质押金库的 calldata 编码器：口径只有一份，且两种 web3 返回形状都要吃下。

为什么单独钉这一条
------------------
`services/chain/verifier_bond_vault.encode_slash_calldata` 是「链下台账 -> 治理账户出账」
之间的桥。它此前写的是 `"0x" + data.hex()`，而 **web3 7+ 的 `encode_abi` 返回的是带 `0x`
的 `str`**（不是 `HexBytes`）—— 在后端/CI 装的 web3 8.0.0 上，一调用就
`AttributeError: 'str' object has no attribute 'hex'`。这条路径当时没有任何测试覆盖，
所以 CI 全绿也没拦住。这里补上：既钉「两种形状都吃下」，也钉「编出来的字节与链上真跑的
那两笔 tx 一模一样」。

锚点是 2026-10-11 在 Ethereum Sepolia 上真实出账的两笔交易（`stake(10) -> slash(6)` 与
`distributePool`）：入参固定，calldata 必须逐字节复现。任何人改了口径（小数位、理由哈希、
参数顺序、地址归一化）这条就会红。
"""
from __future__ import annotations

import pytest
from eth_utils import keccak
from hexbytes import HexBytes

from services.chain import verifier_bond_vault as vbv

VAULT = "0x8eBCF8668a6B54872A4e747d82dB152095B21027"
NODE = "0x1D147c9eefd9D1d4C4725700a05EDc6ca13975Cc"
VICTIM_A = "0x444b6E82249149D50D0F9ca49DCf7cdC3B73FFd6"
VICTIM_B = "0xEf3A7590E3b6528B07ffD5fa5CDe61Ccf857D5F4"
WINNER_B = "0xB151BbC65B18F81bd31198733CD129116b982a22"
ZERO = "0x" + "00" * 20

#: Sepolia tx 0x3cbcb6f6… 的 input：slash(node, victim_a, 6 mUSDC, keccak("G12 testnet first slash (challenge x)"))
SLASH_TX_INPUT = (
    "0xa527f1dc"
    "0000000000000000000000001d147c9eefd9d1d4c4725700a05edc6ca13975cc"
    "000000000000000000000000444b6e82249149d50d0f9ca49dcf7cdc3b73ffd6"
    "00000000000000000000000000000000000000000000000000000000005b8d80"
    "a094dd0415f6b1876ccdc088fb0e7db18a5b02b9220dabcf726e875998ea7b11"
)
#: Sepolia tx 0xb4c3a042… 的 input：distributePool([winner_b, victim_b], 1 mUSDC)
DISTRIBUTE_TX_INPUT = (
    "0x3e952cfa"
    "0000000000000000000000000000000000000000000000000000000000000040"
    "00000000000000000000000000000000000000000000000000000000000f4240"
    "0000000000000000000000000000000000000000000000000000000000000002"
    "000000000000000000000000b151bbc65b18f81bd31198733cd129116b982a22"
    "000000000000000000000000ef3a7590e3b6528b07ffd5fa5cde61ccf857d5f4"
)


def _selector(signature: str) -> str:
    return "0x" + keccak(text=signature)[:4].hex()


class _StubContract:
    """假 contract：只用来喂 ``encode_abi`` 的各种返回形状。"""

    def __init__(self, payload):
        self._payload = payload
        self.calls: list[tuple] = []

    def encode_abi(self, fn_name, args=None):
        self.calls.append((fn_name, args))
        return self._payload


# ---------------------------------------------------------------------------
# 1) 两种 web3 返回形状都要吃下（这就是当初漏出去的 bug）
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "payload, expected",
    [
        ("0xdeadbeef", "0xdeadbeef"),          # web3 7+：带 0x 的 str
        ("deadbeef", "0xdeadbeef"),            # 不带 0x 的 str
        (HexBytes(b"\xde\xad\xbe\xef"), "0xdeadbeef"),  # web3 6：HexBytes
        (b"\xde\xad\xbe\xef", "0xdeadbeef"),   # 裸 bytes
    ],
)
def test_to_calldata_hex_normalises_every_shape(payload, expected):
    assert vbv._to_calldata_hex(payload) == expected


def test_encode_slash_calldata_survives_a_str_from_encode_abi(monkeypatch):
    """web3 7+ 的 encode_abi 返回 str —— 过去这里会 AttributeError 炸掉。"""
    stub = _StubContract("0xdeadbeef")
    monkeypatch.setattr(vbv, "_contract", lambda address=None: stub)
    out = vbv.encode_slash_calldata(
        verifier=NODE, victim=VICTIM_A, amount_usdc=6, reason="x", vault_address=VAULT
    )
    assert out == "0xdeadbeef"
    assert stub.calls and stub.calls[0][0] == "slash"


def test_encode_distribute_pool_calldata_survives_a_str_from_encode_abi(monkeypatch):
    stub = _StubContract("0xfeedface")
    monkeypatch.setattr(vbv, "_contract", lambda address=None: stub)
    out = vbv.encode_distribute_pool_calldata(
        winners=[WINNER_B, VICTIM_B], amount_usdc=1, vault_address=VAULT
    )
    assert out == "0xfeedface"
    assert stub.calls and stub.calls[0][0] == "distributePool"


# ---------------------------------------------------------------------------
# 2) 与链上真跑的 tx 逐字节一致
# ---------------------------------------------------------------------------
def test_slash_calldata_reproduces_the_sepolia_outbound_tx():
    got = vbv.encode_slash_calldata(
        verifier=NODE,
        victim=VICTIM_A,
        amount_usdc=6,
        reason="G12 testnet first slash (challenge x)",
        vault_address=VAULT,
    )
    assert got.lower() == SLASH_TX_INPUT.lower()
    assert got.startswith(_selector("slash(address,address,uint256,bytes32)"))


def test_distribute_pool_calldata_reproduces_the_sepolia_outbound_tx():
    got = vbv.encode_distribute_pool_calldata(
        winners=[WINNER_B, VICTIM_B], amount_usdc=1, vault_address=VAULT
    )
    assert got.lower() == DISTRIBUTE_TX_INPUT.lower()
    assert got.startswith(_selector("distributePool(address[],uint256)"))


def test_slash_calldata_zero_fills_a_missing_victim():
    """没有可指认的受害方 -> 零地址，链上会把 80% 并入罚没池（与台账口径一致）。"""
    got = vbv.encode_slash_calldata(
        verifier=NODE, victim=None, amount_usdc=6, reason="x", vault_address=VAULT
    )
    assert got[10 + 64:10 + 128] == "0" * 64
    assert got[10:10 + 64] == NODE[2:].lower().rjust(64, "0")
    # 金额（第三个参数）= 6 * 10**6
    assert int(got[10 + 128:10 + 192], 16) == 6_000_000


# ---------------------------------------------------------------------------
# 3) 金库地址：显式传入优先；都没有则 fail-closed
# ---------------------------------------------------------------------------
def test_explicit_vault_address_is_used_without_touching_settings(monkeypatch):
    from services import verifier_bond

    monkeypatch.setattr(verifier_bond, "vault_address", lambda: "")
    out = vbv.encode_slash_calldata(
        verifier=NODE, victim=None, amount_usdc=1, reason="", vault_address=VAULT
    )
    assert out.startswith(_selector("slash(address,address,uint256,bytes32)"))


def test_encoding_without_any_vault_address_is_failed_closed(monkeypatch):
    from services import verifier_bond

    monkeypatch.setattr(verifier_bond, "vault_address", lambda: "")
    monkeypatch.delenv("VERIFIER_BOND_VAULT_ADDRESS", raising=False)
    with pytest.raises(RuntimeError, match="VERIFIER_BOND_VAULT_ADDRESS"):
        vbv.encode_slash_calldata(verifier=NODE, victim=None, amount_usdc=1, reason="")


def test_distribute_pool_rejects_an_empty_winner_list():
    with pytest.raises(ValueError):
        vbv.encode_distribute_pool_calldata(winners=[], amount_usdc=1, vault_address=VAULT)


def test_zero_address_constant_is_the_canonical_zero_word():
    assert vbv.ZERO_ADDRESS == ZERO