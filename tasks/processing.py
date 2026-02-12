"""
Processing tasks for AutoResolve.

Handles the main issue processing pipeline.
"""

import asyncio
import logging
import shutil
from datetime import datetime, timezone
from typing import Any, Optional

from celery import shared_task

from app.config import get_settings
from models.database import (
    Approval,
)
from models.database import FixProposal as DBFixProposal
from models.database import (
    Issue,
)
from models.database import SecurityReport as DBSecurityReport
from models.database import (
    Validation,
    get_session_factory,
)

# Session management note:
# process_issue and create_pr use manual session management (get_session_factory)
# because they need intermediate commits and fine-grained transaction control.
# Simpler callers should use get_db_session() from models.database.
from models.schemas import QueuedIssue

logger = logging.getLogger(__name__)


def _run_async(coro: Any) -> Any:
    """Run an async coroutine from a synchronous Celery task.

    Uses asyncio.run() which creates a new event loop, runs the coroutine,
    and properly cleans up (closing async generators, executors, etc).
    """
    return asyncio.run(coro)


def _create_queued_issue(issue: Issue) -> QueuedIssue:
    """Create a QueuedIssue schema from a database Issue."""
    return QueuedIssue(
        queue_id=issue.queue_id,
        issue_id=issue.github_issue_id,
        repo_url=issue.repo_url,
        repo_full_name=issue.repo_full_name,
        title=issue.title,
        body=issue.body or "",
        labels=issue.labels or [],
        author=issue.author or "",
        created_at=issue.github_created_at or datetime.now(timezone.utc),
        priority=issue.priority,
    )


def _save_validation_result(db, issue_id: int, validation_result) -> Validation:
    """Save validation result to database."""
    validation = Validation(
        issue_id=issue_id,
        valid=validation_result.valid,
        validity_status=validation_result.validity_status,
        match_score=validation_result.reproduction_result.match_score,
        error_signature=validation_result.reproduction_result.error_signature,
        issue_context=validation_result.issue_context.model_dump(),
        reproduction_result=validation_result.reproduction_result.model_dump(),
        code_context=(
            validation_result.code_context.model_dump()
            if validation_result.code_context
            else None
        ),
        sandbox_image=validation_result.reproduction_result.sandbox_image,
        validation_duration=validation_result.validation_duration,
    )
    db.add(validation)
    db.commit()
    return validation


def _save_proposal(db, issue_id: int, validation_id: int, proposal) -> DBFixProposal:
    """Save fix proposal to database."""
    db_proposal = DBFixProposal(
        proposal_id=proposal.proposal_id,
        issue_id=issue_id,
        validation_id=validation_id,
        suggested_patch=proposal.suggested_patch,
        parsed_diff=(
            proposal.parsed_diff.model_dump() if proposal.parsed_diff else None
        ),
        affected_files=proposal.affected_files,
        lines_added=proposal.lines_added,
        lines_removed=proposal.lines_removed,
        llm_model=proposal.llm_model,
        generation_attempts=proposal.generation_attempts,
        status="pending_audit",
    )
    db.add(db_proposal)
    db.commit()
    return db_proposal


def _save_security_report(db, proposal_id: int, security_report) -> DBSecurityReport:
    """Save security report to database."""
    db_report = DBSecurityReport(
        report_id=security_report.report_id,
        proposal_id=proposal_id,
        has_vulnerabilities=security_report.has_vulnerabilities,
        risk_score=security_report.risk_score,
        findings_count=security_report.findings_count,
        findings_by_severity=security_report.findings_by_severity,
        findings=[f.model_dump() for f in security_report.findings],
        scanners_used=security_report.scanners_used,
        dynamic_scan_passed=security_report.dynamic_scan_passed,
        recommendation=security_report.recommendation,
        scan_duration=security_report.scan_duration,
    )
    db.add(db_report)
    db.commit()
    return db_report


def _request_approval(db, issue, db_proposal, proposal, security_report, validation_valid):
    """Post approval comment and create approval record."""
    from modules.approval import post_proposal_comment

    comment_id = _run_async(
        post_proposal_comment(
            repo_full_name=issue.repo_full_name,
            issue_number=issue.github_issue_id,
            proposal=proposal,
            security_report=security_report,
            reproduction_valid=validation_valid,
        )
    )

    approval = Approval(
        proposal_id=db_proposal.id, status="pending", comment_id=comment_id
    )
    db.add(approval)
    db.commit()

    # Schedule approval polling
    from tasks.polling import poll_approval

    poll_approval.apply_async(args=[db_proposal.id], countdown=300)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_issue(self, issue_id: int):
    """
    Main processing pipeline for an issue.

    Args:
        issue_id: Database ID of the issue to process
    """
    settings = get_settings()
    SessionLocal = get_session_factory()
    db = SessionLocal()
    repo_dir: Optional[str] = None

    try:
        # Load issue from database
        issue = db.query(Issue).filter(Issue.id == issue_id).first()
        if not issue:
            logger.error(f"Issue {issue_id} not found")
            return

        logger.info(f"Processing issue: {issue.repo_full_name}#{issue.github_issue_id}")
        issue.status = "processing"
        db.commit()

        queued = _create_queued_issue(issue)

        # Step 1: Validate
        from modules.validation import clone_repository, validate_issue

        validation_result = _run_async(validate_issue(queued))
        validation = _save_validation_result(db, issue_id, validation_result)

        if not validation_result.valid:
            logger.info(f"Issue {issue_id} not reproducible")
            issue.status = "not_reproducible"
            db.commit()
            return

        # Step 2: Generate fix
        repo_dir = clone_repository(queued.repo_url, depth=settings.validation.clone_depth)

        from modules.fix_generator import generate_fix

        proposal = _run_async(generate_fix(queued, validation_result, repo_dir))

        if not proposal:
            logger.warning(f"Failed to generate fix for issue {issue_id}")
            issue.status = "fix_failed"
            db.commit()
            return

        db_proposal = _save_proposal(db, issue_id, validation.id, proposal)

        # Step 3: Security audit
        from modules.security_auditor import audit_fix

        security_report = _run_async(
            audit_fix(proposal, repo_dir, validation_result.code_context.language)
        )
        _save_security_report(db, db_proposal.id, security_report)

        if security_report.recommendation == "reject":
            logger.warning(f"Fix rejected due to security concerns: {issue_id}")
            db_proposal.status = "security_rejected"
            issue.status = "security_rejected"
            db.commit()
            return

        db_proposal.status = "pending_approval"
        db.commit()

        # Step 4: Request approval
        _request_approval(
            db, issue, db_proposal, proposal, security_report, validation_result.valid
        )

        issue.status = "pending_approval"
        db.commit()
        logger.info(f"Issue {issue_id} processing complete, awaiting approval")

    except Exception as e:
        logger.error(f"Error processing issue {issue_id}: {e}", exc_info=True)
        try:
            issue.status = "failed"
            db.commit()
        except Exception:
            pass
        self.retry(exc=e)

    finally:
        if repo_dir:
            shutil.rmtree(repo_dir, ignore_errors=True)
        db.close()


@shared_task(bind=True, max_retries=2)
def create_pr(self, proposal_id: int, approved_by: str, auto_merge: bool = True):
    """
    Create a pull request for an approved fix.

    Args:
        proposal_id: Database ID of the proposal
        approved_by: Username who approved
        auto_merge: Whether to auto-merge the PR
    """
    SessionLocal = get_session_factory()
    db = SessionLocal()

    try:
        proposal = (
            db.query(DBFixProposal).filter(DBFixProposal.id == proposal_id).first()
        )
        if not proposal:
            logger.error(f"Proposal {proposal_id} not found")
            return

        issue = proposal.issue

        from models.schemas import ApprovalResult, FixProposal
        from modules.approval import create_pull_request

        # Create schema objects
        fix_proposal = FixProposal(
            proposal_id=proposal.proposal_id,
            issue_id=issue.github_issue_id,
            repo_full_name=issue.repo_full_name,
            suggested_patch=proposal.suggested_patch,
            affected_files=proposal.affected_files,
            lines_added=proposal.lines_added,
            lines_removed=proposal.lines_removed,
        )

        approval = ApprovalResult(
            status="approved", approved_by=approved_by, auto_merge=auto_merge
        )

        pr_result = _run_async(
            create_pull_request(fix_proposal, approval, issue.title)
        )

        # Update approval record
        db_approval = (
            db.query(Approval).filter(Approval.proposal_id == proposal_id).first()
        )

        if db_approval:
            db_approval.status = "approved"
            db_approval.approved_by = approved_by
            db_approval.pr_number = pr_result.pr_number
            db_approval.pr_url = pr_result.pr_url
            db_approval.pr_merged = pr_result.status == "merged"
            db_approval.resolved_at = datetime.now(timezone.utc)

        proposal.status = "approved"
        issue.status = "resolved" if pr_result.status == "merged" else "pr_created"
        db.commit()

        logger.info(f"Created PR #{pr_result.pr_number} for proposal {proposal_id}")

    except Exception as e:
        logger.error(
            f"Error creating PR for proposal {proposal_id}: {e}", exc_info=True
        )
        self.retry(exc=e)

    finally:
        db.close()
