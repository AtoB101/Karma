"""Pluggable signing backends for trade launch intents (Phase 1 — Open Wallet)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TradeLaunchSignContext:
    buyer_identity_id: str
    seller_identity_id: str
    requirement_fingerprint: str
    amount: float
    task_type: str
    task_precision: float
    launch_nonce: str
    deadline_unix: int
    chain_id: int
    verifying_contract: str
    chain_anchor_hash: str | None = None

    def to_typed_data(self) -> dict[str, Any]:
        from services.trade_launch_eip712 import build_trade_launch_typed_data

        return build_trade_launch_typed_data(
            buyer_identity_id=self.buyer_identity_id,
            seller_identity_id=self.seller_identity_id,
            requirement_fingerprint=self.requirement_fingerprint,
            amount=self.amount,
            task_type=self.task_type,
            task_precision=self.task_precision,
            launch_nonce=self.launch_nonce,
            deadline_unix=self.deadline_unix,
            chain_id=self.chain_id,
            verifying_contract=self.verifying_contract,
            chain_anchor_hash=self.chain_anchor_hash,
        )


class SigningBackend(ABC):
    """Sign or verify EIP-712 trade launch intents without exposing keys to the agent runtime."""

    @property
    @abstractmethod
    def backend_id(self) -> str:
        ...

    @abstractmethod
    def sign_trade_launch(self, ctx: TradeLaunchSignContext) -> str:
        ...

    def preview_typed_data(self, ctx: TradeLaunchSignContext) -> dict[str, Any]:
        return ctx.to_typed_data()


class ExternalWalletBackend(SigningBackend):
    """WalletConnect / browser wallet — signing happens outside Karma."""

    @property
    def backend_id(self) -> str:
        return "external"

    def sign_trade_launch(self, ctx: TradeLaunchSignContext) -> str:
        raise NotImplementedError(
            "external wallet backend does not sign server-side; use signing-preview then pass buyer_signature"
        )


class _EvmPrivateKeyBackend(SigningBackend):
    def __init__(self, *, backend_id: str, private_key: str):
        self._backend_id = backend_id
        self._private_key = private_key.strip()

    @property
    def backend_id(self) -> str:
        return self._backend_id

    def sign_trade_launch(self, ctx: TradeLaunchSignContext) -> str:
        from services.trade_launch_eip712 import sign_trade_launch_typed_data

        if not self._private_key:
            raise ValueError(f"{self._backend_id} signing backend has no private key configured")
        return sign_trade_launch_typed_data(
            private_key=self._private_key,
            typed_data=ctx.to_typed_data(),
        )


class LocalDevBackend(_EvmPrivateKeyBackend):
    """Uses TESTNET_PRIVATE_KEY when set (development / CI only)."""

    def __init__(self, private_key: str):
        super().__init__(backend_id="local", private_key=private_key)


class EnvKeyBackend(_EvmPrivateKeyBackend):
    """Uses KARMA_SIGNING_DEV_PRIVATE_KEY (never commit a mainnet key)."""

    def __init__(self, private_key: str):
        super().__init__(backend_id="env", private_key=private_key)


def get_signing_backend(backend_id: str | None = None) -> SigningBackend:
    from config.settings import settings

    bid = (backend_id or settings.karma_signing_backend or "client_only").strip().lower()
    if bid == "client_only":
        return ExternalWalletBackend()
    if bid == "external":
        return ExternalWalletBackend()
    if bid == "local":
        key = (settings.testnet_private_key or "").strip()
        if not key:
            raise ValueError("KARMA_SIGNING_BACKEND=local requires TESTNET_PRIVATE_KEY")
        return LocalDevBackend(key)
    if bid == "env":
        key = (settings.karma_signing_dev_private_key or "").strip()
        if not key:
            raise ValueError("KARMA_SIGNING_BACKEND=env requires KARMA_SIGNING_DEV_PRIVATE_KEY")
        return EnvKeyBackend(key)
    raise ValueError(f"unknown KARMA_SIGNING_BACKEND: {bid}")
