#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Karma 验证者质押金库（KarmaVerifierBond / G12）运维 CLI。

定位
----
把「金库部署 + 链上状态核对 + 治理动作签名」这三件**必须由人 / ops 账户执行**的事
收成一条可审、可测的命令，替掉一次性写在 /tmp 里的脚本。测试网先把钱真动一次、
跑稳了再谈主网 —— 主网未动。

安全边界（与 services/chain/verifier_bond_vault.py 同口径）
----------------------------------------------------------
* 密钥只从环境变量读（默认 ``VERIFIER_BOND_OPS_PRIVATE_KEY``），**永不打印、永不落盘、
  永不回传**；输出里只有地址、tx hash、gas、余额这类公开量。
* 只做两件事：把状态**读**出来（``status``，只读、不需要密钥），把一笔治理动作
  （``deploy`` / ``slash`` / ``distribute``）**签出去**（需要密钥）。
* 罚没是治理动作：生产里 ``admin`` / ``slasher`` 必须是多签合约 —— 部署脚本
  ``karma-core/contracts/script/DeployKarmaVerifierBond.s.sol`` 有主网守卫（admin /
  slasher 是 EOA 就 revert）。本 CLI 是测试网 / 演练用的执行手，不是主网治理通道。
* 罚没 calldata 复用 ``services.chain.verifier_bond_vault.encode_slash_calldata`` ——
  链下台账与链上分账看的是同一串数据，不另起一份实现。
* ``--dry-run`` 只打印将要发的内容，不广播、不碰链 —— 上线前先看一眼要发什么。

用法（在装了 web3 + eth-account 的环境，如 karma-api 容器里）::

  python scripts/ops/verifier_bond_vault.py status --address 0xNode
  python scripts/ops/verifier_bond_vault.py slash --dry-run \
      --verifier 0xNode --amount 6 --victim 0xVictim --reason "challenge 42 upheld"
  python scripts/ops/verifier_bond_vault.py deploy --dry-run \
      --artifact out/KarmaVerifierBond.json --token 0xToken \
      --min-bond 5 --cooldown-hours 72 --min-pool-payout 1

退出码：0 成功 / 2 参数用法错误 / 3 环境或链上失败。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# 允许直接 ``python scripts/ops/verifier_bond_vault.py``：脚本目录进的是 sys.path[0]，
# ``import services`` 会找不到仓库里的包 —— 把仓库根补回 sys.path。
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_FAILED = 3

DEFAULT_KEY_ENV = "VERIFIER_BOND_OPS_PRIVATE_KEY"
DEPLOY_GAS_CEILING = 12_000_000
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

#: ``status`` 读的全量视图函数名 —— 只有 ABI 里真的有的才会读。
VIEW_FUNCTIONS = (
    "admin",
    "slasher",
    "token",
    "minBond",
    "unbondCooldown",
    "minPoolPayout",
    "victimShareBps",
    "totalBonded",
    "slashPool",
    "solvencyGap",
)
PER_ADDRESS_FUNCTIONS = ("bondAmount", "isActive", "isRegistered")
AMOUNT_FUNCTIONS = frozenset(
    {"minBond", "minPoolPayout", "totalBonded", "slashPool", "bondAmount"}
)


class UsageError(RuntimeError):
    """参数用错了 —— 退出码 2，不发交易。"""


class CliError(RuntimeError):
    """环境 / 链上失败 —— 退出码 3，不发交易。"""


# ---------------------------------------------------------------------------
# 纯函数（可离线单测，不碰网络、不碰密钥）
# ---------------------------------------------------------------------------
def parse_addresses(text: str) -> list[str]:
    """逗号分隔的地址 -> 去重后的 checksum 列表（保留顺序）。空 = 用法错误。"""
    from web3 import Web3

    out: list[str] = []
    seen: set[str] = set()
    for part in (text or "").split(","):
        candidate = part.strip()
        if not candidate:
            continue
        try:
            address = Web3.to_checksum_address(candidate)
        except Exception as exc:  # noqa: BLE001
            raise UsageError("不是合法地址：%r（%s）" % (candidate, exc)) from exc
        if address not in seen:
            seen.add(address)
            out.append(address)
    if not out:
        raise UsageError("至少要有一个地址")
    return out


def usdc_to_wei(amount_usdc: float) -> int:
    """USDC（6 位小数）人读值 -> 链上最小单位。复用 wallet_lock，不另定小数位。"""
    from services.chain.wallet_lock import usdc_to_wei as _convert

    return int(_convert(amount_usdc))


def _require_positive(label: str, value: float) -> float:
    if value is None or float(value) <= 0:
        raise UsageError("%s 必须 > 0（给的 %r）" % (label, value))
    return float(value)


# ---------------------------------------------------------------------------
# 环境解析
# ---------------------------------------------------------------------------
def resolve_rpc(args, env: dict[str, str]) -> str:
    rpc = (
        (getattr(args, "rpc", None) or "").strip()
        or (env.get("VERIFIER_BOND_RPC_URL") or "").strip()
        or (env.get("TESTNET_RPC_URL") or "").strip()
    )
    if not rpc:
        raise CliError("没给 RPC：用 --rpc，或设 TESTNET_RPC_URL / VERIFIER_BOND_RPC_URL")
    return rpc


def resolve_vault_address(args) -> str | None:
    explicit = (getattr(args, "vault", None) or "").strip()
    if explicit:
        from web3 import Web3

        return Web3.to_checksum_address(explicit)
    from services import verifier_bond

    return verifier_bond.vault_address() or None


def _connect(rpc: str):
    from web3 import Web3

    w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 90}))
    if not w3.is_connected():
        raise CliError("RPC 连不上：%s" % rpc)
    return w3


def _signer(key_env: str, env: dict[str, str]):
    from eth_account import Account

    raw = (env.get(key_env) or "").strip()
    if not raw:
        raise CliError(
            "环境变量 %s 里没有私钥 —— 本 CLI 不从别处兜底取密钥（fail-closed）" % key_env
        )
    try:
        return Account.from_key(raw)
    except Exception as exc:  # noqa: BLE001
        raise CliError("环境变量 %s 里的私钥不可用：%s" % (key_env, exc)) from exc


def _load_artifact(path: str) -> tuple[list, str]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise CliError("读不到 artifact：%s（%s）" % (path, exc)) from exc
    except ValueError as exc:
        raise CliError("artifact 不是合法 JSON：%s（%s）" % (path, exc)) from exc
    abi = data.get("abi")
    bytecode = data.get("bytecode")
    if isinstance(bytecode, dict):
        bytecode = bytecode.get("object")
    if not abi or not isinstance(bytecode, str) or not bytecode.startswith("0x"):
        raise CliError(
            "artifact 里没有可用的 abi / bytecode —— 指向 forge build 产出的 .json"
        )
    return abi, bytecode


def _vault_abi(args) -> tuple[list, str]:
    artifact = getattr(args, "artifact", None)
    if artifact:
        abi, _ = _load_artifact(artifact)
        return abi, "artifact"
    from services.chain.verifier_bond_vault import VAULT_ABI

    return list(VAULT_ABI), "services-minimal"


def _available(abi: list, names) -> list[str]:
    present = {entry.get("name") for entry in abi if entry.get("type") == "function"}
    return [name for name in names if name in present]


def _send(w3, signer, tx: dict, *, gas: int | None = None):
    """签 + 发 + 等回执；revert 一律抛 CliError，绝不吞。"""
    tx = dict(tx)
    tx["from"] = signer.address
    tx["nonce"] = w3.eth.get_transaction_count(signer.address)
    tx["chainId"] = w3.eth.chain_id
    if gas:
        tx["gas"] = int(gas)
    else:
        try:
            tx["gas"] = int(w3.eth.estimate_gas(tx) * 1.2) + 1
        except Exception as exc:  # noqa: BLE001
            raise CliError("gas 估算失败（交易多半会 revert）：%s" % exc) from exc
    if "gasPrice" not in tx and "maxFeePerGas" not in tx:
        tx["gasPrice"] = w3.eth.gas_price
    signed = signer.sign_transaction(tx)
    raw = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction")
    tx_hash = w3.eth.send_raw_transaction(raw)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
    if receipt.status != 1:
        raise CliError("交易被 revert：%s" % tx_hash.hex())
    return tx_hash.hex(), receipt


# ---------------------------------------------------------------------------
# 子命令
# ---------------------------------------------------------------------------
def cmd_status(args, env) -> int:
    address = resolve_vault_address(args)
    if not address:
        raise CliError("没配金库：用 --vault，或设 VERIFIER_BOND_VAULT_ADDRESS")
    abi, abi_source = _vault_abi(args)
    if args.dry_run:
        print(
            json.dumps(
                {
                    "vault": address,
                    "abi": abi_source,
                    "chain_read": "skipped (dry-run)",
                    "rpc": (args.rpc or env.get("VERIFIER_BOND_RPC_URL")
                            or env.get("TESTNET_RPC_URL") or None),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return EXIT_OK

    w3 = _connect(resolve_rpc(args, env))
    contract = w3.eth.contract(address=address, abi=abi)
    state: dict[str, object] = {}
    for name in _available(abi, VIEW_FUNCTIONS):
        value = getattr(contract.functions, name)().call()
        state[name] = value
        if name in AMOUNT_FUNCTIONS:
            state[name + "_usdc"] = value / 10**6
    nodes: dict[str, object] = {}
    per_addr = _available(abi, PER_ADDRESS_FUNCTIONS)
    if per_addr:
        for raw_addr in getattr(args, "address", []) or []:
            addr = parse_addresses(raw_addr)[0]
            entry = {name: getattr(contract.functions, name)(addr).call() for name in per_addr}
            if "bondAmount" in entry:
                entry["bondAmount_usdc"] = entry["bondAmount"] / 10**6
            nodes[addr] = entry
    print(
        json.dumps(
            {
                "vault": address,
                "abi": abi_source,
                "chain_id": w3.eth.chain_id,
                "block": w3.eth.block_number,
                "state": state,
                "nodes": nodes,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return EXIT_OK


def cmd_deploy(args, env) -> int:
    if not getattr(args, "artifact", None):
        raise UsageError("deploy 需要 --artifact（forge build 产出的 KarmaVerifierBond.json）")
    if not (getattr(args, "token", None) or "").strip():
        raise UsageError("deploy 需要 --token（质押 ERC20 地址）")
    from web3 import Web3

    abi, bytecode = _load_artifact(args.artifact)
    token = Web3.to_checksum_address(args.token.strip())
    min_bond = usdc_to_wei(_require_positive("--min-bond", args.min_bond))
    cooldown = int(float(args.cooldown_hours) * 3600)
    if cooldown <= 0:
        raise UsageError("--cooldown-hours 必须 > 0（冷却期是「被挑战先跑」的堵口）")
    min_pool = usdc_to_wei(_require_positive("--min-pool-payout", args.min_pool_payout))
    admin = Web3.to_checksum_address(args.admin.strip()) if args.admin else None
    slasher = Web3.to_checksum_address(args.slasher.strip()) if args.slasher else None
    plan = {
        "action": "deploy",
        "abi": "artifact",
        "token": token,
        "min_bond_wei": min_bond,
        "unbond_cooldown_seconds": cooldown,
        "min_pool_payout_wei": min_pool,
        "admin": admin or "<signer>",
        "slasher": slasher or admin or "<signer>",
        "deploy_gas": int(args.gas),
    }
    if args.dry_run:
        print(json.dumps({**plan, "broadcast": "skipped (dry-run)"}, ensure_ascii=False, indent=2))
        return EXIT_OK

    signer = _signer(args.key_env, env)
    w3 = _connect(resolve_rpc(args, env))
    admin = admin or signer.address
    slasher = slasher or admin
    factory = w3.eth.contract(abi=abi, bytecode=bytecode)
    tx_hash, receipt = _send(
        w3,
        signer,
        factory.constructor(admin, token, min_bond).build_transaction({}),
        gas=int(args.gas),
    )
    vault_address = receipt["contractAddress"]
    print("VAULT_ADDRESS=%s" % vault_address)
    print("deploy_tx=%s" % tx_hash)
    print("deploy_gasUsed=%s" % receipt["gasUsed"])
    print("deploy_block=%s" % receipt["blockNumber"])

    vault = w3.eth.contract(address=vault_address, abi=abi)
    if admin == signer.address:
        cfg_tx, _ = _send(w3, signer, vault.functions.setStakeConfig(
            min_bond, cooldown, min_pool).build_transaction({}))
        slasher_tx, _ = _send(w3, signer, vault.functions.setSlasher(slasher).build_transaction({}))
        print("setStakeConfig_tx=%s" % cfg_tx)
        print("setSlasher_tx=%s" % slasher_tx)
    else:
        print("ACTION REQUIRED: admin 不是签名者 —— 由多签自己发 "
              "setStakeConfig(minBond, cooldown, minPoolPayout) 与 setSlasher(slasher)")
    return EXIT_OK


def encode_slash_calldata(
    *, vault: str | None, verifier: str, victim: str | None, amount_wei: int, reason: str
) -> str:
    """编码 ``slash(address,address,uint256,bytes32)``。

    复用后端的 ``VAULT_ABI`` 与 ``reason_hash`` —— 链下台账和链上分账看的是同一份
    ABI、同一套理由哈希，不另起一份实现。``vault`` 只用来建 contract 对象，不进
    calldata；缺省用零地址占位，所以 ``--dry-run`` 不必先配金库。
    """
    from web3 import Web3

    from services.chain.verifier_bond_vault import VAULT_ABI, reason_hash

    contract = Web3().eth.contract(
        address=Web3.to_checksum_address(vault or ZERO_ADDRESS), abi=VAULT_ABI
    )
    data = contract.encode_abi(
        "slash",
        args=[
            Web3.to_checksum_address(verifier),
            Web3.to_checksum_address(victim) if victim else ZERO_ADDRESS,
            int(amount_wei),
            reason_hash(reason or ""),
        ],
    )
    return data if data.startswith("0x") else "0x" + data


def cmd_slash(args, env) -> int:
    verifier = parse_addresses(args.verifier)[0]
    victim = parse_addresses(args.victim)[0] if args.victim else None
    amount_wei = usdc_to_wei(_require_positive("--amount", args.amount))
    vault = resolve_vault_address(args)
    data = encode_slash_calldata(
        vault=vault,
        verifier=verifier,
        victim=victim,
        amount_wei=amount_wei,
        reason=args.reason or "",
    )
    if args.dry_run:
        print(
            json.dumps(
                {
                    "action": "slash",
                    "to": vault or "<VERIFIER_BOND_VAULT_ADDRESS>",
                    "verifier": verifier,
                    "victim": victim or ZERO_ADDRESS,
                    "amount_wei": amount_wei,
                    "reason": args.reason or "",
                    "calldata": data,
                    "broadcast": "skipped (dry-run)",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return EXIT_OK
    if not vault:
        raise CliError("没配金库：用 --vault，或设 VERIFIER_BOND_VAULT_ADDRESS")

    signer = _signer(args.key_env, env)
    w3 = _connect(resolve_rpc(args, env))
    tx_hash, receipt = _send(
        w3, signer, {"to": vault, "value": 0, "data": data, "chainId": w3.eth.chain_id}
    )
    print("slash_tx=%s" % tx_hash)
    print("slash_gasUsed=%s" % receipt["gasUsed"])
    print("slash_block=%s" % receipt["blockNumber"])
    print("slash_verifier=%s" % verifier)
    print("slash_victim=%s" % (victim or ZERO_ADDRESS))
    print("slash_amount_wei=%s" % amount_wei)
    return EXIT_OK


def cmd_distribute(args, env) -> int:
    winners = parse_addresses(args.winners)
    amount_wei = usdc_to_wei(_require_positive("--amount", args.amount))
    abi, abi_source = _vault_abi(args)
    vault = resolve_vault_address(args)
    from web3 import Web3

    contract = Web3().eth.contract(abi=abi)
    data = contract.encode_abi("distributePool", args=[winners, amount_wei])
    data = data if data.startswith("0x") else "0x" + data
    if args.dry_run:
        print(
            json.dumps(
                {
                    "action": "distribute",
                    "to": vault or "<VERIFIER_BOND_VAULT_ADDRESS>",
                    "winners": winners,
                    "amount_wei": amount_wei,
                    "abi": abi_source,
                    "calldata": data,
                    "broadcast": "skipped (dry-run)",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return EXIT_OK
    if not vault:
        raise CliError("没配金库：用 --vault，或设 VERIFIER_BOND_VAULT_ADDRESS")

    signer = _signer(args.key_env, env)
    w3 = _connect(resolve_rpc(args, env))
    tx_hash, receipt = _send(w3, signer, {"to": vault, "value": 0, "data": data})
    print("distribute_tx=%s" % tx_hash)
    print("distribute_gasUsed=%s" % receipt["gasUsed"])
    print("distribute_winners=%s" % ",".join(winners))
    print("distribute_amount_wei=%s" % amount_wei)
    return EXIT_OK


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def _add_common_options(parser: argparse.ArgumentParser, *, sub: bool = False) -> None:
    """``--rpc`` / ``--vault`` / ``--artifact`` / ``--key-env`` / ``--dry-run`` 在子命令
    前后都能写。

    子命令那一层用 ``SUPPRESS`` 默认值 —— argparse 子解析器会拿自己的默认值回写命名
    空间，不用 SUPPRESS 的话「写在子命令之前」的选项会被后面的默认值悄悄覆盖。
    """
    default = argparse.SUPPRESS if sub else None
    parser.add_argument("--rpc", default=default,
                        help="RPC 端点（默认取 TESTNET_RPC_URL / VERIFIER_BOND_RPC_URL）")
    parser.add_argument("--vault", default=default,
                        help="金库地址（默认取 VERIFIER_BOND_VAULT_ADDRESS）")
    parser.add_argument("--artifact", default=default,
                        help="forge build 产出的 KarmaVerifierBond.json（含 abi + bytecode）")
    parser.add_argument("--key-env", default=argparse.SUPPRESS if sub else DEFAULT_KEY_ENV,
                        help="从哪个环境变量读签名私钥（默认 %s）" % DEFAULT_KEY_ENV)
    parser.add_argument("--dry-run", action="store_true",
                        default=argparse.SUPPRESS if sub else False,
                        help="只打印将要发的内容，不广播、不碰链")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="verifier_bond_vault",
        description="Karma 验证者质押金库（KarmaVerifierBond / G12）运维 CLI —— 测试网先行",
    )
    _add_common_options(parser)
    sub = parser.add_subparsers(dest="cmd", required=True)

    status = sub.add_parser("status", help="只读：打印金库链上状态")
    _add_common_options(status, sub=True)
    status.add_argument("--address", action="append", default=[],
                        help="要查的节点地址（可重复；逗号分隔也行）")
    status.set_defaults(func=cmd_status)

    deploy = sub.add_parser("deploy", help="部署 + 配置金库（测试网；主网走多签）")
    _add_common_options(deploy, sub=True)
    deploy.add_argument("--token", help="质押 ERC20 地址")
    deploy.add_argument("--min-bond", type=float, default=5.0, help="最低保证金（USDC，默认 5）")
    deploy.add_argument("--cooldown-hours", type=float, default=72.0, help="退出冷却期（小时，默认 72）")
    deploy.add_argument("--min-pool-payout", type=float, default=1.0, help="罚没池起奖线（USDC，默认 1）")
    deploy.add_argument("--admin", help="admin 地址（默认 = 签名者）")
    deploy.add_argument("--slasher", help="slasher 地址（默认 = admin）")
    deploy.add_argument("--gas", type=int, default=DEPLOY_GAS_CEILING,
                        help="部署 gas 上限（默认 %d；via_ir 创建成本约 9.2M）" % DEPLOY_GAS_CEILING)
    deploy.set_defaults(func=cmd_deploy)

    slash = sub.add_parser("slash", help="罚没：编码 + 签名 + 广播（治理动作）")
    _add_common_options(slash, sub=True)
    slash.add_argument("--verifier", required=True, help="被罚的节点地址")
    slash.add_argument("--amount", type=float, required=True, help="罚没额（USDC）")
    slash.add_argument("--victim", help="受害方地址（缺省 = 全进罚没池）")
    slash.add_argument("--reason", default="", help="罚没理由（链上打 keccak256 便于对账）")
    slash.set_defaults(func=cmd_slash)

    distribute = sub.add_parser("distribute", help="把罚没池分给优秀节点")
    _add_common_options(distribute, sub=True)
    distribute.add_argument("--winners", required=True, help="获奖节点地址，逗号分隔")
    distribute.add_argument("--amount", type=float, required=True, help="分出金额（USDC）")
    distribute.set_defaults(func=cmd_distribute)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    env = dict(os.environ)
    try:
        return int(args.func(args, env))
    except UsageError as exc:
        sys.stderr.write("usage error: %s\n" % exc)
        return EXIT_USAGE
    except CliError as exc:
        sys.stderr.write("error: %s\n" % exc)
        return EXIT_FAILED
    except KeyboardInterrupt:
        sys.stderr.write("interrupted\n")
        return EXIT_FAILED


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    sys.exit(main())