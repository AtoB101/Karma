"""The startup column auto-migrator must emit dialect-correct DDL.

A new ``UTCDateTime`` column was rendered as "DATETIME", which Postgres rejects;
the failed ALTER only logged at debug level, so the column was silently missing
until SQLAlchemy tried to select it. These tests pin the dialect-aware rendering.
"""
from __future__ import annotations

import pytest
from sqlalchemy import Float, Integer, JSON, String
from sqlalchemy.dialects import postgresql, sqlite

from db.models.orm import UTCDateTime
from db.session import _ddl_type


def test_datetime_column_compiles_for_postgres():
    assert _ddl_type(UTCDateTime(), postgresql.dialect()) == "TIMESTAMP WITHOUT TIME ZONE"


def test_plain_types_still_render():
    dialect = postgresql.dialect()
    assert _ddl_type(String(16), dialect).startswith("VARCHAR(16)")
    assert _ddl_type(Integer(), dialect) == "INTEGER"
    assert _ddl_type(Float(), dialect) in {"FLOAT", "DOUBLE PRECISION"}
    assert _ddl_type(JSON(), dialect) == "JSON"


def test_sqlite_still_gets_datetime():
    assert _ddl_type(UTCDateTime(), sqlite.dialect()) == "DATETIME"


def test_unrenderable_type_falls_back_instead_of_raising():
    class Weird:
        def compile(self, dialect=None):  # noqa: ANN001
            raise RuntimeError("cannot render")

        def __str__(self) -> str:
            return "WEIRD"

    assert _ddl_type(Weird(), postgresql.dialect()) == "WEIRD"


def test_registered_models_have_renderable_types():
    """Every mapped column must render for Postgres, or startup silently skips it."""
    from db.models.orm import Base

    dialect = postgresql.dialect()
    for mapper in Base.registry.mappers:
        for column in mapper.local_table.columns:
            rendered = _ddl_type(column.type, dialect)
            assert rendered and "DATETIME" not in rendered.upper(), (
                f"{mapper.local_table.name}.{column.name} renders as {rendered!r}"
            )
