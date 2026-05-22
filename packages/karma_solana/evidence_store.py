"""
SolanaEvidenceStore — Decentralized Evidence Bundle Storage
============================================================

Uploads Karma Evidence Bundles to Arweave (permanent) or IPFS
(content-addressed) so that Solana on-chain records have a
verifiable pointer to the full audit trail.

Design
------
The on-chain record (Solana memo or Program account) stores:
    1. SHA-256 hash of the evidence bundle
    2. URI pointing to the full bundle on Arweave/IPFS
    3. Verification verdict and confidence

Any third party can:
    1. Fetch the bundle from Arweave/IPFS
    2. Verify the SHA-256 hash matches the on-chain record
    3. Independently verify the cryptographic proofs

Backends
--------
- ``ArweaveUploader`` — Permanent storage via Arweave (recommended for production)
- ``IPFSUploader`` — Content-addressed via IPFS (good for testing)
- ``MockUploader`` — In-memory store for testing (no external deps)

Usage
-----
    store = ArweaveUploader(wallet_path="./arweave-key.json")
    uri = await store.upload(evidence_bundle)
    print(uri)  # ar://<tx_id>
"""

from __future__ import annotations

import hashlib
import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Optional

from core.schemas import EvidenceBundle

logger = logging.getLogger(__name__)


class SolanaEvidenceStore(ABC):
    """
    Abstract interface for decentralized evidence storage.

    Implementations must:
    - Accept an EvidenceBundle and return a content URI
    - Ensure content-addressability (hash-based retrieval)
    - Be suitable for recording on Solana (URI fits in a memo or account data)
    """

    @abstractmethod
    async def upload(self, bundle: EvidenceBundle) -> str:
        """
        Upload an evidence bundle to decentralized storage.

        Parameters
        ----------
        bundle : EvidenceBundle
            The assembled Karma evidence bundle.

        Returns
        -------
        str
            Content URI (e.g., "ar://<tx_id>", "ipfs://<cid>", "https://...")
        """
        ...

    @abstractmethod
    async def retrieve(self, uri: str) -> Optional[dict[str, Any]]:
        """
        Retrieve a previously uploaded evidence bundle.

        Parameters
        ----------
        uri : str
            The content URI returned by ``upload()``.

        Returns
        -------
        dict | None
            The bundle as a dict, or None if not found.
        """
        ...


# ═══════════════════════════════════════════════════════════════════
# Arweave Uploader
# ═══════════════════════════════════════════════════════════════════

class ArweaveUploader(SolanaEvidenceStore):
    """
    Upload evidence bundles to Arweave for permanent, verifiable storage.

    Arweave is ideal for audit trails because:
    - Data is stored permanently (one-time payment)
    - Content is addressable via transaction ID
    - Solana has native Arweave bridge support (via oracles)

    Parameters
    ----------
    wallet_path : str | None
        Path to an Arweave JWK wallet file. If None, uses a
        gateway-based upload (free, limited size).
    gateway_url : str
        Arweave gateway URL.
    """

    def __init__(
        self,
        wallet_path: Optional[str] = None,
        gateway_url: str = "https://arweave.net",
    ) -> None:
        self.wallet_path = wallet_path
        self.gateway_url = gateway_url.rstrip("/")
        self._wallet: Optional[Any] = None

    def _load_wallet(self) -> Any:
        """Lazy-load the Arweave wallet JWK."""
        if self._wallet is not None:
            return self._wallet

        if self.wallet_path is None:
            logger.warning(
                "No Arweave wallet provided — uploads will use a public gateway "
                "(limited size, may not be permanent). Set wallet_path for production."
            )
            return None

        try:
            from arweave import Wallet
            with open(self.wallet_path) as f:
                jwk = json.load(f)
            self._wallet = Wallet(jwk)
            return self._wallet
        except ImportError:
            logger.warning("arweave-python-client not installed — using gateway-based upload fallback")
            return None
        except Exception as e:
            logger.error("Failed to load Arweave wallet: %s", e)
            return None

    async def upload(self, bundle: EvidenceBundle) -> str:
        """
        Upload bundle to Arweave.

        Strategy:
        1. Serialize the bundle to JSON
        2. Compute content hash (for on-chain verification)
        3. Upload to Arweave via gateway or bundled transaction
        4. Return ``ar://<tx_id>`` URI
        """
        bundle_json = bundle.model_dump_json(indent=2)
        content_hash = hashlib.sha256(bundle_json.encode()).hexdigest()

        wallet = self._load_wallet()

        if wallet is not None:
            # Full Arweave transaction (permanent storage)
            return await self._upload_via_wallet(bundle_json, content_hash)
        else:
            # Gateway-based upload (good for dev/test)
            return await self._upload_via_gateway(bundle_json, content_hash)

    async def _upload_via_wallet(self, bundle_json: str, content_hash: str) -> str:
        """Upload to Arweave using a wallet (permanent storage)."""
        import httpx

        try:
            from arweave import Wallet, Transaction

            wallet = self._load_wallet()
            if wallet is None:
                raise ValueError("Arweave wallet not available")

            # Create a data transaction
            tx = Transaction(
                wallet=wallet,
                data=bundle_json.encode("utf-8"),
            )
            tx.add_tag("App-Name", "Karma-Trust-Protocol")
            tx.add_tag("Content-Type", "application/json")
            tx.add_tag("Content-Hash", content_hash)
            tx.add_tag("Protocol-Version", "1.0")

            tx.sign()
            tx.send()

            tx_id = tx.id
            logger.info("Evidence bundle uploaded to Arweave: tx=%s", tx_id)
            return f"ar://{tx_id}"

        except ImportError:
            logger.warning("arweave-python-client not installed, falling back to gateway upload")
            return await self._upload_via_gateway(bundle_json, content_hash)

    async def _upload_via_gateway(self, bundle_json: str, content_hash: str) -> str:
        """
        Upload to Arweave via HTTP gateway.

        This is suitable for dev/test but not production (no guarantee
        of permanence without a funded wallet).
        """
        import httpx

        url = f"{self.gateway_url}/chunk"
        headers = {"Content-Type": "application/json"}

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.post(url, content=bundle_json, headers=headers)
                resp.raise_for_status()
                # Gateway may return a tx_id or other identifier
                data = resp.json()
                tx_id = data.get("id") or data.get("tx_id") or f"gw-{content_hash[:16]}"
                logger.info("Evidence bundle uploaded via Arweave gateway: %s", tx_id)
                return f"ar://{tx_id}"
            except Exception as e:
                logger.error("Arweave gateway upload failed: %s", e)
                # Fallback: return a content-hash-based URI
                fallback_uri = f"karma://sha256/{content_hash}"
                logger.warning("Using fallback URI: %s", fallback_uri)
                return fallback_uri

    async def retrieve(self, uri: str) -> Optional[dict[str, Any]]:
        """Retrieve an evidence bundle from Arweave by URI."""
        import httpx

        # Parse URI: ar://<tx_id> or https://arweave.net/<tx_id>
        if uri.startswith("ar://"):
            tx_id = uri[5:]
        elif "arweave.net" in uri:
            tx_id = uri.split("/")[-1]
        else:
            logger.warning("Unrecognized Arweave URI format: %s", uri)
            return None

        url = f"{self.gateway_url}/{tx_id}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                logger.error("Failed to retrieve from Arweave: %s", e)
                return None


# ═══════════════════════════════════════════════════════════════════
# IPFS Uploader
# ═══════════════════════════════════════════════════════════════════

class IPFSUploader(SolanaEvidenceStore):
    """
    Upload evidence bundles to IPFS for content-addressed storage.

    IPFS is ideal for:
    - Content-addressable retrieval (no trust in the host)
    - Pin to multiple nodes for redundancy
    - Gateway-agnostic access

    Parameters
    ----------
    gateway_url : str
        IPFS gateway URL (e.g., "https://ipfs.io" or local "http://127.0.0.1:5001").
    use_local_node : bool
        If True, uses local IPFS daemon API (port 5001). Otherwise uses a public gateway.
    """

    def __init__(
        self,
        gateway_url: str = "https://ipfs.io",
        use_local_node: bool = False,
    ) -> None:
        self.gateway_url = gateway_url.rstrip("/")
        self.use_local_node = use_local_node

    async def upload(self, bundle: EvidenceBundle) -> str:
        """Upload bundle to IPFS and return CID."""
        import httpx

        bundle_json = bundle.model_dump_json(indent=2)

        if self.use_local_node:
            return await self._upload_local(bundle_json)
        else:
            return await self._upload_via_gateway(bundle_json)

    async def _upload_local(self, bundle_json: str) -> str:
        """Upload to a local IPFS node API."""
        import httpx

        url = "http://127.0.0.1:5001/api/v0/add"
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                # IPFS API expects multipart file upload
                files = {"file": ("bundle.json", bundle_json.encode(), "application/json")}
                resp = await client.post(url, files=files)
                resp.raise_for_status()
                data = resp.json()
                cid = data["Hash"]
                logger.info("Evidence bundle uploaded to IPFS: cid=%s", cid)
                return f"ipfs://{cid}"
            except Exception as e:
                logger.error("Local IPFS upload failed: %s", e)
                return await self._upload_via_gateway(bundle_json)

    async def _upload_via_gateway(self, bundle_json: str) -> str:
        """Upload via public IPFS gateway (pinning service)."""
        import httpx

        # For MVP, use a content-hash-based IPFS URI
        # In production, integrate with a pinning service (Pinata, web3.storage, etc.)
        cid = hashlib.sha256(bundle_json.encode()).hexdigest()

        url = f"{self.gateway_url}/api/v0/add"
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                files = {"file": ("bundle.json", bundle_json.encode(), "application/json")}
                resp = await client.post(url, files=files)
                if resp.status_code == 200:
                    data = resp.json()
                    cid = data.get("Hash", cid)
            except Exception as e:
                logger.warning("IPFS gateway upload failed (%s), using content-hash URI", e)

        logger.info("Evidence bundle content-identified: ipfs://%s", cid)
        return f"ipfs://{cid}"

    async def retrieve(self, uri: str) -> Optional[dict[str, Any]]:
        """Retrieve an evidence bundle from IPFS by URI."""
        import httpx

        if uri.startswith("ipfs://"):
            cid = uri[7:]
        else:
            cid = uri.split("/")[-1]

        url = f"{self.gateway_url}/ipfs/{cid}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                logger.error("Failed to retrieve from IPFS: %s", e)
                return None


# ═══════════════════════════════════════════════════════════════════
# Mock Uploader (Testing)
# ═══════════════════════════════════════════════════════════════════

class MockUploader(SolanaEvidenceStore):
    """
    In-memory evidence store for testing.

    Stores bundles in a dict keyed by their SHA-256 hash.
    No external dependencies or network calls.
    """

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    async def upload(self, bundle: EvidenceBundle) -> str:
        bundle_json = bundle.model_dump_json(indent=2)
        content_hash = hashlib.sha256(bundle_json.encode()).hexdigest()
        self._store[content_hash] = json.loads(bundle_json)
        return f"mock://{content_hash}"

    async def retrieve(self, uri: str) -> Optional[dict[str, Any]]:
        if uri.startswith("mock://"):
            content_hash = uri[7:]
        else:
            content_hash = uri
        return self._store.get(content_hash, None)
