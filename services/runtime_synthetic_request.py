"""Build minimal Starlette ``Request`` objects for internal route delegation."""
from __future__ import annotations

from starlette.requests import Request

# The Runtime Gateway has already verified a Runtime Key when it hands a Request to an
# inner route, so the inner route must not try to re-resolve the actor from headers. The
# actor rides on scope["state"], which only in-process code can set.
#
# This replaces the old fake "karma_<id>_devruntimekey12" API key. That key only resolved
# while AUTH_ALLOW_DEV_KEY_FALLBACK was enabled, so in production every /runtime mutator
# died with 401 "authentication required for this operation".
RUNTIME_ACTOR_STATE_KEY = "karma_runtime_actor_id"


async def _empty_receive() -> dict:
    return {"type": "http.disconnect"}


def synthetic_request(
    *,
    headers: dict[str, str] | None = None,
    path: str = "/runtime/delegate",
    actor_id: str | None = None,
) -> Request:
    raw_headers = [
        (k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in (headers or {}).items()
    ]
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
    if actor_id:
        scope["state"] = {RUNTIME_ACTOR_STATE_KEY: actor_id}
    return Request(scope, _empty_receive)


def runtime_actor_id(request: Request) -> str | None:
    """Actor id stamped by the Runtime Gateway, when this Request came from it."""
    state = getattr(request, "state", None)
    if state is None:
        return None
    value = getattr(state, RUNTIME_ACTOR_STATE_KEY, None)
    return str(value) if value else None
