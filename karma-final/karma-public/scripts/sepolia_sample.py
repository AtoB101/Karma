#!/usr/bin/env python3
"""
Standalone Sepolia on-chain sampling for market validation.
Uses Phase C task data that was already generated.
"""
import json
import os
import sys
import time
from pathlib import Path

TASK_DETAILS_DIR = Path("results/market-scenario-test/phase_C/task_details")
OUTPUT_DIR = Path("results/market-scenario-test/phase_C/sepolia_samples")

def sha256(data) -> str:
    import hashlib
    if isinstance(data, bytes):
        raw = data
    elif isinstance(data, str):
        raw = data.encode()
    else:
        raw = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(raw).hexdigest()

def load_tasks(market: str) -> list[dict]:
    tasks = []
    market_dir = TASK_DETAILS_DIR / market
    if not market_dir.exists():
        print(f"  No task details found for {market}")
        return tasks
    for f in sorted(market_dir.iterdir()):
        if f.suffix == ".json":
            with open(f) as fp:
                tasks.append(json.load(fp))
    return tasks

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    rpc_url = os.environ.get("TESTNET_RPC_URL", "")
    private_key = os.environ.get("TESTNET_PRIVATE_KEY", "")
    engine_addr = os.environ.get("KARMA_ENGINE_ADDRESS", "")
    chain_id = int(os.environ.get("TESTNET_CHAIN_ID", "11155111"))

    print(f"RPC: {rpc_url[:50]}...")
    print(f"Engine: {engine_addr}")
    print(f"Chain ID: {chain_id}")
    print(f"Key: {'SET' if private_key else 'MISSING'}")

    if not all([rpc_url, private_key, engine_addr]):
        print("ERROR: Missing config. Run: export $(grep -v '^#' .env.testnet | xargs)")
        # Generate simulation-mode tx log
        generate_sim_log()
        return

    try:
        from web3 import Web3
        w3 = Web3(Web3.HTTPProvider(rpc_url))
        if not w3.is_connected():
            print("ERROR: Cannot connect to Sepolia")
            generate_sim_log()
            return

        account = w3.eth.account.from_key(private_key)
        balance = w3.eth.get_balance(account.address)
        print(f"Wallet: {account.address}")
        print(f"Balance: {w3.from_wei(balance, 'ether')} ETH")

        all_tx_log = []
        for market in ["data_labeling", "api_call"]:
            print(f"\n{'='*50}")
            print(f"  {market} — 10 settlement flows")
            print(f"{'='*50}")

            tasks = load_tasks(market)
            if not tasks:
                print(f"  No tasks for {market}")
                continue

            sample_count = min(10, len(tasks))
            for i in range(sample_count):
                task = tasks[i]
                task_id = task.get("task_id", task.get("task_contract", {}).get("task_id", "unknown"))
                trace_id = task.get("trace_id", "unknown")
                settlement = task.get("settlement_plan", {})
                decision = settlement.get("decision", "unknown")
                tc = task.get("task_contract", {})
                escrow = tc.get("escrow_amount", 0)

                tx_entry = {
                    "market": market,
                    "sample_index": i + 1,
                    "task_id": task_id,
                    "trace_id": trace_id,
                    "decision": decision,
                    "escrow_amount": escrow,
                }

                try:
                    settlement_data = json.dumps({
                        "task_id": task_id,
                        "trace_id": trace_id,
                        "decision": decision,
                        "bundle_hash": sha256(task.get("evidence_bundle", {})),
                    })

                    tx = {
                        "from": account.address,
                        "to": w3.to_checksum_address(engine_addr),
                        "data": w3.to_hex(text=settlement_data),
                        "value": 0,
                        "gas": 100000,
                        "gasPrice": w3.eth.gas_price,
                        "nonce": w3.eth.get_transaction_count(account.address, 'pending'),
                        "chainId": chain_id,
                    }

                    signed = account.sign_transaction(tx)
                    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
                    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=90)

                    tx_entry["tx_hash"] = "0x" + tx_hash.hex()
                    tx_entry["block_number"] = receipt.blockNumber
                    tx_entry["gas_used"] = receipt.gasUsed
                    tx_entry["status"] = "success" if receipt.status == 1 else "failed"
                    print(f"  [{i+1}/{sample_count}] {tx_entry['tx_hash'][:18]}... blk={receipt.blockNumber} gas={receipt.gasUsed} ✓")

                except Exception as e:
                    tx_entry["status"] = "error"
                    tx_entry["error"] = str(e)[:200]
                    print(f"  [{i+1}/{sample_count}] ERROR: {str(e)[:120]}")

                all_tx_log.append(tx_entry)
                time.sleep(0.5)

        # Write tx log
        tx_log_path = OUTPUT_DIR / "sampled_onchain_tx_log.jsonl"
        with open(tx_log_path, "w") as f:
            for entry in all_tx_log:
                f.write(json.dumps(entry) + "\n")
        print(f"\n✓ {tx_log_path} ({len(all_tx_log)} entries)")

    except ImportError:
        print("web3 not installed. Run: pip install web3")
        generate_sim_log()
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        generate_sim_log()


def generate_sim_log():
    """Generate simulated on-chain tx log from task details."""
    print("\n  Generating simulation-mode on-chain tx log...")
    all_tx_log = []
    for market in ["data_labeling", "api_call"]:
        tasks = load_tasks(market)
        sample_count = min(10, len(tasks))
        for i in range(sample_count):
            task = tasks[i]
            task_id = task.get("task_id", task.get("task_contract", {}).get("task_id", "unknown"))
            trace_id = task.get("trace_id", "unknown")
            settlement = task.get("settlement_plan", {})
            decision = settlement.get("decision", "unknown")
            tc = task.get("task_contract", {})
            escrow = tc.get("escrow_amount", 0)

            all_tx_log.append({
                "market": market,
                "sample_index": i + 1,
                "task_id": task_id,
                "trace_id": trace_id,
                "decision": decision,
                "escrow_amount": escrow,
                "tx_hash": f"sim_{sha256(task_id)[:32]}",
                "block_number": 0,
                "gas_used": 0,
                "status": "simulated",
                "note": "Sepolia RPC not configured or unreachable — simulation mode",
            })

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    tx_log_path = OUTPUT_DIR / "sampled_onchain_tx_log.jsonl"
    with open(tx_log_path, "w") as f:
        for entry in all_tx_log:
            f.write(json.dumps(entry) + "\n")
    print(f"  ✓ Simulation tx log: {tx_log_path} ({len(all_tx_log)} entries)")


if __name__ == "__main__":
    main()
