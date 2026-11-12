#!/usr/bin/env python3
"""把 testnet 演练身份喂饱：测试币 + 对托管合约的 ERC-20 授权 + 链上承诺。

托管合约是**非托管**的：`commit()` 只把「我承担得起这笔钱」记在链上（`reserved`），
`bind()` 也只记责任，钱只在 `finalize*` 那一刻从买方钱包**直划**卖方。所以一条链上单
要能跑，缺一不可：

1. 买方/卖方钱包有测试币（`mUSDC`，Sepolia 上是可 mint 的测试代币）；
2. 两个钱包各自 `approve(托管合约)` —— `commit()` 会当场比 `allowance`；
3. 两个钱包各自签 `commit(token, amount, operator)` 产出一条链上账单；
4. 台账把这两条账单认到身份上（`claim_commit`，金额从链上读，客户端说了不算）；
5. 身份档案上有绑定钱包（`identity_profiles.bound_wallet_address`）——
   否则 `allowed_wallets()` 是空的，认领会被拒。

这个脚本把这五步一次做完，幂等可重跑。

用法::

    python3 scripts/seed_testnet_escrow_drill.py --amount 50 --stake 5
    python3 scripts/seed_testnet_escrow_drill.py --dry-run
    python3 scripts/seed_testnet_escrow_drill.py --identity a2a-buyer --party buyer

安全：**拒绝在 production 上跑**（`APP_ENV=production` 直接退出）。
私钥写在 ``<KEYS_DIR>/drill-<identity>.key``（0600），不进仓库。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

BUYER_IDENTITY = "a2a-buyer"
SELLER_IDENTITY = "a2a-seller"

_ERC20_ABI = [
    {"name": "approve", "inputs": [{"type": "address"}, {"type": "uint256"}],
     "outputs": [{"type": "bool"}], "stateMutability": "nonpayable", "type": "function"},
    {"name": "allowance", "inputs": [{"type": "address"}, {"type": "address"}],
     "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"name": "balanceOf", "inputs": [{"type": "address"}],
     "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"name": "mint", "inputs": [{"type": "address"}, {"type": "uint256"}],
     "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"name": "decimals", "inputs": [], "outputs": [{"type": "uint8"}],
     "stateMutability": "view", "type": "function"},
]

_ESCROW_ABI = [
    {"name": "commit", "inputs": [{"type": "address"}, {"type": "uint256"}, {"type": "address"}],
     "outputs": [{"type": "uint256"}], "stateMutability": "nonpayable", "type": "function"},
]


def _keys_dir() -> Path:
    return Path(os.environ.get("DRILL_KEYS_DIR") or (_ROOT / "karma_data" / "drill_keys"))


def _load_or_make_key(identity_id: str) -> str:
    """This identity's drill private key, created once and reused after that."""
    from eth_account import Account

    d = _keys_dir()
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"drill-{identity_id}.key"
    if p.exists():
        key = p.read_text(encoding="utf-8").strip()
        if not key.startswith("0x"):
            key = "0x" + key
        return key
    account = Account.create()
    p.write_text(account.key.hex(), encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return account.key.hex()


def _usdc_wei(amount: float, decimals: int) -> int:
    return round(float(amount) * (10 ** decimals))


class _Chain:
    """Thin sender: one place that signs and waits, so nothing here can double-send."""

    def __init__(self, w3, operator_key: str):
        from eth_account import Account

        self.w3 = w3
        self.operator = Account.from_key(operator_key)

    def send(self, fn, key: str, *, gas: int | None = None) -> tuple[str, object]:
        from eth_account import Account

        acct = Account.from_key(key)
        tx = fn.build_transaction({
            "from": acct.address,
            "nonce": self.w3.eth.get_transaction_count(acct.address),
            "chainId": self.w3.eth.chain_id,
            "maxFeePerGas": self.w3.to_wei(30, "gwei"),
            "maxPriorityFeePerGas": self.w3.to_wei(1, "gwei"),
            "value": 0,
            "type": 2,
        })
        tx["gas"] = gas or int(self.w3.eth.estimate_gas(tx) * 1.3)
        signed = acct.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
        if receipt.status != 1:
            raise SystemExit(f"{fn.fn_name} reverted (tx {tx_hash.hex()})")
        return tx_hash.hex(), receipt

    def send_value(self, to: str, wei: int, key: str) -> tuple[str, object]:
        """A plain ETH transfer - same signer/wait discipline as :meth:`send`."""
        from eth_account import Account

        acct = Account.from_key(key)
        dest = self.w3.to_checksum_address(to)
        value = int(wei)
        # 别拿 21000 硬编码：这类测试网上一笔「发到空地址」的转账实测要 ~205k gas
        # （Sepolia 上直接发 1 wei 给一个全新地址，收据里 gasUsed=204600），
        # 写死 21000 会以 out-of-gas 收场（status 0，gasUsed 恰好 21000）。
        estimate = self.w3.eth.estimate_gas(
            {"from": acct.address, "to": dest, "value": value}
        )
        tx = {
            "from": acct.address,
            "to": dest,
            "value": value,
            "nonce": self.w3.eth.get_transaction_count(acct.address),
            "chainId": self.w3.eth.chain_id,
            "maxFeePerGas": self.w3.to_wei(30, "gwei"),
            "maxPriorityFeePerGas": self.w3.to_wei(1, "gwei"),
            "gas": max(21000, int(estimate * 1.5)),
            "type": 2,
        }
        signed = acct.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
        if receipt.status != 1:
            raise SystemExit(f"value transfer reverted (tx {tx_hash.hex()})")
        return tx_hash.hex(), receipt


async def _register_identity(db, *, identity_id: str, wallet: str, dry_run: bool) -> str:
    """Point the ledger at this wallet: identity profile + runtime key row."""
    from db.models.orm import IdentityProfileModel, RuntimeKeyModel
    from services.identity_reputation import open_identity_ledger

    profile = await db.get(IdentityProfileModel, identity_id)
    if profile is None:
        profile = IdentityProfileModel(
            identity_id=identity_id,
            display_id=f"KARMA-DRILL-{identity_id.upper()[:8]}",
            legal_identity_status="unbound",
            status="active",
            bound_wallet_address=wallet,
            projection_readonly=False,
        )
        db.add(profile)
        action = "created"
    else:
        action = "kept" if (profile.bound_wallet_address or "").lower() == wallet.lower() else "rebound"
        if action == "rebound" and dry_run:
            return "would-rebind"
        profile.bound_wallet_address = wallet
    if not dry_run:
        await db.flush()
        await open_identity_ledger(db, identity_id)

    key = await db.get(RuntimeKeyModel, f"rt-{identity_id}")
    if key is not None and not dry_run:
        key.wallet_address = wallet
    return action


async def _amain(args) -> int:
    from eth_account import Account
    from web3 import Web3

    from config.settings import settings

    if (settings.app_env or "").strip().lower() in ("production", "prod"):
        print(f"refusing to run against production (APP_ENV={settings.app_env})")
        return 2
    from services.chain import allowance_escrow as escrow

    if not escrow.escrow_enabled():
        print(f"allowance escrow is not configured here: {escrow.disabled_detail()}")
        return 2

    w3 = Web3(Web3.HTTPProvider(settings.testnet_rpc_url, request_kwargs={"timeout": 30}))
    token_addr = w3.to_checksum_address(settings.erc20_token_address)
    escrow_addr = w3.to_checksum_address(escrow.configured_address())
    token = w3.eth.contract(address=token_addr, abi=_ERC20_ABI)
    escrow_c = w3.eth.contract(address=escrow_addr, abi=_ESCROW_ABI)
    decimals = int(token.functions.decimals().call())
    chain = _Chain(w3, (settings.settlement_operator_private_key or "").strip())
    operator_addr = chain.operator.address

    parties: list[tuple[str, float, str]] = []
    if args.party in ("both", "buyer"):
        parties.append((BUYER_IDENTITY, float(args.amount), "buyer"))
    if args.party in ("both", "seller"):
        parties.append((SELLER_IDENTITY, float(args.stake), "seller"))
    if args.identity:
        parties = [p for p in parties if p[0] == args.identity]
        if not parties:
            print(f"--identity {args.identity} is not one of the drilled parties")
            return 2

    print(f"venue      : APP_ENV={settings.app_env} chain={w3.eth.chain_id}")
    print(f"escrow     : {escrow_addr}")
    print(f"token      : {token_addr} (decimals={decimals})")
    print(f"operator   : {operator_addr}")
    print("parties    : " + ", ".join(f"{i}/{r}" for i, _a, r in parties))
    if args.dry_run:
        print("dry-run: nothing signed, nothing written")
        return 0

    from db.session import AsyncSessionLocal

    summary = []
    for identity_id, amount, role in parties:
        want_wei = _usdc_wei(amount, decimals)
        key = _load_or_make_key(identity_id)
        wallet = Account.from_key(key).address

        # 1. gas for the drill wallet's own two transactions.
        #    额度别抠：节点算 ``eth_estimateGas`` 时会把搜索上限压到
        #    ``余额 / maxFeePerGas``，钱包里钱太少 → 估出来的 gas 被截断 →
        #    一笔其实只需要 ~20k 的 approve 会以「gas required exceeds
        #    allowance」报错（实测 0.02 ETH / 30 gwei = 只能估到 662379）。
        #    0.3 ETH 把上限抬到千万级，链上完事还能退回来。
        target_gas = w3.to_wei(args.gas_eth, "ether")
        have_gas = w3.eth.get_balance(wallet)
        if have_gas < target_gas // 2:
            chain.send_value(wallet, target_gas - have_gas, chain.operator.key.hex())
        # 2. test tokens
        have = token.functions.balanceOf(wallet).call()
        if have < want_wei:
            chain.send(token.functions.mint(wallet, want_wei - have), chain.operator.key.hex())
        # 3. ERC-20 allowance to the escrow (commit() checks this on the spot)
        if token.functions.allowance(wallet, escrow_addr).call() < want_wei:
            chain.send(token.functions.approve(escrow_addr, want_wei), key)
        # 4. the on-chain commitment (owner-signed)
        before_allow = token.functions.allowance(wallet, escrow_addr).call()
        if before_allow < want_wei:
            raise SystemExit(f"allowance still short for {identity_id}")
        tx_hash, receipt = chain.send(
            escrow_c.functions.commit(token_addr, want_wei, operator_addr), key
        )
        # 5. ledger: bind wallet + credit the bill (amount read from chain)
        async with AsyncSessionLocal() as db:
            action = await _register_identity(db, identity_id=identity_id, wallet=wallet, dry_run=False)
            row = await escrow.claim_commit(
                db, identity_id=identity_id, tx_hash=tx_hash, wallets={wallet.lower()}
            )
            await escrow.reconcile_capacity_mirror(db, identity_id)
            await db.commit()
            bill_id = row.bill_id
            committed = float(row.amount_usdc)
        summary.append({
            "identity": identity_id, "role": role, "wallet": wallet,
            "bill_id": bill_id, "committed_usdc": committed,
            "commit_tx": tx_hash, "profile": action,
            "gas_wei": int(receipt.gasUsed),
        })
        print(
            f"  {identity_id:<12} wallet={wallet} bill={bill_id} "
            f"committed={committed:.6f} ({action})"
        )

    print()
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="seed testnet escrow drill identities")
    p.add_argument("--identity", default=None, help="only this identity (a2a-buyer / a2a-seller)")
    p.add_argument("--party", default="both", choices=["both", "buyer", "seller"])
    p.add_argument("--amount", default="50", help="buyer commitment in USDC")
    p.add_argument("--stake", default="5", help="seller stake in USDC")
    p.add_argument("--gas-eth", default="0.3", help="ETH to top the drill wallet up to")
    p.add_argument("--dry-run", action="store_true")
    return asyncio.run(_amain(p.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
