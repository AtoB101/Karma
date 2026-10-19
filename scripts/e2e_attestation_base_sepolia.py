#!/usr/bin/env python3
"""P0-1: end-to-end attestation settlement on Base Sepolia.

Proves the arbitration path actually works (the core differentiator vs a
plain escrow). Registers 3 verifiers, runs a bindWithAttestation binding,
publishes evidence, collects 3-of-3 EIP-712 attestations, waits out the
challenge window, and settles via settleWithAttestation.

Deploys a fresh VerifierRegistry + KarmaAttestationGateway (short 60s
challenge window for testnet) and repoints KarmaBilateral to them, so the
already-deployed production testnet contracts are not disturbed.

Env:
  ADMIN_PRIVATE_KEY   Base Sepolia deployer/admin key
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "karma-sdk" / "python"))

from web3 import Web3
from eth_account import Account
from eth_keys import keys
from eth_abi import encode

RPC = os.getenv("BASE_SEPOLIA_RPC", "https://sepolia.base.org")
CHAIN_ID = 84532
KARMA = "0x3D633d55Bb7bDD4Af55a92C0F48dd25B7f06c3A5"
ADMIN_KEY = os.getenv("ADMIN_PRIVATE_KEY", "")

AMOUNT = 10_000_000          # 10 mUSDC (6 decimals)
ETH_STIPEND = Web3.to_wei(0.002, "ether")
CHALLENGE_WINDOW = 60        # seconds (constructor does not enforce the 1h floor)

OUT = ROOT / "karma-core" / "contracts" / "out"


def load(path: Path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def send_tx(w3, acct, fn, gas=3_000_000):
    tx = fn.build_transaction({
        "from": acct.address,
        "nonce": w3.eth.get_transaction_count(acct.address, "pending"),
        "gas": gas,
    })
    signed = acct.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    if receipt.status != 1:
        raise RuntimeError(f"tx {tx_hash.hex()} reverted")
    return receipt


def fund(w3, admin, to, value):
    tx = {
        "from": admin.address,
        "to": Web3.to_checksum_address(to),
        "value": value,
        "gas": 21000,
        "gasPrice": w3.eth.gas_price,
        "nonce": w3.eth.get_transaction_count(admin.address, "pending"),
    }
    signed = admin.sign_transaction(tx)
    h = w3.eth.send_raw_transaction(signed.raw_transaction)
    return w3.eth.wait_for_transaction_receipt(h, timeout=120)


def latest_ts(w3):
    return w3.eth.get_block("latest")["timestamp"]



def _wait_until(cond, label, timeout=60, interval=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return
        print(f"\r  waiting {label}...", end="", flush=True)
        time.sleep(interval)
    print("")
    if not cond():
        raise TimeoutError(f"timed out waiting for {label}")


def main() -> int:
    if not ADMIN_KEY:
        print("Set ADMIN_PRIVATE_KEY env var.")
        return 2

    w3 = Web3(Web3.HTTPProvider(RPC))
    assert w3.is_connected()
    assert w3.eth.chain_id == CHAIN_ID
    admin = Account.from_key(ADMIN_KEY)
    print(f"chain    {w3.eth.chain_id} ({RPC})")
    print(f"admin    {admin.address}")
    print(f"karma    {KARMA}")

    karma_artifact = load(OUT / "KarmaBilateral.sol" / "KarmaBilateral.json")
    karma = w3.eth.contract(address=Web3.to_checksum_address(KARMA), abi=karma_artifact["abi"])

    # 1. fresh MockERC20 (open mint)
    mock_artifact = load(OUT / "MockERC20.sol" / "MockERC20.json")
    Mock = w3.eth.contract(abi=mock_artifact["abi"], bytecode=mock_artifact["bytecode"]["object"])
    mock_addr = send_tx(w3, admin, Mock.constructor())["contractAddress"]
    mock = w3.eth.contract(address=mock_addr, abi=mock_artifact["abi"])
    send_tx(w3, admin, karma.functions.setTokenAllowed(mock_addr, True))
    print(f"mock     {mock_addr}")

    # 2. fresh VerifierRegistry with real staking (minStake 1 mUSDC)
    reg_artifact = load(OUT / "VerifierRegistry.sol" / "VerifierRegistry.json")
    Reg = w3.eth.contract(abi=reg_artifact["abi"], bytecode=reg_artifact["bytecode"]["object"])
    reg_addr = send_tx(w3, admin, Reg.constructor(admin.address))["contractAddress"]
    registry = w3.eth.contract(address=reg_addr, abi=reg_artifact["abi"])
    MIN_STAKE = 1_000_000  # 1 mUSDC
    send_tx(w3, admin, registry.functions.setStakingConfig(mock_addr, MIN_STAKE, 0))
    print(f"registry {reg_addr}")

    # 3. register 3 verifiers (inactive) and stake to activate
    verifiers = [Account.create() for _ in range(3)]
    for i, v in enumerate(verifiers):
        if w3.eth.get_balance(v.address) < ETH_STIPEND:
            fund(w3, admin, v.address, ETH_STIPEND)
        send_tx(w3, admin, registry.functions.registerVerifier(v.address, f"https://v{i+1}.e2e.karma", 0))
        send_tx(w3, admin, mock.functions.mint(v.address, MIN_STAKE))
        send_tx(w3, v, mock.functions.approve(reg_addr, MIN_STAKE))
        send_tx(w3, v, registry.functions.stake(MIN_STAKE))
        assert registry.functions.isActiveVerifier(v.address).call()
        print(f"  verifier {i+1} {v.address} active")
    send_tx(w3, admin, registry.functions.setThresholds(3, 3))

    # 4. fresh gateway with 60s challenge window
    gw_artifact = load(OUT / "KarmaAttestationGateway.sol" / "KarmaAttestationGateway.json")
    Gw = w3.eth.contract(abi=gw_artifact["abi"], bytecode=gw_artifact["bytecode"]["object"])
    gw_addr = send_tx(w3, admin, Gw.constructor(reg_addr, KARMA, admin.address, CHALLENGE_WINDOW))["contractAddress"]
    gateway = w3.eth.contract(address=gw_addr, abi=gw_artifact["abi"])
    send_tx(w3, admin, registry.functions.setAuthorizedCaller(gw_addr, True))
    send_tx(w3, admin, karma.functions.setAttestationGateway(gw_addr))
    print(f"gateway  {gw_addr} (challengeWindow={CHALLENGE_WINDOW}s)")

    # 5. buyer + agent lock
    buyer = Account.create()
    agent = Account.create()
    for a in (buyer, agent):
        if w3.eth.get_balance(a.address) < ETH_STIPEND:
            fund(w3, admin, a.address, ETH_STIPEND)
        send_tx(w3, admin, mock.functions.mint(a.address, AMOUNT))
        send_tx(w3, a, mock.functions.approve(KARMA, AMOUNT))
    print(f"buyer    {buyer.address}")
    print(f"agent    {agent.address}")

    buyer_bill = _lock(w3, karma, buyer, mock_addr, AMOUNT)
    agent_bill = _lock(w3, karma, agent, mock_addr, AMOUNT)
    print(f"bills    buyer={buyer_bill} agent={agent_bill}")

    # 6. bindWithAttestation
    task_id = Web3.keccak(text="base-sepolia-attestation-e2e-task")
    scope = Web3.keccak(text="base-sepolia-attestation-e2e-scope")
    bind_receipt = send_tx(w3, buyer, karma.functions.bindWithAttestation(buyer_bill, agent_bill, scope, task_id))
    binding_id = int(karma.events.BillsBound().process_receipt(bind_receipt)[0]["args"]["bindingId"])
    print(f"binding  {binding_id}")
    _wait_until(lambda: karma.functions.requiresAttestation(binding_id).call(),
                f"requiresAttestation[{binding_id}]=true")
    print(f"requiresAttestation={karma.functions.requiresAttestation(binding_id).call()}")

    # 7. publish evidence
    evidence_hash = Web3.keccak(text="ipfs://base-sepolia-attestation-e2e-proof")
    cid = "ipfs://bafy-attestation-e2e"
    send_tx(w3, admin, gateway.functions.publishEvidence(task_id, evidence_hash, cid))
    print(f"evidence {cid} hash={evidence_hash.hex()}")

    # 8. verifiers sign + submit EIP-712 attestations
    for i, v in enumerate(verifiers):
        if w3.eth.get_balance(v.address) < ETH_STIPEND:
            fund(w3, admin, v.address, ETH_STIPEND)
        _submit_attestation(w3, gateway, v, task_id, True)
        print(f"  attestation {i+1}/3 from {v.address}")

    print(f"quorum   {gateway.functions.isQuorumReached(task_id).call()} "
          f"valid={gateway.functions.validAttestationCount(task_id).call()}")

    # 9. wait out challenge window
    challenge_end = gateway.functions.challengeEnd(task_id).call()
    print(f"waiting challenge window: end={challenge_end}")
    while latest_ts(w3) <= challenge_end:
        print(f"\r  {challenge_end - latest_ts(w3):>3}s remaining", end="", flush=True)
        time.sleep(10)
    print("")

    # 10. settle
    print("settleWithAttestation ...")
    send_tx(w3, admin, gateway.functions.settleWithAttestation(task_id, binding_id, evidence_hash))

    _wait_until(lambda: karma.functions.getBinding(binding_id).call()[4] == 3,
                f"binding {binding_id} SETTLED")
    state = karma.functions.getBinding(binding_id).call()[4]
    print(f"binding state={state} (expect 3=SETTLED)")
    assert state == 3, f"expected SETTLED(3), got {state}"

    buyer_final = mock.functions.balanceOf(buyer.address).call()
    agent_final = mock.functions.balanceOf(agent.address).call()
    print(f"payout   buyer={buyer_final/1e6} agent={agent_final/1e6} mUSDC")
    assert buyer_final == 0
    assert agent_final == 2 * AMOUNT
    assert karma.functions.checkInvariant(mock_addr).call()

    print("\nP0-1 ATTESTATION E2E PASSED")
    print(f"  taskId={task_id.hex()}")
    print(f"  gateway={gw_addr}")
    print(f"  registry={reg_addr}")
    print(f"  mock={mock_addr}")
    return 0


def _lock(w3, karma, acct, token, amount):
    receipt = send_tx(w3, acct, karma.functions.lock(Web3.to_checksum_address(token), amount))
    logs = karma.events.BillMinted().process_receipt(receipt)
    return int(logs[0]["args"]["billId"])


def _submit_attestation(w3, gateway, verifier, task_id, valid):
    evidence_hash = gateway.functions.taskEvidence(task_id).call()
    cid = gateway.functions.taskEvidenceCid(task_id).call()
    typehash = Web3.keccak(text="KarmaAttestation(bytes32 taskId,bytes32 evidenceHash,string cid,address verifier,uint256 chainId,address verifyingContract)")
    domain_typehash = Web3.keccak(text="EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)")
    domain = Web3.keccak(encode(
        ["bytes32", "bytes32", "bytes32", "uint256", "address"],
        [domain_typehash, Web3.keccak(text="KarmaAttestationGateway"), Web3.keccak(text="1"),
         CHAIN_ID, Web3.to_checksum_address(gateway.address)],
    ))
    struct_hash = Web3.keccak(encode(
        ["bytes32", "bytes32", "bytes32", "string", "address", "uint256", "address"],
        [typehash, task_id, evidence_hash, cid, verifier.address, CHAIN_ID,
         Web3.to_checksum_address(gateway.address)],
    ))
    digest = Web3.keccak(b"\x19\x01" + domain + struct_hash)
    sig = keys.PrivateKey(verifier.key).sign_msg_hash(digest)
    v = sig.v + 27
    r = sig.r.to_bytes(32, "big")
    s = sig.s.to_bytes(32, "big")
    send_tx(w3, verifier, gateway.functions.submitAttestation(task_id, v, r, s, valid))


if __name__ == "__main__":
    sys.exit(main())
