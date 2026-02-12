"""
SQLAlchemy database models for AutoResolve.

Based on the database schema defined in the specification.
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4


def utc_now() -> datetime:
    """Return current UTC time as timezone-aware datetime."""
    return datetime.now(timezone.utc)

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.dialects.postgresql import UUID

from models.compat import JSONType
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    sessionmaker,
)

from app.config import get_settings


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class Issue(Base):
    """Issues table - tracks GitHub issues being processed."""

    __tablename__ = "issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    queue_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False, default=uuid4
    )
    github_issue_id: Mapped[int] = mapped_column(Integer, nullable=False)
    repo_full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    repo_url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    labels: Mapped[dict] = mapped_column(JSONType, default=list)
    author: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    github_created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    queued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    priority: Mapped[int] = mapped_column(Integer, default=3)
    status: Mapped[str] = mapped_column(String(50), default="pending")

    # Relationships
    validations: Mapped[list["Validation"]] = relationship(
        "Validation", back_populates="issue", cascade="all, delete-orphan"
    )
    fix_proposals: Mapped[list["FixProposal"]] = relationship(
        "FixProposal", back_populates="issue", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_issues_status", "status"),
        Index("idx_issues_repo", "repo_full_name"),
        Index("idx_issues_priority", "priority"),
        Index(
            "uq_issues_repo_issue",
            "repo_full_name",
            "github_issue_id",
            unique=True,
        ),
    )


class Validation(Base):
    """Validation results table."""

    __tablename__ = "validations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    issue_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("issues.id", ondelete="CASCADE"), nullable=False
    )
    valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    validity_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    match_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    error_signature: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    issue_context: Mapped[Optional[dict]] = mapped_column(JSONType, nullable=True)
    reproduction_result: Mapped[Optional[dict]] = mapped_column(JSONType, nullable=True)
    code_context: Mapped[Optional[dict]] = mapped_column(JSONType, nullable=True)
    sandbox_image: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    validated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    validation_duration: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Relationships
    issue: Mapped["Issue"] = relationship("Issue", back_populates="validations")

    __table_args__ = (Index("idx_validations_issue", "issue_id"),)


class FixProposal(Base):
    """Fix proposals table."""

    __tablename__ = "fix_proposals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    proposal_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False, default=uuid4
    )
    issue_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("issues.id", ondelete="CASCADE"), nullable=False
    )
    validation_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("validations.id"), nullable=True
    )
    suggested_patch: Mapped[str] = mapped_column(Text, nullable=False)
    parsed_diff: Mapped[Optional[dict]] = mapped_column(JSONType, nullable=True)
    affected_files: Mapped[dict] = mapped_column(JSONType, default=list)
    lines_added: Mapped[int] = mapped_column(Integer, default=0)
    lines_removed: Mapped[int] = mapped_column(Integer, default=0)
    llm_model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    generation_attempts: Mapped[int] = mapped_column(Integer, default=1)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    status: Mapped[str] = mapped_column(String(50), default="pending_audit")

    # Relationships
    issue: Mapped["Issue"] = relationship("Issue", back_populates="fix_proposals")
    validation: Mapped[Optional["Validation"]] = relationship("Validation")
    security_reports: Mapped[list["SecurityReport"]] = relationship(
        "SecurityReport", back_populates="proposal", cascade="all, delete-orphan"
    )
    approvals: Mapped[list["Approval"]] = relationship(
        "Approval", back_populates="proposal", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_proposals_issue", "issue_id"),
        Index("idx_proposals_status", "status"),
    )


class SecurityReport(Base):
    """Security reports table."""

    __tablename__ = "security_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False, default=uuid4
    )
    proposal_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("fix_proposals.id", ondelete="CASCADE"), nullable=False
    )
    has_vulnerabilities: Mapped[bool] = mapped_column(Boolean, nullable=False)
    risk_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    findings_count: Mapped[int] = mapped_column(Integer, default=0)
    findings_by_severity: Mapped[dict] = mapped_column(JSONType, default=dict)
    findings: Mapped[dict] = mapped_column(JSONType, default=list)
    scanners_used: Mapped[dict] = mapped_column(JSONType, default=list)
    dynamic_scan_passed: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    recommendation: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    scanned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    scan_duration: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Relationships
    proposal: Mapped["FixProposal"] = relationship(
        "FixProposal", back_populates="security_reports"
    )

    __table_args__ = (Index("idx_security_proposal", "proposal_id"),)


class Approval(Base):
    """Approvals table."""

    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    proposal_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("fix_proposals.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    approved_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    rejected_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    auto_merge: Mapped[bool] = mapped_column(Boolean, default=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    comment_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pr_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pr_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pr_merged: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )

    # Relationships
    proposal: Mapped["FixProposal"] = relationship(
        "FixProposal", back_populates="approvals"
    )

    __table_args__ = (
        Index("idx_approvals_proposal", "proposal_id"),
        Index("idx_approvals_status", "status"),
    )


class AuditLog(Base):
    """Audit log table for tracking all system events."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    entity_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    actor: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    details: Mapped[Optional[dict]] = mapped_column(JSONType, nullable=True)

    __table_args__ = (
        Index("idx_audit_timestamp", "timestamp"),
        Index("idx_audit_entity", "entity_type", "entity_id"),
    )


class MonitoredRepo(Base):
    """Monitored repositories table."""

    __tablename__ = "monitored_repos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repo_full_name: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False
    )
    webhook_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    webhook_secret: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    settings: Mapped[dict] = mapped_column(JSONType, default=dict)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    last_polled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (Index("idx_repos_enabled", "enabled"),)


# Database connection utilities

_engine = None
_session_factory = None


def get_engine():
    """Get or create the cached database engine."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.database.url,
            pool_size=settings.database.pool_size,
            pool_pre_ping=True,
        )
    return _engine


def get_session_factory():
    """Get or create the cached session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine())
    return _session_factory


def reset_engine():
    """Reset cached engine and session factory (for testing)."""
    global _engine, _session_factory
    _engine = None
    _session_factory = None


def init_db():
    """Initialize database tables."""
    engine = get_engine()
    Base.metadata.create_all(engine)


def get_db():
    """Get database session for FastAPI dependency injection."""
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_db_session():
    """Get a database session as a context manager for Celery tasks and modules.

    Usage:
        with get_db_session() as db:
            db.query(...)
            # auto-commits on success, rolls back on exception
    """
    from contextlib import contextmanager

    @contextmanager
    def _session_scope():
        SessionLocal = get_session_factory()
        session = SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    return _session_scope()
