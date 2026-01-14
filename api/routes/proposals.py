"""
Fix proposal API routes for AutoResolve.
"""

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.config import get_settings
from app.dependencies import get_db
from models.database import FixProposal, SecurityReport
from models.schemas import ProposalResponse

logger = logging.getLogger(__name__)

router = APIRouter()


def verify_api_key(x_api_key: Optional[str] = Header(None)):
    """Verify API key for protected endpoints."""
    settings = get_settings()
    if settings.api.api_key and x_api_key != settings.api.api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return True


@router.get("/proposals/{proposal_id}", response_model=ProposalResponse)
async def get_proposal(
    proposal_id: UUID,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_api_key)
):
    """Get details for a specific fix proposal."""
    proposal = db.query(FixProposal).filter(
        FixProposal.proposal_id == proposal_id
    ).first()

    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")

    return ProposalResponse(
        proposal_id=proposal.proposal_id,
        issue_id=proposal.issue_id,
        repo_full_name=proposal.issue.repo_full_name,
        affected_files=proposal.affected_files,
        lines_added=proposal.lines_added,
        lines_removed=proposal.lines_removed,
        status=proposal.status,
        generated_at=proposal.generated_at
    )


@router.get("/proposals/{proposal_id}/diff")
async def get_proposal_diff(
    proposal_id: UUID,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_api_key)
):
    """Get the raw diff for a fix proposal."""
    proposal = db.query(FixProposal).filter(
        FixProposal.proposal_id == proposal_id
    ).first()

    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")

    return {
        "proposal_id": str(proposal_id),
        "diff": proposal.suggested_patch,
        "parsed_diff": proposal.parsed_diff
    }


@router.post("/proposals/{proposal_id}/retry")
async def retry_proposal(
    proposal_id: UUID,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_api_key)
):
    """Regenerate a fix proposal."""
    proposal = db.query(FixProposal).filter(
        FixProposal.proposal_id == proposal_id
    ).first()

    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")

    if proposal.status not in ["rejected", "pending_audit"]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot retry proposal with status '{proposal.status}'"
        )

    # TODO: Trigger fix regeneration
    # from tasks.processing import regenerate_fix
    # regenerate_fix.delay(proposal.issue_id)

    logger.info(f"Retrying proposal: {proposal_id}")

    return {"status": "queued", "proposal_id": str(proposal_id)}


@router.get("/reports/{proposal_id}")
async def get_security_report(
    proposal_id: UUID,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_api_key)
):
    """Get the security report for a fix proposal."""
    proposal = db.query(FixProposal).filter(
        FixProposal.proposal_id == proposal_id
    ).first()

    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")

    report = db.query(SecurityReport).filter(
        SecurityReport.proposal_id == proposal.id
    ).order_by(SecurityReport.scanned_at.desc()).first()

    if not report:
        raise HTTPException(status_code=404, detail="Security report not found")

    return {
        "report_id": str(report.report_id),
        "proposal_id": str(proposal_id),
        "has_vulnerabilities": report.has_vulnerabilities,
        "risk_score": report.risk_score,
        "findings_count": report.findings_count,
        "findings_by_severity": report.findings_by_severity,
        "findings": report.findings,
        "scanners_used": report.scanners_used,
        "dynamic_scan_passed": report.dynamic_scan_passed,
        "recommendation": report.recommendation,
        "scanned_at": report.scanned_at.isoformat(),
        "scan_duration": report.scan_duration
    }
