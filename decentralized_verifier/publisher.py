"""
Karma Decentralized Verification — Evidence Publisher
======================================================
Dual-publishes evidence bundles to IPFS (trust anchor) and MinIO (cache).

  IPFS CID  →  trust anchor for verifier nodes
  MinIO     →  local cache / fast retrieval fallback

Graceful degradation: IPFS failures never crash publication — the bundle
is hashed and optionally MinIO-cached regardless.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Callable, Optional

import aiohttp

from decentralized_verifier import EvidencePublication, utc_now_iso
from decentralized_verifier.rules.hashing import evidence_hash

logger = logging.getLogger(__name__)

# ── type aliases ──────────────────────────────────────────────────

#: Signature callback: (message: str) -> str  (hex signature)
SignerCallback = Callable[[str], str]


# ═══════════════════════════════════════════════════════════════════
# EvidencePublisher
# ═══════════════════════════════════════════════════════════════════

class EvidencePublisher:
    """
    Publish an EvidenceBundle to decentralized storage.

    Dual-path strategy:
      1. IPFS  →  CID becomes the canonical trust anchor
      2. MinIO →  optional fast-retrieval cache

    Parameters
    ----------
    ipfs_gateway:
        Base URL for the IPFS HTTP gateway (e.g. ``https://ipfs.io``)
        or a local daemon (``http://127.0.0.1:5001``).
        The publisher will try the add-endpoint of this gateway.
    minio_client:
        Pre-configured MinIO client object (optional).  Must expose
        ``put_object(bucket, key, data, length)`` method.
    signer:
        Optional signing callback.  Called with the concatenation
        ``evidence_hash + cid + published_at`` (hex-encoded bytes).
        Must return a hex-encoded signature string.
    """

    # ── constructor ───────────────────────────────────────────────

    def __init__(
        self,
        *,
        ipfs_gateway: str = "https://ipfs.io",
        minio_client: Any = None,
        signer: Optional[SignerCallback] = None,
    ) -> None:
        self._ipfs_gateway = ipfs_gateway.rstrip("/")
        self._minio = minio_client
        self._signer = signer

        # Resolve IPFS add URL: if the gateway is a local daemon
        # (port 5001), use its native API.  Otherwise treat it as a
        # public gateway with the same endpoint pattern.
        self._ipfs_add_url = f"{self._ipfs_gateway}/api/v0/add"

    # ── public API ────────────────────────────────────────────────

    async def publish(
        self,
        bundle: dict[str, Any],
        publisher_id: str,
    ) -> EvidencePublication:
        """
        Publish an evidence bundle.

        Steps
        -----
        1. Compute deterministic ``evidence_hash`` (canonical JSON → SHA-256).
        2. Upload to IPFS — CID returned is the trust anchor.
        3. Optionally cache the same JSON in MinIO.
        4. Sign ``(evidence_hash + cid + published_at)`` if a signer is
           configured.

        Returns
        -------
        EvidencePublication
            Populated with at least ``evidence_hash``.  ``cid`` may be
            empty if IPFS was unreachable.

        Raises
        ------
        Nothing — storage failure is degraded gracefully.
        """
        published_at = utc_now_iso()

        # 1 ── compute evidence hash (always succeeds) ─────────────
        eh = evidence_hash(bundle)

        # 2 ── upload to IPFS ─────────────────────────────────────
        cid, storage_provider = await self._upload_to_ipfs(bundle)
        if not cid:
            storage_provider = "none"

        # 3 ── upload to MinIO (best-effort cache) ────────────────
        if self._minio is not None:
            try:
                await self._upload_to_minio(bundle, eh)
                if storage_provider == "ipfs":
                    storage_provider = "ipfs+minio"
                else:
                    storage_provider = "minio"
            except Exception:
                logger.warning("MinIO upload failed for bundle hash=%s", eh, exc_info=True)

        # 4 ── sign the publication ────────────────────────────────
        signature = ""
        if self._signer is not None and cid:
            signature = self._sign_proof(eh, cid, published_at)

        # 5 ── assemble publication record ────────────────────────
        bundle_id = bundle.get("bundle_id", "")
        task_id = bundle.get("task_id", "")

        return EvidencePublication(
            id=f"pub-{bundle_id or eh[:12]}",
            task_id=task_id,
            bundle_id=bundle_id,
            evidence_hash=eh,
            cid=cid,
            storage_provider=storage_provider,
            published_at=published_at,
            publisher_actor=publisher_id,
            publisher_signature=signature,
        )

    async def verify_publication(
        self,
        cid: str,
        expected_hash: str,
    ) -> bool:
        """
        Verify that a published bundle matches its expected hash.

        Fetches the JSON from IPFS via the configured gateway, re-
        computes the evidence hash, and compares against
        *expected_hash*.

        Returns ``True`` on match, ``False`` on any mismatch or
        fetch failure.
        """
        try:
            raw = await self._fetch_from_ipfs(cid)
            bundle = json.loads(raw)
            recomputed = evidence_hash(bundle)
            return recomputed == expected_hash
        except Exception:
            logger.warning(
                "verify_publication failed for cid=%s", cid, exc_info=True,
            )
            return False

    # ── IPFS helpers ──────────────────────────────────────────────

    async def _upload_to_ipfs(self, bundle: dict[str, Any]) -> tuple[str, str]:
        """
        Upload canonical JSON to IPFS via HTTP API.

        Returns ``(cid, "ipfs")`` on success, ``("", "")`` on failure.
        """
        payload = canonical_json_bytes(bundle)
        data = aiohttp.FormData()
        data.add_field("file", payload, filename="evidence.json", content_type="application/json")

        for attempt in range(2):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(self._ipfs_add_url, data=data, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                        if resp.status == 200:
                            result = await resp.json()
                            cid = result.get("Hash", "")
                            if cid:
                                logger.info("IPFS upload OK  cid=%s", cid)
                                return cid, "ipfs"

                        logger.warning(
                            "IPFS add returned %d on attempt %d", resp.status, attempt + 1,
                        )
            except Exception:
                logger.warning(
                    "IPFS upload attempt %d failed", attempt + 1, exc_info=True,
                )

        logger.error("IPFS upload exhausted retries — evidence_hash only")
        return "", ""

    async def _fetch_from_ipfs(self, cid: str) -> bytes:
        """
        Fetch raw content from IPFS by CID.

        Raises on any failure (callers handle gracefully).
        """
        url = f"{self._ipfs_gateway}/api/v0/cat?arg={cid}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"IPFS cat returned {resp.status}")
                return await resp.read()

    # ── MinIO helper ─────────────────────────────────────────────

    async def _upload_to_minio(
        self,
        bundle: dict[str, Any],
        bundle_hash: str,
    ) -> None:
        """
        Cache the canonical JSON in MinIO (best-effort).

        Key layout:  ``evidence/{hash[:2]}/{hash}.json``
        """
        payload = canonical_json_bytes(bundle)
        bucket = "karma-evidence"
        key = f"evidence/{bundle_hash[:2]}/{bundle_hash}.json"

        # MinIO's put_object signature: bucket, object_name, data, length.
        # We call it in a thread to avoid blocking the event loop.
        import asyncio

        await asyncio.to_thread(
            self._minio.put_object,
            bucket,
            key,
            payload,
            len(payload),
        )
        logger.info("MinIO cache OK  key=%s", key)

    # ── signing ──────────────────────────────────────────────────

    def _sign_proof(
        self,
        bundle_hash: str,
        cid: str,
        published_at: str,
    ) -> str:
        """
        Generate a publisher signature over the publication proof.

        Message format:  ``SHA-256(evidence_hash || cid || published_at)``
        The hex digest of that concatenation is passed to the signer
        callback, which returns a hex signature.
        """
        message = bundle_hash + cid + published_at
        digest = hashlib.sha256(message.encode("utf-8")).hexdigest()
        assert self._signer is not None  # guarded by caller
        return self._signer(digest)


# ═══════════════════════════════════════════════════════════════════
# helpers
# ═══════════════════════════════════════════════════════════════════

def canonical_json_bytes(obj: dict[str, Any]) -> bytes:
    """
    Serialize a dict to canonical JSON bytes.

    Sorted keys, no whitespace — identical to the hashing module's
    convention so that evidence bundles have a single canonical form.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
