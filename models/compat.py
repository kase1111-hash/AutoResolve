"""
Cross-database compatible JSON type for AutoResolve.

Provides a JSON column type that works with both PostgreSQL (JSONB)
and SQLite (TEXT with JSON serialization) so tests using SQLite
produce the same behavior as production PostgreSQL.
"""

import json

from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator


class JSONType(TypeDecorator):
    """JSON type that uses JSONB on PostgreSQL and TEXT on SQLite."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            return json.dumps(value)
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
