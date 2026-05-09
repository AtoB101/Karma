"""
Karma — MinIO / S3 Object Store
Persists evidence bundles and full receipt payloads.
"""
from __future__ import annotations

import io
import json
from typing import Any

from minio import Minio
from minio.error import S3Error

from config.settings import settings
from core.evidence.bundle_builder import ObjectStore
from core.schemas import EvidenceBundle, ExecutionReceipt


def get_minio_client() -> Minio:
    return Minio(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )


async def ensure_buckets(client: Minio) -> None:
    for bucket in [settings.minio_bucket_evidence, settings.minio_bucket_receipts]:
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)


class MinIOObjectStore(ObjectStore):
    """
    Stores evidence bundles and receipts in MinIO/S3.
    Path format: bundles/{task_id}/{bundle_id}.json
    """

    def __init__(self, client: Minio | None = None):
        self._client = client or get_minio_client()
        self._bucket = settings.minio_bucket_evidence

    async def save_bundle(
        self,
        bundle: EvidenceBundle,
        receipts: list[ExecutionReceipt],
    ) -> str:
        payload = {
            "bundle":   bundle.model_dump(mode="json"),
            "receipts": [r.model_dump(mode="json") for r in receipts],
        }
        data = json.dumps(payload, default=str).encode()
        path = f"bundles/{bundle.task_id}/{bundle.bundle_id}.json"

        self._client.put_object(
            bucket_name=self._bucket,
            object_name=path,
            data=io.BytesIO(data),
            length=len(data),
            content_type="application/json",
            metadata={
                "task_id":   bundle.task_id,
                "bundle_id": bundle.bundle_id,
                "steps":     str(bundle.total_steps),
            },
        )
        return path

    async def load_bundle(self, storage_path: str) -> dict[str, Any]:
        try:
            response = self._client.get_object(self._bucket, storage_path)
            return json.loads(response.read())
        except S3Error as e:
            raise FileNotFoundError(f"Bundle not found at {storage_path}: {e}")

    async def save_receipt(self, receipt: ExecutionReceipt) -> str:
        data = receipt.model_dump(mode="json")
        raw = json.dumps(data, default=str).encode()
        path = f"receipts/{receipt.task_id}/{receipt.receipt_id}.json"

        self._client.put_object(
            bucket_name=settings.minio_bucket_receipts,
            object_name=path,
            data=io.BytesIO(raw),
            length=len(raw),
            content_type="application/json",
        )
        return path

    async def delete_bundle(self, storage_path: str) -> None:
        try:
            self._client.remove_object(self._bucket, storage_path)
        except S3Error:
            pass

    def presigned_url(self, storage_path: str, expires_seconds: int = 3600) -> str:
        """Generate a time-limited pre-signed download URL."""
        from datetime import timedelta
        return self._client.presigned_get_object(
            self._bucket,
            storage_path,
            expires=timedelta(seconds=expires_seconds),
        )
