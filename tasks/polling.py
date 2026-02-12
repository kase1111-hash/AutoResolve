"""
Polling tasks for AutoResolve.

Handles approval polling and repository polling.
"""

import logging
from datetime import datetime, timedelta, timezone

from celery import shared_task

from app.config import get_settings
from models.database import (
    Approval,
)
from models.database import FixProposal as DBFixProposal
from models.database import (
    Issue,
    MonitoredRepo,
    get_session_factory,
)

logger = logging.getLogger(__name__)


@shared_task
def poll_approval(proposal_id: int):
    """
    Check for maintainer response on a proposal.

    Args:
        proposal_id: Database ID of the proposal
    """
    settings = get_settings()
    SessionLocal = get_session_factory()
    db = SessionLocal()

    try:
        proposal = (
            db.query(DBFixProposal).filter(DBFixProposal.id == proposal_id).first()
        )
        if not proposal:
            logger.error(f"Proposal {proposal_id} not found")
            return

        if proposal.status not in ("pending_approval", "pending_audit"):
            logger.debug(f"Proposal {proposal_id} no longer pending: {proposal.status}")
            return

        issue = proposal.issue

        from models.schemas import FixProposal
        from modules.approval import handle_expiry, handle_rejection, poll_for_approval

        # Create schema object
        fix_proposal = FixProposal(
            proposal_id=proposal.proposal_id,
            issue_id=issue.github_issue_id,
            repo_full_name=issue.repo_full_name,
            suggested_patch=proposal.suggested_patch,
            affected_files=proposal.affected_files,
            generated_at=proposal.generated_at,
        )

        import asyncio

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            result = loop.run_until_complete(
                poll_for_approval(
                    repo_full_name=issue.repo_full_name,
                    issue_number=issue.github_issue_id,
                    proposal=fix_proposal,
                )
            )
        finally:
            loop.close()

        if result.status == "approved":
            logger.info(f"Proposal {proposal_id} approved by {result.approved_by}")

            # Trigger PR creation
            from tasks.processing import create_pr

            create_pr.delay(proposal_id, result.approved_by, result.auto_merge)

        elif result.status == "rejected":
            logger.info(f"Proposal {proposal_id} rejected by {result.rejected_by}")

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(handle_rejection(fix_proposal, result))
            finally:
                loop.close()

            # Update database
            db_approval = (
                db.query(Approval).filter(Approval.proposal_id == proposal_id).first()
            )
            if db_approval:
                db_approval.status = "rejected"
                db_approval.rejected_by = result.rejected_by
                db_approval.rejection_reason = result.rejection_reason
                db_approval.resolved_at = datetime.now(timezone.utc)

            proposal.status = "rejected"
            issue.status = "rejected"
            db.commit()

        elif result.status == "expired":
            logger.info(f"Proposal {proposal_id} expired")

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(handle_expiry(fix_proposal))
            finally:
                loop.close()

            # Update database
            db_approval = (
                db.query(Approval).filter(Approval.proposal_id == proposal_id).first()
            )
            if db_approval:
                db_approval.status = "expired"
                db_approval.resolved_at = datetime.now(timezone.utc)

            proposal.status = "expired"
            issue.status = "expired"
            db.commit()

        elif result.status == "regenerate":
            logger.info(f"Regeneration requested for proposal {proposal_id}")

            # TODO: Trigger fix regeneration with feedback
            proposal.status = "regenerating"
            db.commit()

            # Re-schedule polling for the new proposal
            poll_approval.apply_async(args=[proposal_id], countdown=600)

        else:
            # Still pending - schedule next check
            poll_approval.apply_async(
                args=[proposal_id],
                countdown=settings.approval.poll_interval_minutes * 60,
            )

    except Exception as e:
        logger.error(
            f"Error polling approval for proposal {proposal_id}: {e}", exc_info=True
        )
        # Re-schedule on error
        poll_approval.apply_async(args=[proposal_id], countdown=300)

    finally:
        db.close()


@shared_task
def poll_repositories():
    """
    Poll all enabled repositories for new issues.

    Fallback mechanism for missed webhooks.
    """
    settings = get_settings()
    SessionLocal = get_session_factory()
    db = SessionLocal()

    try:
        # Get enabled repos from database
        repos = db.query(MonitoredRepo).filter(MonitoredRepo.enabled == True).all()
        repo_names = [r.repo_full_name for r in repos]

        # Also include repos from config
        repo_names.extend(settings.monitored_repos)
        repo_names = list(set(repo_names))

        if not repo_names:
            logger.debug("No repositories to poll")
            return

        from modules.monitoring import poll_repositories

        queued = poll_repositories(
            repos=repo_names, since_minutes=settings.monitoring.poll_lookback_minutes
        )

        # Update last_polled_at
        for repo in repos:
            repo.last_polled_at = datetime.now(timezone.utc)
        db.commit()

        if queued:
            logger.info(f"Polling queued {len(queued)} new issues")

            # Trigger processing for each new issue
            for issue in queued:
                from tasks.processing import process_issue

                # Find the database ID
                db_issue = (
                    db.query(Issue).filter(Issue.queue_id == issue.queue_id).first()
                )

                if db_issue:
                    process_issue.delay(db_issue.id)

    except Exception as e:
        logger.error(f"Error polling repositories: {e}", exc_info=True)

    finally:
        db.close()


@shared_task
def cleanup_expired_proposals():
    """
    Clean up expired proposals that were never resolved.

    Runs daily to archive old proposals.
    """
    settings = get_settings()

    try:
        from datetime import timedelta

        from models.database import get_db_session

        cutoff = datetime.now(timezone.utc) - timedelta(days=settings.approval.timeout_days)

        with get_db_session() as db:
            # Find proposals that are still pending past the cutoff
            pending_proposals = (
                db.query(DBFixProposal)
                .filter(
                    DBFixProposal.status == "pending_approval",
                    DBFixProposal.generated_at < cutoff,
                )
                .all()
            )

            for proposal in pending_proposals:
                logger.info(f"Expiring proposal {proposal.proposal_id}")

                proposal.status = "expired"

                # Update associated approval
                approval = (
                    db.query(Approval)
                    .filter(
                        Approval.proposal_id == proposal.id, Approval.status == "pending"
                    )
                    .first()
                )

                if approval:
                    approval.status = "expired"
                    approval.resolved_at = datetime.now(timezone.utc)

                # Update issue status
                if proposal.issue:
                    proposal.issue.status = "expired"

        if pending_proposals:
            logger.info(f"Expired {len(pending_proposals)} proposals")

    except Exception as e:
        logger.error(f"Error cleaning up expired proposals: {e}", exc_info=True)
