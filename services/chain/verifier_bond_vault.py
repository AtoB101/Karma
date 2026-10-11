"""链上质押金库（KarmaVerifierBond）的接口：只读 + 构造调用，**绝不签名**。

安全模型（与 services/chain/allowance_escrow.py 一致）
----------------------------------------------------
Karma 后端全程不持有、不索取、不传输任何私钥 / 助记词。所以这一层只做两件事：

1. 告诉上层「金库配了没有」—— 没配的时候，罚没台账停在 ``pending``（见
   services/bond_slash.py），不许伪装成已出账；
2. 把一笔罚没编码成链上调用（``encode_slash_calldata``），交给**治理账户**
   （多签 / 时间锁 / ops 脚本）去签、去发 —— 罚没是治理动作，不该由热钱包执行。

出账结果（tx hash / 状态）由 ops 侧回写 ``bond_slashes``。
"""
from __future__ import annotations

from typing import Any

from services import verifier_bond
from services.chain.wallet_lock import usdc_to_wei, wei_to_usdc

#: 只包含我们要用到的那几个函数的最小 ABI —— 够编码 calldata，不需要外部依赖。
VAULT_ABI: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "slash",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "verifier", "type": "address"},
            {"name": "victim", "type": "address"},
            {"name": "amount", "type": "uint256"},
            {"name": "reason", "type": "bytes32"},
        ],
        "outputs": [
            {"name": "victimAmount", "type": "uint256"},
            {"name": "poolAmount", "type": "uint256"},
        ],
    },
    {
        "type": "function",
        "name": "distributePool",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "winners", "type": "address[]"},
            {"name": "amount", "type": "uint256"},
        ],
        "outputs": [],
    },
    {
        "type": "function",
        "name": "slashPool",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "type": "function",
        "name": "totalBonded",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "type": "function",
        "name": "isActive",
        "stateMutability": "view",
        "inputs": [{"name": "verifier", "type": "address"}],
        "outputs": [{"name": "", "type": "bool"}],
    },
    {
        "type": "function",
        "name": "bondAmount",
        "stateMutability": "view",
        "inputs": [{"name": "verifier", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
]


def vault_configured() -> bool:
    return verifier_bond.vault_configured()


def vault_address() -> str | None:
    return verifier_bond.vault_address() or None


def reason_hash(reason: str | None) -> str:
    """把罚没理由打成链上 ``bytes32``（keccak256），便于事后对账。"""
    from eth_utils import keccak

    payload = (reason or "").encode("utf-8")
    digest = keccak(b"\0" if not payload else payload)
    return "0x" + digest.hex()


#: ``slash`` 没有可指认的受害方时，受害方参数传零地址（链上会把 80% 并入罚没池）。
ZERO_ADDRESS = "0x" + "00" * 20


def _to_calldata_hex(data: Any) -> str:
    """把 ``encode_abi`` 的结果统一成 ``0x…`` 字符串。

    web3 6 返回 ``HexBytes``，web3 7+ 返回**带 ``0x`` 的 ``str``**。只认其中一种的话，
    出账那一刻会以 ``AttributeError: 'str' object has no attribute 'hex'`` 炸掉 ——
    这条路径此前没有任何测试覆盖，正是这么漏出去的。
    """
    if isinstance(data, str):
        return data if data.startswith("0x") else "0x" + data
    return "0x" + bytes(data).hex()


def _contract(address: str | None = None) -> Any:
    from web3 import Web3

    address = (address or vault_address() or "").strip()
    if not address:
        raise RuntimeError(
            "VERIFIER_BOND_VAULT_ADDRESS is not configured — the bond vault is not deployed yet"
        )
    return Web3().eth.contract(address=Web3.to_checksum_address(address), abi=VAULT_ABI)


def encode_slash_calldata(
    *,
    verifier: str,
    victim: str | None,
    amount_usdc: float,
    reason: str | None,
    vault_address: str | None = None,
) -> str:
    """编码 ``slash(address,address,uint256,bytes32)`` 的 calldata。

    ``victim`` 为空时传零地址 —— 链上合约会把本该给受害方的部分也并入罚没池，
    与 ``services/bond_slash.py`` 的账目口径完全一致。

    ``vault_address`` 只用来建 contract 对象（地址不进 calldata），缺省取
    ``settings.verifier_bond_vault_address``；显式传入是为了让 ops 脚本能在
    ``--dry-run`` 时预览 calldata，而不必先把金库配进进程环境。
    """
    from web3 import Web3

    verifier_addr = Web3.to_checksum_address(verifier)
    victim_addr = Web3.to_checksum_address(victim) if victim else ZERO_ADDRESS
    data = _contract(vault_address).encode_abi(
        "slash",
        args=[verifier_addr, victim_addr, usdc_to_wei(amount_usdc), reason_hash(reason)],
    )
    return _to_calldata_hex(data)


def encode_distribute_pool_calldata(
    *,
    winners: list[str],
    amount_usdc: float,
    vault_address: str | None = None,
) -> str:
    """编码 ``distributePool(address[],uint256)``：把罚没池分给优秀节点。

    与 ``slash`` 同一套口径（同一份 ``VAULT_ABI``、同一个 6 位小数）。发之前是否已满足
    链上的 ``slashPool >= minPoolPayout``，由调用方自己先核对 —— 编码器不替人做判断。
    """
    from web3 import Web3

    if not winners:
        raise ValueError("distributePool 至少要有一个获奖地址")
    data = _contract(vault_address).encode_abi(
        "distributePool",
        args=[[Web3.to_checksum_address(w) for w in winners], usdc_to_wei(amount_usdc)],
    )
    return _to_calldata_hex(data)


def wei_to_amount(amount_wei: int) -> float:
    return wei_to_usdc(int(amount_wei))
