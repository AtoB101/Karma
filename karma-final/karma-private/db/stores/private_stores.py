"""
PRIVATE — Store Dependency Injection for Private Runtime
Requires karma-trust-protocol (public SDK) installed:
    pip install -e ../karma-public
DO NOT commit to public repository.
"""
from __future__ import annotations

from core.schemas import AgentRole  # noqa: F401 - re-exported for convenience
from db.stores.receipt_store import PostgresReceiptStore
from db.stores.settlement_store import PostgresSettlementStore
from services.signing import Ed25519SigningService
from core.reputation.pg_store import PostgresReputationStore
from core.audit.trail import DecisionAuditTrail

_signing = None
_engine = None
_session_factory = None
_audit = None


def _get_engine():
    global _engine
    if _engine is None:
        from sqlalchemy.ext.asyncio import create_async_engine
        from config.settings import settings
        _engine = create_async_engine(
            settings.database_url,
            pool_size=settings.database_pool_size,
            echo=False,
        )
    return _engine


def _get_session_factory():
    global _session_factory
    if _session_factory is None:
        from sqlalchemy.ext.asyncio import async_sessionmaker
        _session_factory = async_sessionmaker(bind=_get_engine(), expire_on_commit=False)
    return _session_factory


def get_signing_service() -> Ed25519SigningService:
    global _signing
    if _signing is None:
        _signing = Ed25519SigningService()
    return _signing


def get_receipt_store() -> PostgresReceiptStore:
    return PostgresReceiptStore(_get_session_factory()())


def get_settlement_store() -> PostgresSettlementStore:
    return PostgresSettlementStore(_get_session_factory()())


def get_reputation_store() -> PostgresReputationStore:
    return PostgresReputationStore(_get_session_factory()())


def get_audit_trail() -> DecisionAuditTrail:
    global _audit
    if _audit is None:
        from config.settings import settings
        _audit = DecisionAuditTrail(settings.audit_log_path)
    return _audit
