"""Build minimal Starlette ``Request`` objects for internal route delegation."""
from __future__ import annotations

from starlette.requests import Request


async def _empty_receive() -> dict:
    return {"type": "http.disconnect"}


def synthetic_request(*, headers: dict[str, str], path: str = "/runtime/delegate") -> Request:
    raw_headers = [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in headers.items()]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "root_path": "",
        "client": ("127.0.0.1", 0),
        "server": ("testserver", 80),
        "headers": raw_headers,
    }
    return Request(scope, _empty_receive)
