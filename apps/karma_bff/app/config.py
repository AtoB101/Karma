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
