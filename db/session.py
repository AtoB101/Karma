"""
Karma — Async Database Session
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config.settings import settings
from db.models.orm import Base

logger = logging.getLogger(__name__)

engine = create_async_engine(
    settings.database_url,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    echo=settings.debug,
    future=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def _migrate_missing_columns(_conn_unused=None):
    """Dev-mode helper: add any ORM columns missing from actual SQLite tables."""
    from sqlalchemy import inspect as sa_inspect, text as sa_text

    async with engine.connect() as conn:
        def _sync_migrate(sync_conn):
            inspector = sa_inspect(sync_conn)
            tables = inspector.get_table_names()
            for table_name in tables:
                try:
                    mapper = next(
                        (m for m in Base.registry.mappers if m.local_table.name == table_name),
                        None,
                    )
                except Exception:
                    mapper = None
                if mapper is None:
                    continue
                orm_cols = {c.name: c for c in mapper.local_table.columns}
                db_cols = {c["name"] for c in inspector.get_columns(table_name)}
                for col_name, col in orm_cols.items():
                    if col_name not in db_cols:
                        col_type = _ddl_type(col.type, sync_conn.dialect)
                        stmt = f'ALTER TABLE "{table_name}" ADD COLUMN "{col_name}" {col_type}'
                        logger.info("auto_migrate adding column %s.%s (%s)", table_name, col_name, col_type)
                        try:
                            sync_conn.execute(sa_text(stmt))
                            sync_conn.commit()
                        except Exception:
                            sync_conn.rollback()
                            logger.warning(
                                "auto_migrate FAILED to add %s.%s as %s — the model now selects a "
                                "column the table does not have",
                                table_name,
                                col_name,
                                col_type,
                            )

        await conn.run_sync(_sync_migrate)


def _ddl_type(col_type, dialect) -> str:
    """Render a column type for the live dialect.

    ``str(col.type)`` yields generic names like "DATETIME", which Postgres
    rejects — the ALTER failed, was swallowed as a debug log, and the app only
    noticed when SQLAlchemy started selecting a column that was never added.
    Compiling against the real dialect gives TIMESTAMP WITHOUT TIME ZONE,
    DOUBLE PRECISION, ... so the column actually lands.
    """
    try:
        return col_type.compile(dialect=dialect)
    except Exception:
        return str(col_type)


async def init_db() -> None:
    """Create all tables. Use Alembic in production."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Run auto-migration after create_all, outside the transaction
    await _migrate_missing_columns(None)


async def drop_db() -> None:
    """Drop all tables. Tests only."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency."""
    async with get_session() as session:
        yield session
