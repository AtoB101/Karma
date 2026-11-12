#!/usr/bin/env python3
"""TEE machine-verifiable settlement E2E on Base Sepolia.

Deploys a fresh KarmaBilateral + TEESettlementVerifier + MockERC20, registers an
enclave (off-chain quote verification is simulated by the attester role), then
runs lock -> bind -> settleWithTEE and asserts the binding settles IMMEDIATELY
(no Layer 1 dispute window) from a single enclave EIP-712 signature.

Fully isolated: deploys its own stack so shared testnet state is untouched.
The enclave key and imageHash match scripts/tee_attestation/settlement_vector.json.

Env:
  ADMIN_PRIVATE_KEY   Base Sepolia deployer/admin key (defaults to the known
                      test key used by this repo's CI/deploy runs)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from web3 import Web3
from eth_account import Account
from eth_utils import keccak

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "tee_attestation"))
import eip712_settlement as ref  # noqa: E402

RPC = os.getenv("BASE_SEPOLIA_RPC", "https://sepolia.base.org")
CHAIN_ID = 84532
ADMIN_KEY = os.getenv("ADMIN_PRIVATE_KEY", "")

AMOUNT = 10_000_000          # 10 mUSDC per side (6 decimals)
ETH_STIPEND = Web3.to_wei(0.002, "ether")
OUT = ROOT / "karma-core" / "contracts" / "out"
PER_TX_GAS_CAP = 16_777_216  # Base Azul (EIP-7825) per-tx gas ceiling

# Must match TEESettlementVerifier / golden vector.
ENCLAVE_PK = "0x" + "11" * 32
IMAGE_HASH = keccak(text="nitro-image-pcr0")


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
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
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


def deploy(w3, acct, artifact, *ctor_args):
    c = w3.eth.contract(abi=artifact["abi"], bytecode=artifact["bytecode"]["object"])
    gas = c.constructor(*ctor_args).estimate_gas({"from": acct.address})
    gas = min(int(gas * 1.15), PER_TX_GAS_CAP)
    return send_tx(w3, acct, c.constructor(*ctor_args), gas=gas)["contractAddress"]


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
    print(f"admin_eth {w3.from_wei(w3.eth.get_balance(admin.address), 'ether')} ETH")

    karma_artifact = load(OUT / "KarmaBilateral.sol" / "KarmaBilateral.json")
    verifier_artifact = load(OUT / "TEESettlementVerifier.sol" / "TEESettlementVerifier.json")
    mock_artifact = load(OUT / "MockERC20.sol" / "MockERC20.json")

    # 1. fresh stack (Karma first, verifier needs the core address)
    karma_addr = deploy(w3, admin, karma_artifact, admin.address)
    mock_addr = deploy(w3, admin, mock_artifact)
    verifier_addr = deploy(w3, admin, verifier_artifact, admin.address, karma_addr)
    print(f"karma    {karma_addr}")
    print(f"mock     {mock_addr}")
    print(f"verifier {verifier_addr}")

    karma = w3.eth.contract(address=Web3.to_checksum_address(karma_addr), abi=karma_artifact["abi"])
    verifier = w3.eth.contract(address=Web3.to_checksum_address(verifier_addr), abi=verifier_artifact["abi"])
    mock = w3.eth.contract(address=Web3.to_checksum_address(mock_addr), abi=mock_artifact["abi"])

    # 2. wire TEE verifier + allow token + zero the settle delay
    send_tx(w3, admin, karma.functions.setTokenAllowed(mock_addr, True))
    send_tx(w3, admin, karma.functions.setSettleDelay(0))
    send_tx(w3, admin, karma.functions.setTEEVerifier(verifier_addr))
    send_tx(w3, admin, verifier.functions.setAttester(admin.address))
    assert karma.functions.teeVerifier().call() == Web3.to_checksum_address(verifier_addr)
    assert verifier.functions.core().call() == Web3.to_checksum_address(karma_addr)

    # 3. register the enclave (simulating a successful off-chain quote check)
    enclave_addr = Web3.to_checksum_address(ref.keys.PrivateKey(bytes.fromhex("11" * 32)).public_key.to_address())
    send_tx(w3, admin, verifier.functions.registerEnclave(enclave_addr, IMAGE_HASH))
    enclave = verifier.functions.enclaves(enclave_addr).call()
    assert enclave[1] is True and bytes(enclave[0]) == bytes(IMAGE_HASH)
    print(f"enclave  {enclave_addr} imageHash={Web3.to_hex(IMAGE_HASH)}")

    # 4. participants
    buyer, agent = Account.create(), Account.create()
    for a in (buyer, agent):
        if w3.eth.get_balance(a.address) < ETH_STIPEND:
            fund(w3, admin, a.address, ETH_STIPEND)
        send_tx(w3, admin, mock.functions.mint(a.address, AMOUNT))
        send_tx(w3, a, mock.functions.approve(karma_addr, AMOUNT))
    print(f"buyer    {buyer.address}")
    print(f"agent    {agent.address}")

    # 5. lock + bind
    def _lock(acct):
        receipt = send_tx(w3, acct, karma.functions.lock(mock_addr, AMOUNT))
        return int(karma.events.BillMinted().process_receipt(receipt)[0]["args"]["billId"])

    buyer_bill = _lock(buyer)
    agent_bill = _lock(agent)
    bind_receipt = send_tx(w3, buyer, karma.functions.bind(buyer_bill, agent_bill, Web3.keccak(text="scope")))
    binding_id = int(karma.events.BillsBound().process_receipt(bind_receipt)[0]["args"]["bindingId"])
    binding = karma.functions.getBinding(binding_id).call()
    print(f"binding  {binding_id}, state={binding[4]} (0=ACTIVE)")

    # 6. enclave signs the settlement digest off-chain
    proof_hash = keccak(text="execution-proof")
    domain_separator = ref.compute_domain_separator(CHAIN_ID, verifier_addr)
    signed = ref.sign_settlement(ENCLAVE_PK, domain_separator, binding_id, proof_hash, IMAGE_HASH)
    assert Web3.to_checksum_address(ref.keys.PrivateKey(bytes.fromhex("11" * 32)).public_key.to_address()) == enclave_addr
    attestation = bytes.fromhex(signed["teeAttestation"][2:])
    print(f"digest   {signed['digest']}")

    # on-chain DOMAIN_SEPARATOR must match the reference implementation
    assert Web3.to_hex(verifier.functions.DOMAIN_SEPARATOR().call()) == "0x" + domain_separator.hex(), \
        "on-chain domain separator != reference implementation"
    print("domain   separator matches reference impl byte-for-byte")

    # 7. settleWithTEE -> immediate SETTLED (no finalize step)
    settle_receipt = send_tx(w3, buyer, karma.functions.settleWithTEE(binding_id, proof_hash, attestation))
    settled_events = karma.events.TEESettled().process_receipt(settle_receipt)
    assert settled_events, "TEESettled event not emitted"
    binding = karma.functions.getBinding(binding_id).call()
    assert binding[4] == 3, f"expected SETTLED (3), got {binding[4]}"
    print(f"final    state={binding[4]} (3=SETTLED), TEESettled imageHash={Web3.to_hex(settled_events[0]['args']['imageHash'])}")

    # 8. financial invariant
    assert mock.functions.balanceOf(buyer.address).call() == 0, "buyer should pay full amount"
    assert mock.functions.balanceOf(agent.address).call() == 2 * AMOUNT, "agent should receive both bills (no fee wired)"
    assert karma.functions.checkInvariant(mock_addr).call() is True
    print(f"balances buyer={mock.functions.balanceOf(buyer.address).call()/1e6} agent={mock.functions.balanceOf(agent.address).call()/1e6} mUSDC")

    print("\nTEE SETTLEMENT E2E PASSED")
    print(f"  karma={karma_addr}")
    print(f"  verifier={verifier_addr}")
    print(f"  mock={mock_addr}")
    print(f"  enclave={enclave_addr}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
