"""URL safety for agent-initiated x402 fetches."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeX402UrlError(ValueError):
    pass


def _blocked_ip(addr) -> bool:
    return bool(
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def resolve_host_ips(host: str) -> list:
    """Every address a hostname currently resolves to ([] when it does not).

    Separated out so tests can stub it and so the caller can run it off the
    event loop. Note the residual gap: the name is resolved *here* and again by
    httpx when it connects, so a DNS answer that changes in between (rebinding)
    is not caught by this check alone.
    """
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except OSError:
        return []
    out = []
    for info in infos:
        raw = str(info[4][0]).split("%", 1)[0]
        try:
            addr = ipaddress.ip_address(raw)
        except ValueError:
            continue
        if addr not in out:
            out.append(addr)
    return out


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
        if allow_private_hosts:
            return url.strip()
        # A bare hostname used to be waved through, so a domain whose A record
        # points at 127.0.0.1 / 169.254.169.254 reached it anyway. Resolve first
        # and judge the addresses we would actually connect to.
        resolved = resolve_host_ips(host)
        if not resolved:
            raise UnsafeX402UrlError("hostname did not resolve: %s" % host)
        blocked = [str(a) for a in resolved if _blocked_ip(a)]
        if blocked:
            raise UnsafeX402UrlError(
                "hostname resolves to a private/reserved address (%s)" % ", ".join(blocked)
            )
        return url.strip()
    if _blocked_ip(ip) and not allow_private_hosts:
        raise UnsafeX402UrlError("private/reserved IP targets disabled")
    return url.strip()
