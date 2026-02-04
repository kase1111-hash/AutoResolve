"""
Pydantic schemas for AutoResolve.

Defines all data transfer objects used across the application.
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    """Return current UTC time as timezone-aware datetime."""
    return datetime.now(timezone.utc)

# =============================================================================
# Monitoring Module Schemas
# =============================================================================


class QueuedIssue(BaseModel):
    """Issue queued for processing."""

    queue_id: UUID = Field(default_factory=uuid4)
    issue_id: int  # GitHub issue number
    repo_url: str  # https://github.com/org/repo
    repo_full_name: str  # org/repo
    title: str
    body: str
    labels: list[str] = []
    author: str
    created_at: datetime
    queued_at: datetime = Field(default_factory=_utc_now)
    priority: int = 3  # 1 (high) - 5 (low)
    status: str = "pending"  # pending | processing | completed | failed


class GitHubWebhookPayload(BaseModel):
    """Parsed GitHub webhook payload."""

    action: str
    issue: dict
    repository: dict
    sender: dict


# =============================================================================
# Validation Module Schemas
# =============================================================================


class EnvironmentInfo(BaseModel):
    """Environment information from issue parsing."""

    os: Optional[str] = None
    python_version: Optional[str] = None
    dependencies: list[str] = []


class IssueContext(BaseModel):
    """Structured context extracted from an issue."""

    error_type: Optional[str] = None
    error_message: Optional[str] = None
    affected_files: list[str] = []
    affected_functions: list[str] = []
    stack_trace: Optional[str] = None
    reproduction_steps: list[str] = []
    expected_behavior: Optional[str] = None
    actual_behavior: Optional[str] = None
    environment: EnvironmentInfo = EnvironmentInfo()
    code_snippets: list[str] = []
    parse_confidence: float = 0.0


class ReproductionResult(BaseModel):
    """Result of issue reproduction in sandbox."""

    valid: bool
    validity_status: str  # confirmed | partial | not_reproduced | error
    match_score: float  # 0.0 - 1.0
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    error_signature: Optional[str] = None
    execution_time: float = 0.0
    sandbox_image: str = ""
    reproduced_at: datetime = Field(default_factory=_utc_now)


class FunctionContext(BaseModel):
    """Context for a specific function."""

    file: str
    name: str
    start_line: int
    end_line: int
    source: str
    imports: list[str] = []


class CodeContext(BaseModel):
    """Code context for fix generation."""

    affected_files: list[str]
    functions: list[FunctionContext] = []
    error_signature: str = ""
    test_command: str = ""
    language: str = ""
    repo_commit: str = ""  # SHA of tested commit


class ValidationResult(BaseModel):
    """Complete validation result for an issue."""

    issue_id: int
    repo_full_name: str
    valid: bool
    validity_status: str
    issue_context: IssueContext
    reproduction_result: ReproductionResult
    code_context: Optional[CodeContext] = None
    validated_at: datetime = Field(default_factory=_utc_now)
    validation_duration: float = 0.0


# =============================================================================
# Fix Generation Module Schemas
# =============================================================================


class DiffLine(BaseModel):
    """Single line in a diff."""

    type: str  # context | add | remove
    content: str
    old_lineno: Optional[int] = None
    new_lineno: Optional[int] = None


class DiffHunk(BaseModel):
    """A hunk within a diff."""

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[DiffLine] = []


class FileDiff(BaseModel):
    """Diff for a single file."""

    path: str
    old_path: Optional[str] = None  # For renames
    hunks: list[DiffHunk] = []
    is_new: bool = False
    is_deleted: bool = False


class ParsedDiff(BaseModel):
    """Parsed unified diff."""

    files: list[FileDiff] = []


class FixProposal(BaseModel):
    """Proposed fix for an issue."""

    proposal_id: UUID = Field(default_factory=uuid4)
    issue_id: int
    repo_full_name: str
    suggested_patch: str  # Unified diff text
    parsed_diff: Optional[ParsedDiff] = None
    affected_files: list[str] = []
    lines_added: int = 0
    lines_removed: int = 0
    llm_model: str = ""
    generation_attempts: int = 1
    generated_at: datetime = Field(default_factory=_utc_now)
    status: str = "pending_audit"  # pending_audit | audited | approved | rejected


class FixValidation(BaseModel):
    """Result of fix validation."""

    valid: bool
    error: Optional[str] = None
    details: Optional[str] = None
    parsed_diff: Optional[ParsedDiff] = None


# =============================================================================
# Security Audit Module Schemas
# =============================================================================


class Finding(BaseModel):
    """Security finding from a scanner."""

    finding_id: UUID = Field(default_factory=uuid4)
    scanner: str  # bandit | semgrep | custom
    rule_id: str
    cwe: Optional[str] = None  # e.g., CWE-78
    owasp: Optional[str] = None  # e.g., A03:2021
    severity: str  # critical | high | medium | low | info
    confidence: str = "medium"  # high | medium | low
    file: str
    line_start: int
    line_end: int
    code_snippet: str = ""
    message: str
    recommendation: Optional[str] = None
    false_positive: bool = False
    in_new_code: bool = True


class DynamicScanResult(BaseModel):
    """Result of dynamic security analysis."""

    passed: bool
    stdout: str = ""
    stderr: str = ""
    error: Optional[str] = None
    execution_time: float = 0.0


class SecurityReport(BaseModel):
    """Complete security audit report."""

    report_id: UUID = Field(default_factory=uuid4)
    proposal_id: UUID
    has_vulnerabilities: bool
    risk_score: float  # 0.0 - 1.0
    findings_count: int = 0
    findings_by_severity: dict[str, int] = {}
    findings: list[Finding] = []
    critical_findings: list[Finding] = []
    scanners_used: list[str] = []
    dynamic_scan_passed: Optional[bool] = None
    scan_duration: float = 0.0
    scanned_at: datetime = Field(default_factory=_utc_now)
    recommendation: str = "review"  # approve | review | reject


# =============================================================================
# Approval Module Schemas
# =============================================================================


class ApprovalResult(BaseModel):
    """Result of approval polling."""

    status: str  # pending | approved | rejected | expired | regenerate
    approved_by: Optional[str] = None
    rejected_by: Optional[str] = None
    auto_merge: bool = True
    rejection_reason: Optional[str] = None
    feedback: Optional[str] = None  # For regenerate requests
    resolved_at: Optional[datetime] = None


class PullRequestResult(BaseModel):
    """Result of PR creation."""

    pr_number: int
    pr_url: str
    branch_name: str
    status: str  # open | merged | closed
    checks_passed: Optional[bool] = None
    merged_at: Optional[datetime] = None
    merged_by: Optional[str] = None


# =============================================================================
# API Schemas
# =============================================================================


class RepoCreate(BaseModel):
    """Request to add a monitored repository."""

    repo_full_name: str
    settings: dict = {}


class RepoResponse(BaseModel):
    """Response for repository operations."""

    id: int
    repo_full_name: str
    webhook_id: Optional[int] = None
    enabled: bool = True
    added_at: datetime


class IssueResponse(BaseModel):
    """Response for issue operations."""

    id: int
    github_issue_id: int
    repo_full_name: str
    title: str
    status: str
    validation: Optional[dict] = None
    proposal: Optional[dict] = None
    approval: Optional[dict] = None


class ProposalResponse(BaseModel):
    """Response for proposal operations."""

    proposal_id: UUID
    issue_id: int
    repo_full_name: str
    affected_files: list[str]
    lines_added: int
    lines_removed: int
    status: str
    generated_at: datetime


class StatsResponse(BaseModel):
    """System statistics response."""

    total_issues_processed: int = 0
    issues_by_status: dict[str, int] = {}
    total_proposals: int = 0
    proposals_approved: int = 0
    proposals_rejected: int = 0
    average_fix_time_seconds: float = 0.0
    security_findings_blocked: int = 0


class HealthResponse(BaseModel):
    """Health check response."""

    status: str  # healthy | degraded | unhealthy
    version: str
    database: str  # connected | disconnected
    redis: str  # connected | disconnected
    celery: str  # connected | disconnected


# =============================================================================
# Event Schemas
# =============================================================================


class NotificationEvent(BaseModel):
    """Event for notification dispatch."""

    event_type: str
    repo_full_name: str
    issue_id: Optional[int] = None
    proposal_id: Optional[UUID] = None
    details: dict = {}
    timestamp: datetime = Field(default_factory=_utc_now)
