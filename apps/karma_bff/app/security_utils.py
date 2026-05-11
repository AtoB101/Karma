"""Input validation and safe serialization for BFF."""

from __future__ import annotations

import html
import json
import re
from typing import Any

# trace_id: conservative allowlist (OpenManus / UUID / slug style)
_TRACE_ID_RE = re.compile(r"^[A-Za-z0-9_\-.:]{4,128}$")


def assert_valid_trace_id(trace_id: str) -> str:
    tid = str(trace_id or "").strip()
    if not _TRACE_ID_RE.match(tid):
        raise ValueError("invalid trace_id format")
    return tid


def safe_json_for_html(obj: Any) -> str:
    """Escape for embedding inside HTML (mitigate XSS from snapshot JSON)."""
    return html.escape(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True), quote=True)


def safe_text_for_html(s: str) -> str:
    return html.escape(s, quote=True)
