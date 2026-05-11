"""
Karma — Ed25519 Signing Service
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from config.settings import settings
from core.hooks.hook_layer import ReceiptSigner
from core.evidence.bundle_builder import BundleSigner
from core.schemas import ExecutionReceipt


class Ed25519SigningService(ReceiptSigner, BundleSigner):
    """
    Ed25519 key management, signing, and verification.
    Implements both ReceiptSigner and BundleSigner interfaces.
    """

    def __init__(self):
        self._private_key: Ed25519PrivateKey | None = None
        self._public_key: Ed25519PublicKey | None = None
        self._load_or_generate()

    # --- Key lifecycle ---

    def _load_or_generate(self) -> None:
        priv_path = Path(settings.ed25519_private_key_path)
        pub_path  = Path(settings.ed25519_public_key_path)
        if priv_path.exists() and pub_path.exists():
            with open(priv_path, "rb") as f:
                self._private_key = serialization.load_pem_private_key(f.read(), password=None)
            with open(pub_path, "rb") as f:
                self._public_key = serialization.load_pem_public_key(f.read())  # type: ignore
        else:
            self._generate_and_save(priv_path, pub_path)

    def _generate_and_save(self, priv_path: Path, pub_path: Path) -> None:
        priv_path.parent.mkdir(parents=True, exist_ok=True)
        self._private_key = Ed25519PrivateKey.generate()
        self._public_key  = self._private_key.public_key()
        with open(priv_path, "wb") as f:
            f.write(self._private_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ))
        with open(pub_path, "wb") as f:
            f.write(self._public_key.public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            ))

    # --- Public interface ---

    def get_public_key_b64(self) -> str:
        assert self._public_key
        raw = self._public_key.public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        return base64.b64encode(raw).decode()

    def sign_bytes(self, data: bytes) -> str:
        assert self._private_key
        return base64.b64encode(self._private_key.sign(data)).decode()

    def sign_dict(self, payload: dict[str, Any]) -> str:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return self.sign_bytes(canonical)

    def verify(self, data: bytes, signature_b64: str, public_key_b64: str | None = None) -> bool:
        try:
            sig = base64.b64decode(signature_b64)
            if public_key_b64:
                raw = base64.b64decode(public_key_b64)
                pub: Ed25519PublicKey = Ed25519PublicKey.from_public_bytes(raw)  # type: ignore
            else:
                pub = self._public_key  # type: ignore
            assert pub
            pub.verify(sig, data)
            return True
        except Exception:
            return False

    # --- ReceiptSigner ---

    def sign_receipt(self, receipt: ExecutionReceipt) -> str:
        payload = {
            "receipt_id": receipt.receipt_id,
            "task_id":    receipt.task_id,
            "agent_id":   receipt.agent_id,
            "step_index": receipt.step_index,
            "tool_name":  receipt.tool_name,
            "input_hash": receipt.input_hash,
            "output_hash":receipt.output_hash,
            "started_at": receipt.started_at.isoformat(),
            "ended_at":   receipt.ended_at.isoformat(),
            "status":     receipt.status.value if hasattr(receipt.status, "value") else receipt.status,
        }
        return self.sign_dict(payload)

    # --- BundleSigner ---

    def sign_bundle(self, payload: dict[str, Any]) -> str:
        return self.sign_dict(payload)


def sha256_of(data: Any) -> str:
    if isinstance(data, bytes):
        raw = data
    elif isinstance(data, str):
        raw = data.encode()
    else:
        raw = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(raw).hexdigest()


# Singleton
signing_service = Ed25519SigningService()
