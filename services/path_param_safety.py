"""
Reject path parameters that are unusably long or inject Redis / log metacharacters.

Used for externally-controlled URL segments (task_id, bundle_id, receipt_id, etc.).
"""
from __future__ import annotations

import re

from fastapi import HTTPException

_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9_.-]{1,256}$")


def validate_public_url_segment(name: str, value: str) -> str:
    if not _SAFE_SEGMENT.match(value):
        raise HTTPException(
            status_code=400,
            detail=f"invalid {name}: allowed characters are [A-Za-z0-9_.-], max length 256",
        )
    return value
