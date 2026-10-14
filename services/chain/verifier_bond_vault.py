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

import asyncio
from collections.abc import Iterable
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
        "name": "stake",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "amount", "type": "uint256"}],
        "outputs": [],
    },
    {
        "type": "function",
        "name": "isRegistered",
        "stateMutability": "view",
        "inputs": [{"name": "verifier", "type": "address"}],
        "outputs": [{"name": "", "type": "bool"}],
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

# ---------------------------------------------------------------------------
# 只读：金库里到底押了多少钱（④-B1）
# ---------------------------------------------------------------------------


class BondVaultUnavailable(RuntimeError):
    """金库读不到（没配 / RPC 不通 / 合约调用失败）。

    绝不当成「余额 0」：把「读不到」当成「没质押」会在 RPC 抖动时误停一个合格的岗，
    当成「有质押」则会让没押金的人过关 —— 两种都错，所以只能抛，由调用方 fail-closed。
    """


def _configured_vault_address() -> str:
    """模块级助手：避开同名参数 ``vault_address`` 的遮蔽。"""
    from services import verifier_bond

    return verifier_bond.vault_address()


def _configured_rpc_url(explicit: str | None = None) -> str:
    """读链用的 RPC：显式参数 > ``VERIFIER_BOND_RPC_URL`` > ``TESTNET_RPC_URL``。

    与 ``scripts/ops/verifier_bond_vault.py`` 的 ``resolve_rpc`` 同一个顺序 —— 两个进程读链的口径
    不一样，运维时就会出现「脚本读得到、后端读不到」的鬼故事。
    """
    from config.settings import settings

    return (
        explicit or settings.verifier_bond_rpc_url or settings.testnet_rpc_url or ""
    ).strip()


def read_bonds_sync(
    wallets: Iterable[str],
    *,
    vault_address: str | None = None,
    rpc_url: str | None = None,
) -> dict[str, dict[str, Any]]:
    """批量读「这些钱包在金库里押了多少」。返回 ``{小写钱包: {...}}``。

    只读：不签名、不发交易。金额取链上 ``bondAmount``，**不接受调用方自报**。
    """
    address = (vault_address or _configured_vault_address() or "").strip()
    if not address:
        raise BondVaultUnavailable("VERIFIER_BOND_VAULT_ADDRESS is not configured")
    rpc = _configured_rpc_url(rpc_url)
    if not rpc:
        raise BondVaultUnavailable("TESTNET_RPC_URL is not configured")
    wanted = [w for w in ((w or "").strip().lower() for w in wallets) if w]
    if not wanted:
        return {}
    from web3 import Web3

    try:
        w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 20}))
        contract = w3.eth.contract(address=Web3.to_checksum_address(address), abi=VAULT_ABI)
        out: dict[str, dict[str, Any]] = {}
        for wallet in wanted:
            checksum = Web3.to_checksum_address(wallet)
            out[wallet] = {
                "wallet": wallet,
                "vault": address,
                "registered": bool(contract.functions.isRegistered(checksum).call()),
                "active": bool(contract.functions.isActive(checksum).call()),
                "bond_usdc": wei_to_amount(contract.functions.bondAmount(checksum).call()),
            }
        return out
    except BondVaultUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 - 转成一个明确的「查不清」，不让上层把它当成 0
        raise BondVaultUnavailable("bond vault read failed: %s" % exc) from exc


async def read_bonds(
    wallets: Iterable[str],
    *,
    vault_address: str | None = None,
    rpc_url: str | None = None,
) -> dict[str, dict[str, Any]]:
    """``read_bonds_sync`` 的非阻塞包装（链上读不占事件循环）。"""
    return await asyncio.to_thread(
        read_bonds_sync, list(wallets), vault_address=vault_address, rpc_url=rpc_url
    )


async def read_bond(
    wallet: str | None,
    *,
    vault_address: str | None = None,
    rpc_url: str | None = None,
) -> dict[str, Any] | None:
    """单钱包读取；没给钱包返回 ``None``（不去猜）。"""
    key = (wallet or "").strip().lower()
    if not key:
        return None
    return (await read_bonds([key], vault_address=vault_address, rpc_url=rpc_url)).get(key)



#: ``slash(address,address,uint256,bytes32)`` 的 4 字节选择器。
SLASH_SELECTOR = "0xa527f1dc"


def verify_slash_tx_sync(
    tx_hash: str,
    *,
    vault_address: str | None = None,
    rpc_url: str | None = None,
) -> dict[str, Any]:
    """回链上确认「这笔 tx 真的是本金库的一笔 slash()」。

    为什么不能只相信操作人的一个字符串：台账里的 ``settled`` 是对外声明「钱已经划过去了」。
    一个手拄的 tx hash 能把它变成谎言。所以这里要逐项核：

    1. 交易已上链且 ``status == 1``（没 revert）；
    2. ``to`` 就是当前配的金库；
    3. ``input`` 的选择器就是 ``slash(...)``。

    任一项查不到 / 不对 → 抛 ``BondVaultUnavailable``：宁可回写不了，也不写一个假的「已出账」。
    """
    address = (vault_address or _configured_vault_address() or "").strip()
    if not address:
        raise BondVaultUnavailable("VERIFIER_BOND_VAULT_ADDRESS is not configured")
    rpc = _configured_rpc_url(rpc_url)
    if not rpc:
        raise BondVaultUnavailable("TESTNET_RPC_URL is not configured")
    from web3 import Web3

    from services.chain.wallet_lock import _field

    try:
        w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 20}))
        receipt = w3.eth.get_transaction_receipt(tx_hash)
        if receipt is None:
            raise BondVaultUnavailable("transaction %s is not mined yet" % tx_hash)
        tx = w3.eth.get_transaction(tx_hash)
    except BondVaultUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001
        raise BondVaultUnavailable("could not read transaction %s: %s" % (tx_hash, exc)) from exc

    status = _field(receipt, "status", 0)
    if int(status or 0) != 1:
        raise BondVaultUnavailable("transaction %s reverted on-chain" % tx_hash)
    to = str(_field(receipt, "to", "") or "").strip().lower()
    if to != address.lower():
        raise BondVaultUnavailable(
            "transaction %s was sent to %s, not to the bond vault %s" % (tx_hash, to or "<none>", address)
        )
    data = str(_field(tx, "input", "") or "")
    if not data.lower().startswith(SLASH_SELECTOR):
        raise BondVaultUnavailable(
            "transaction %s does not call slash(address,address,uint256,bytes32)" % tx_hash
        )
    return {
        "tx_hash": tx_hash,
        "vault": address,
        "block": _field(receipt, "blockNumber"),
        "selector": SLASH_SELECTOR,
    }


async def verify_slash_tx(
    tx_hash: str,
    *,
    vault_address: str | None = None,
    rpc_url: str | None = None,
) -> dict[str, Any]:
    """``verify_slash_tx_sync`` 的非阻塞包装。"""
    return await asyncio.to_thread(
        verify_slash_tx_sync, tx_hash, vault_address=vault_address, rpc_url=rpc_url
    )


def encode_stake_calldata(*, amount_usdc: float, vault_address: str | None = None) -> str:
    """编码 ``stake(uint256)``：质押人用**自己的钱包**签这一笔。

    后端只编码，不签名 —— 与 ``slash`` / ``distributePool`` 同一条安全模型：
    后端全程不持有、不索取、不传输任何私钥。
    """
    data = _contract(vault_address).encode_abi("stake", args=[usdc_to_wei(amount_usdc)])
    return _to_calldata_hex(data)
