"""
Processing tasks for AutoResolve.

Handles the main issue processing pipeline.
"""

import logging
import shutil
from datetime import datetime

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
from models.schemas import QueuedIssue

logger = logging.getLogger(__name__)


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

    try:
        # Load issue from database
        issue = db.query(Issue).filter(Issue.id == issue_id).first()
        if not issue:
            logger.error(f"Issue {issue_id} not found")
            return

        logger.info(f"Processing issue: {issue.repo_full_name}#{issue.github_issue_id}")

        # Update status
        issue.status = "processing"
        db.commit()

        # Create QueuedIssue for module functions
        queued = QueuedIssue(
            queue_id=issue.queue_id,
            issue_id=issue.github_issue_id,
            repo_url=issue.repo_url,
            repo_full_name=issue.repo_full_name,
            title=issue.title,
            body=issue.body or "",
            labels=issue.labels or [],
            author=issue.author or "",
            created_at=issue.github_created_at or datetime.utcnow(),
            priority=issue.priority
        )

        # Step 1: Validate
        import asyncio

        from modules.validation import clone_repository, validate_issue

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            validation_result = loop.run_until_complete(validate_issue(queued))
        finally:
            loop.close()

        # Save validation result
        validation = Validation(
            issue_id=issue_id,
            valid=validation_result.valid,
            validity_status=validation_result.validity_status,
            match_score=validation_result.reproduction_result.match_score,
            error_signature=validation_result.reproduction_result.error_signature,
            issue_context=validation_result.issue_context.model_dump(),
            reproduction_result=validation_result.reproduction_result.model_dump(),
            code_context=validation_result.code_context.model_dump() if validation_result.code_context else None,
            sandbox_image=validation_result.reproduction_result.sandbox_image,
            validation_duration=validation_result.validation_duration
        )
        db.add(validation)
        db.commit()

        if not validation_result.valid:
            logger.info(f"Issue {issue_id} not reproducible")
            issue.status = "not_reproducible"
            db.commit()
            return

        # Step 2: Generate fix
        repo_dir = clone_repository(queued.repo_url, depth=settings.validation.clone_depth)

        try:
            from modules.fix_generator import generate_fix

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            try:
                proposal = loop.run_until_complete(
                    generate_fix(queued, validation_result, repo_dir)
                )
            finally:
                loop.close()

            if not proposal:
                logger.warning(f"Failed to generate fix for issue {issue_id}")
                issue.status = "fix_failed"
                db.commit()
                return

            # Save proposal
            db_proposal = DBFixProposal(
                proposal_id=proposal.proposal_id,
                issue_id=issue_id,
                validation_id=validation.id,
                suggested_patch=proposal.suggested_patch,
                parsed_diff=proposal.parsed_diff.model_dump() if proposal.parsed_diff else None,
                affected_files=proposal.affected_files,
                lines_added=proposal.lines_added,
                lines_removed=proposal.lines_removed,
                llm_model=proposal.llm_model,
                generation_attempts=proposal.generation_attempts,
                status="pending_audit"
            )
            db.add(db_proposal)
            db.commit()

            # Step 3: Security audit
            from modules.security_auditor import audit_fix

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            try:
                security_report = loop.run_until_complete(
                    audit_fix(proposal, repo_dir, validation_result.code_context.language)
                )
            finally:
                loop.close()

            # Save security report
            db_report = DBSecurityReport(
                report_id=security_report.report_id,
                proposal_id=db_proposal.id,
                has_vulnerabilities=security_report.has_vulnerabilities,
                risk_score=security_report.risk_score,
                findings_count=security_report.findings_count,
                findings_by_severity=security_report.findings_by_severity,
                findings=[f.model_dump() for f in security_report.findings],
                scanners_used=security_report.scanners_used,
                dynamic_scan_passed=security_report.dynamic_scan_passed,
                recommendation=security_report.recommendation,
                scan_duration=security_report.scan_duration
            )
            db.add(db_report)
            db.commit()

            if security_report.recommendation == "reject":
                logger.warning(f"Fix rejected due to security concerns: {issue_id}")
                db_proposal.status = "security_rejected"
                issue.status = "security_rejected"
                db.commit()
                return

            db_proposal.status = "pending_approval"
            db.commit()

            # Step 4: Request approval
            from modules.approval import post_proposal_comment

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            try:
                comment_id = loop.run_until_complete(
                    post_proposal_comment(
                        repo_full_name=issue.repo_full_name,
                        issue_number=issue.github_issue_id,
                        proposal=proposal,
                        security_report=security_report,
                        reproduction_valid=validation_result.valid
                    )
                )
            finally:
                loop.close()

            # Create approval record
            approval = Approval(
                proposal_id=db_proposal.id,
                status="pending",
                comment_id=comment_id
            )
            db.add(approval)
            db.commit()

            issue.status = "pending_approval"
            db.commit()

            # Schedule approval polling
            from tasks.polling import poll_approval
            poll_approval.apply_async(
                args=[db_proposal.id],
                countdown=300  # Check after 5 minutes
            )

            logger.info(f"Issue {issue_id} processing complete, awaiting approval")

        finally:
            # Cleanup repo
            if repo_dir:
                shutil.rmtree(repo_dir, ignore_errors=True)

    except Exception as e:
        logger.error(f"Error processing issue {issue_id}: {e}", exc_info=True)
        try:
            issue.status = "failed"
            db.commit()
        except Exception:
            pass
        self.retry(exc=e)

    finally:
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
        proposal = db.query(DBFixProposal).filter(DBFixProposal.id == proposal_id).first()
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
            lines_removed=proposal.lines_removed
        )

        approval = ApprovalResult(
            status="approved",
            approved_by=approved_by,
            auto_merge=auto_merge
        )

        import asyncio

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            pr_result = loop.run_until_complete(
                create_pull_request(fix_proposal, approval, issue.title)
            )
        finally:
            loop.close()

        # Update approval record
        db_approval = db.query(Approval).filter(
            Approval.proposal_id == proposal_id
        ).first()

        if db_approval:
            db_approval.status = "approved"
            db_approval.approved_by = approved_by
            db_approval.pr_number = pr_result.pr_number
            db_approval.pr_url = pr_result.pr_url
            db_approval.pr_merged = pr_result.status == "merged"
            db_approval.resolved_at = datetime.utcnow()

        proposal.status = "approved"
        issue.status = "resolved" if pr_result.status == "merged" else "pr_created"
        db.commit()

        logger.info(f"Created PR #{pr_result.pr_number} for proposal {proposal_id}")

    except Exception as e:
        logger.error(f"Error creating PR for proposal {proposal_id}: {e}", exc_info=True)
        self.retry(exc=e)

    finally:
        db.close()
