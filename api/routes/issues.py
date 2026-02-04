"""
Issue management API routes for AutoResolve.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.orm import Session

from api.middleware.auth import check_api_rate_limit
from app.config import get_settings
from app.dependencies import get_db
from models.database import Approval, FixProposal, Issue, Validation
from models.schemas import IssueResponse

logger = logging.getLogger(__name__)

router = APIRouter()


def verify_api_key(x_api_key: Optional[str] = Header(None)):
    """Verify API key for protected endpoints."""
    settings = get_settings()
    if settings.api.api_key and x_api_key != settings.api.api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return True


@router.get("/issues", response_model=list[IssueResponse])
async def list_issues(
    request: Request,
    status: Optional[str] = Query(None, description="Filter by status"),
    repo: Optional[str] = Query(None, description="Filter by repository"),
    limit: int = Query(50, le=100, description="Maximum number of results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    db: Session = Depends(get_db),
    _: bool = Depends(verify_api_key),
    __: None = Depends(check_api_rate_limit),
):
    """List processed issues with optional filtering."""
    query = db.query(Issue)

    if status:
        query = query.filter(Issue.status == status)
    if repo:
        query = query.filter(Issue.repo_full_name == repo)

    issues = query.order_by(Issue.queued_at.desc()).offset(offset).limit(limit).all()

    result = []
    for issue in issues:
        # Get latest validation
        validation = (
            db.query(Validation)
            .filter(Validation.issue_id == issue.id)
            .order_by(Validation.validated_at.desc())
            .first()
        )

        # Get latest proposal
        proposal = (
            db.query(FixProposal)
            .filter(FixProposal.issue_id == issue.id)
            .order_by(FixProposal.generated_at.desc())
            .first()
        )

        # Get latest approval
        approval = None
        if proposal:
            approval = (
                db.query(Approval)
                .filter(Approval.proposal_id == proposal.id)
                .order_by(Approval.created_at.desc())
                .first()
            )

        result.append(
            IssueResponse(
                id=issue.id,
                github_issue_id=issue.github_issue_id,
                repo_full_name=issue.repo_full_name,
                title=issue.title,
                status=issue.status,
                validation=(
                    {"valid": validation.valid, "match_score": validation.match_score}
                    if validation
                    else None
                ),
                proposal=(
                    {
                        "proposal_id": str(proposal.proposal_id),
                        "affected_files": proposal.affected_files,
                        "status": proposal.status,
                    }
                    if proposal
                    else None
                ),
                approval=(
                    {"status": approval.status, "pr_url": approval.pr_url}
                    if approval
                    else None
                ),
            )
        )

    return result


@router.get("/issues/{issue_id}", response_model=IssueResponse)
async def get_issue(
    request: Request,
    issue_id: int,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_api_key),
    __: None = Depends(check_api_rate_limit),
):
    """Get details for a specific issue."""
    issue = db.query(Issue).filter(Issue.id == issue_id).first()

    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    # Get latest validation
    validation = (
        db.query(Validation)
        .filter(Validation.issue_id == issue.id)
        .order_by(Validation.validated_at.desc())
        .first()
    )

    # Get latest proposal
    proposal = (
        db.query(FixProposal)
        .filter(FixProposal.issue_id == issue.id)
        .order_by(FixProposal.generated_at.desc())
        .first()
    )

    # Get latest approval
    approval = None
    if proposal:
        approval = (
            db.query(Approval)
            .filter(Approval.proposal_id == proposal.id)
            .order_by(Approval.created_at.desc())
            .first()
        )

    return IssueResponse(
        id=issue.id,
        github_issue_id=issue.github_issue_id,
        repo_full_name=issue.repo_full_name,
        title=issue.title,
        status=issue.status,
        validation=(
            {
                "valid": validation.valid,
                "match_score": validation.match_score,
                "validity_status": validation.validity_status,
                "error_signature": validation.error_signature,
            }
            if validation
            else None
        ),
        proposal=(
            {
                "proposal_id": str(proposal.proposal_id),
                "affected_files": proposal.affected_files,
                "lines_added": proposal.lines_added,
                "lines_removed": proposal.lines_removed,
                "status": proposal.status,
                "generated_at": proposal.generated_at.isoformat(),
            }
            if proposal
            else None
        ),
        approval=(
            {
                "status": approval.status,
                "approved_by": approval.approved_by,
                "rejected_by": approval.rejected_by,
                "pr_number": approval.pr_number,
                "pr_url": approval.pr_url,
                "pr_merged": approval.pr_merged,
            }
            if approval
            else None
        ),
    )


@router.post("/issues/{issue_id}/retry")
async def retry_issue(
    request: Request,
    issue_id: int,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_api_key),
    __: None = Depends(check_api_rate_limit),
):
    """Retry processing a failed issue."""
    issue = db.query(Issue).filter(Issue.id == issue_id).first()

    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    if issue.status not in ["failed", "rejected"]:
        raise HTTPException(
            status_code=400, detail=f"Cannot retry issue with status '{issue.status}'"
        )

    # Reset status and requeue
    issue.status = "pending"
    db.commit()

    # TODO: Enqueue for reprocessing
    # from tasks.processing import process_issue
    # process_issue.delay(issue.id)

    logger.info(f"Retrying issue: {issue.repo_full_name}#{issue.github_issue_id}")

    return {"status": "queued", "issue_id": issue.id}


@router.get("/issues/{issue_id}/timeline")
async def get_issue_timeline(
    request: Request,
    issue_id: int,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_api_key),
    __: None = Depends(check_api_rate_limit),
):
    """Get the processing timeline for an issue."""
    from models.database import AuditLog

    issue = db.query(Issue).filter(Issue.id == issue_id).first()

    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    # Get audit log entries for this issue
    events = (
        db.query(AuditLog)
        .filter(AuditLog.entity_type == "issue", AuditLog.entity_id == issue_id)
        .order_by(AuditLog.timestamp.asc())
        .all()
    )

    return {
        "issue_id": issue_id,
        "timeline": [
            {
                "timestamp": event.timestamp.isoformat(),
                "event_type": event.event_type,
                "actor": event.actor,
                "details": event.details,
            }
            for event in events
        ],
    }
