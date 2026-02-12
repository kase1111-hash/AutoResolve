"""
Cross-database compatible JSON type for AutoResolve.

Provides a JSON column type that works with both PostgreSQL (JSONB)
and SQLite (TEXT with JSON serialization) so tests using SQLite
produce the same behavior as production PostgreSQL.
"""

import json
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator


def _json_default(obj):
    """Handle datetime and UUID objects during JSON serialization."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, UUID):
        return str(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


class JSONType(TypeDecorator):
    """JSON type that uses JSONB on PostgreSQL and TEXT on SQLite."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            return json.dumps(value, default=_json_default)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            return json.loads(value)
        return value

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import JSONB

            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(Text())
