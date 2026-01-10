"""
Dependency injection container for AutoResolve.
"""

from functools import lru_cache
from typing import Generator

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from models.database import get_session_factory


@lru_cache()
def get_cached_settings() -> Settings:
    """Get cached settings instance."""
    return get_settings()


def get_db() -> Generator[Session, None, None]:
    """Get database session."""
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
