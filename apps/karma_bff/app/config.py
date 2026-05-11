"""Environment-driven BFF config."""

from __future__ import annotations

import os


def integration_secret() -> str:
    return os.environ.get("BFF_INTEGRATION_SECRET", "").strip()


def webhook_secret() -> str:
    return os.environ.get("BFF_WEBHOOK_SECRET", "").strip() or integration_secret()


def database_path() -> str:
    return os.environ.get("BFF_DATABASE_PATH", "/tmp/karma_bff.db").strip()


def public_base_url() -> str:
    return os.environ.get("BFF_PUBLIC_BASE_URL", "http://127.0.0.1:8820").rstrip("/")


def cors_allow_origins() -> list[str]:
    raw = os.environ.get("BFF_CORS_ALLOW_ORIGINS", "").strip()
    if raw == "*":
        return ["*"]
    if raw:
        return [x.strip() for x in raw.split(",") if x.strip()]
    return ["*"]


def trusted_hosts() -> list[str] | None:
    raw = os.environ.get("BFF_TRUSTED_HOSTS", "").strip()
    if not raw:
        return None
    return [x.strip() for x in raw.split(",") if x.strip()]


def rate_limit_public_per_minute() -> int:
    return max(10, int(os.environ.get("BFF_RATE_LIMIT_PUBLIC_PER_MIN", "120")))


def rate_limit_integration_per_minute() -> int:
    return max(20, int(os.environ.get("BFF_RATE_LIMIT_INTEGRATION_PER_MIN", "300")))


def max_body_bytes() -> int:
    return max(4096, int(os.environ.get("BFF_MAX_BODY_BYTES", str(256 * 1024))))
