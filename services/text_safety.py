"""Reject unsafe user-controlled text before persistence (KSA2-008 / KSA2-011)."""
from __future__ import annotations

from collections.abc import Iterable


def validate_safe_storage_text(value: str, *, field: str) -> str:
    """
    Block NUL bytes and Unicode bidirectional override / isolate controls that can
    spoof filenames, logs, or UI rendering.
    """
    if "\x00" in value:
        raise ValueError(f"{field}: null bytes are not allowed")
    for ch in value:
        o = ord(ch)
        if 0x202A <= o <= 0x202E or 0x2066 <= o <= 0x2069:
            raise ValueError(f"{field}: Unicode bidirectional formatting characters are not allowed")
    return value


def validate_safe_storage_text_optional(value: str | None, *, field: str) -> str | None:
    if value is None:
        return None
    return validate_safe_storage_text(value, field=field)


def _iter_json_strings(obj: object) -> Iterable[str]:
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _iter_json_strings(v)
    elif isinstance(obj, list):
        for x in obj:
            yield from _iter_json_strings(x)
    elif isinstance(obj, str):
        yield obj


def validate_json_strings_safe(obj: object, *, field: str) -> None:
    """Apply ``validate_safe_storage_text`` to every string nested in JSON-like structures."""
    for s in _iter_json_strings(obj):
        validate_safe_storage_text(s, field=f"{field} (nested string)")
