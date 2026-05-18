"""URL safety for agent-initiated x402 fetches."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse


class UnsafeX402UrlError(ValueError):
    pass


def validate_x402_target_url(url: str, *, allow_private_hosts: bool = False) -> str:
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https"):
        raise UnsafeX402UrlError("only http/https URLs allowed")
    if not parsed.netloc:
        raise UnsafeX402UrlError("URL must include host")
    if "@" in parsed.netloc:
        raise UnsafeX402UrlError("userinfo in URL is not allowed")
    host = parsed.hostname or ""
    if not host:
        raise UnsafeX402UrlError("missing hostname")
    lowered = host.lower()
    if lowered in ("localhost", "127.0.0.1", "::1"):
        if not allow_private_hosts:
            raise UnsafeX402UrlError("localhost targets disabled")
        return url.strip()
    # Block path traversal in path segment only (basic)
    if ".." in (parsed.path or ""):
        raise UnsafeX402UrlError("path traversal not allowed")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return url.strip()
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
        if not allow_private_hosts:
            raise UnsafeX402UrlError("private/reserved IP targets disabled")
    return url.strip()
