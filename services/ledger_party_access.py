"""
Ledger / voucher party binding — complements settlement party checks.

When ``ledger_require_party_actor`` and ``auth_enforce_protected_routes`` are enabled,
capacity mutations must act on the caller's own identity, and voucher mutations must
match the asserted buyer or seller identity to prevent cross-tenant credit manipulation.
"""
from __future__ import annotations

from fastapi import HTTPException, Request

from config.settings import settings

from services.settlement_party_access import require_actor


def ledger_party_binding_active() -> bool:
    return bool(settings.ledger_require_party_actor and settings.auth_enforce_protected_routes)


def require_ledger_identity(request: Request, identity_id: str) -> None:
    if not ledger_party_binding_active():
        return
    actor = require_actor(request)
    if actor != identity_id:
        raise HTTPException(
            403,
            "authenticated actor must match the target identity for this ledger operation",
        )
