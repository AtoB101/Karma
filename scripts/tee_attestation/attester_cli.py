#!/usr/bin/env python3
"""Attester CLI — verify a Nitro attestation and register the enclave on-chain.

Two subcommands:

  verify    Off-chain only: verify the hardware quote against the AWS Nitro root
            and print the extracted enclave address + imageHash as JSON. This is
            the auditable, reproducible half of the trust split.

  register  Verify (same as above) and then broadcast
            `TEESettlementVerifier.registerEnclave(enclave, imageHash)`.

Examples:

  python scripts/tee_attestation/attester_cli.py verify ./attestation.cose
  python scripts/tee_attestation/attester_cli.py register ./attestation.cose \
      --verifier 0x... --attester-key 0x... --rpc https://sepolia.base.org

Env fallbacks:
  ATTESTER_PRIVATE_KEY  attester private key (register)
  BASE_SEPOLIA_RPC      RPC URL (register)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import nitro_attestation as na  # noqa: E402

DEFAULT_ROOT_CA = SCRIPT_DIR / "root.pem"


def _read_document(arg: str) -> bytes:
    if Path(arg).exists():
        return Path(arg).read_bytes()
    return bytes.fromhex(arg.replace("0x", ""))


def _verify(args) -> dict:
    document = _read_document(args.document)
    root_pem = Path(args.root_ca).read_bytes()
    expected_pcr0 = bytes.fromhex(args.expected_pcr0[2:]) if args.expected_pcr0 else None
    result = na.verify_attestation(
        document,
        root_pem,
        expected_pcr0=expected_pcr0,
        max_age_seconds=args.max_age,
    )
    return {
        "ok": True,
        "moduleId": result.module_id.hex(),
        "pcr0": result.pcr0.hex(),
        "imageHash": "0x" + result.image_hash.hex(),
        "enclave": result.enclave_address,
        "timestamp": result.timestamp,
        "digest": result.digest,
    }


def cmd_verify(args) -> int:
    print(json.dumps(_verify(args), indent=2))
    return 0


def cmd_register(args) -> int:
    from web3 import Web3
    from eth_account import Account

    out = _verify(args)
    enclave = args.enclave or out["enclave"]
    if not enclave:
        print("enclave address not present in user_data; pass --enclave explicitly.", file=sys.stderr)
        return 2
    image_hash = out["imageHash"]

    key = args.attester_key or os.getenv("ATTESTER_PRIVATE_KEY", "")
    if not key:
        print("Set --attester-key or ATTESTER_PRIVATE_KEY.", file=sys.stderr)
        return 2

    rpc = args.rpc or os.getenv("BASE_SEPOLIA_RPC", "https://sepolia.base.org")
    w3 = Web3(Web3.HTTPProvider(rpc))
    if not w3.is_connected():
        print(f"cannot connect to {rpc}", file=sys.stderr)
        return 2
    acct = Account.from_key(key)

    verifier_abi = [
        {
            "inputs": [{"internalType": "address", "name": "enclave", "type": "address"},
                       {"internalType": "bytes32", "name": "imageHash", "type": "bytes32"}],
            "name": "registerEnclave",
            "outputs": [],
            "stateMutability": "nonpayable",
            "type": "function",
        }
    ]
    verifier = w3.eth.contract(address=Web3.to_checksum_address(args.verifier), abi=verifier_abi)

    tx = verifier.functions.registerEnclave(
        Web3.to_checksum_address(enclave), Web3.to_bytes(hexstr=image_hash)
    ).build_transaction({
        "from": acct.address,
        "nonce": w3.eth.get_transaction_count(acct.address, "pending"),
    })
    tx["gas"] = 300_000
    signed = acct.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
    if receipt.status != 1:
        print(f"registerEnclave reverted: {tx_hash.hex()}", file=sys.stderr)
        return 1

    print(json.dumps({**out, "enclave": enclave, "registerTx": tx_hash.hex(), "verifier": args.verifier}, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify Nitro attestation and register enclave on-chain")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("document", help="attestation document (file path or hex)")
    common.add_argument("--root-ca", default=str(DEFAULT_ROOT_CA), help="trusted root CA PEM path")
    common.add_argument("--expected-pcr0", default=None, help="optional expected PCR0 (hex)")
    common.add_argument("--max-age", type=int, default=300, help="max attestation age in seconds")

    v = sub.add_parser("verify", parents=[common])
    v.set_defaults(func=cmd_verify)

    r = sub.add_parser("register", parents=[common])
    r.add_argument("--verifier", required=True, help="TEESettlementVerifier address")
    r.add_argument("--attester-key", default=None, help="attester private key (hex)")
    r.add_argument("--rpc", default=None, help="RPC URL")
    r.add_argument("--enclave", default=None, help="override enclave address if user_data is empty")
    r.set_defaults(func=cmd_register)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
