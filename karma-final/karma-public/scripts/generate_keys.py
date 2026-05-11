#!/usr/bin/env python3
"""
Generate Ed25519 signing keys for Karma agents.

Usage:
    python scripts/generate_keys.py
    python scripts/generate_keys.py --out keys/worker
"""
import argparse
import sys
from pathlib import Path


def generate(private_path: Path, public_path: Path) -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization

    private_path.parent.mkdir(parents=True, exist_ok=True)

    if private_path.exists():
        print(f"[skip] {private_path} already exists — delete it first to regenerate.")
        return

    key = Ed25519PrivateKey.generate()

    with open(private_path, "wb") as f:
        f.write(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ))
    private_path.chmod(0o600)

    with open(public_path, "wb") as f:
        f.write(key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ))

    print(f"[ok] Private key: {private_path}")
    print(f"[ok] Public key:  {public_path}")

    # Print base64 public key for agent registration
    import base64
    raw = key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    print(f"[ok] Public key (base64): {base64.b64encode(raw).decode()}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Ed25519 keys for Karma")
    parser.add_argument("--out", default="keys/agent", help="Key file prefix (default: keys/agent)")
    args = parser.parse_args()

    prefix = Path(args.out)
    generate(
        private_path=prefix.parent / (prefix.name + "_private.pem"),
        public_path=prefix.parent / (prefix.name + "_public.pem"),
    )


if __name__ == "__main__":
    main()
