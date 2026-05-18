"""UTC-safe time helpers for tests (avoid naive local datetime.utcnow() drift)."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone


def unix_now_utc() -> int:
    return int(time.time())


def future_deadline_unix(*, offset_seconds: int = 600) -> int:
    return unix_now_utc() + offset_seconds


def utc_naive_datetime(*, offset: timedelta | None = None) -> datetime:
    """Naive UTC datetime for APIs that store UTC without tzinfo."""
    base = datetime.now(timezone.utc).replace(tzinfo=None)
    if offset:
        return base + offset
    return base
