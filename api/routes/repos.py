"""
Repository management API routes for AutoResolve.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session

from app.config import get_settings
from app.dependencies import get_db
from models.database import MonitoredRepo
from models.schemas import RepoCreate, RepoResponse

logger = logging.getLogger(__name__)

router = APIRouter()


def verify_api_key(x_api_key: Optional[str] = Header(None)):
    """Verify API key for protected endpoints."""
    settings = get_settings()
    if settings.api.api_key and x_api_key != settings.api.api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return True


@router.get("/repos", response_model=list[RepoResponse])
async def list_repos(
    db: Session = Depends(get_db),
    _: bool = Depends(verify_api_key)
):
    """List all monitored repositories."""
    repos = db.query(MonitoredRepo).all()
    return [
        RepoResponse(
            id=repo.id,
            repo_full_name=repo.repo_full_name,
            webhook_id=repo.webhook_id,
            enabled=repo.enabled,
            added_at=repo.added_at
        )
        for repo in repos
    ]


@router.post("/repos", response_model=RepoResponse, status_code=201)
async def add_repo(
    repo_data: RepoCreate,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_api_key)
):
    """Add a repository to be monitored."""
    # Check if already exists
    existing = db.query(MonitoredRepo).filter(
        MonitoredRepo.repo_full_name == repo_data.repo_full_name
    ).first()

    if existing:
        raise HTTPException(status_code=409, detail="Repository already monitored")

    # Create new monitored repo
    repo = MonitoredRepo(
        repo_full_name=repo_data.repo_full_name,
        settings=repo_data.settings,
        enabled=True
    )

    db.add(repo)
    db.commit()
    db.refresh(repo)

    logger.info(f"Added repository to monitoring: {repo_data.repo_full_name}")

    # TODO: Register webhook with GitHub

    return RepoResponse(
        id=repo.id,
        repo_full_name=repo.repo_full_name,
        webhook_id=repo.webhook_id,
        enabled=repo.enabled,
        added_at=repo.added_at
    )


@router.get("/repos/{repo_full_name:path}", response_model=RepoResponse)
async def get_repo(
    repo_full_name: str,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_api_key)
):
    """Get a specific monitored repository."""
    repo = db.query(MonitoredRepo).filter(
        MonitoredRepo.repo_full_name == repo_full_name
    ).first()

    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    return RepoResponse(
        id=repo.id,
        repo_full_name=repo.repo_full_name,
        webhook_id=repo.webhook_id,
        enabled=repo.enabled,
        added_at=repo.added_at
    )


@router.delete("/repos/{repo_full_name:path}", status_code=204)
async def remove_repo(
    repo_full_name: str,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_api_key)
):
    """Remove a repository from monitoring."""
    repo = db.query(MonitoredRepo).filter(
        MonitoredRepo.repo_full_name == repo_full_name
    ).first()

    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    db.delete(repo)
    db.commit()

    logger.info(f"Removed repository from monitoring: {repo_full_name}")

    # TODO: Unregister webhook from GitHub

    return None


@router.patch("/repos/{repo_full_name:path}/toggle")
async def toggle_repo(
    repo_full_name: str,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_api_key)
):
    """Toggle repository monitoring on/off."""
    repo = db.query(MonitoredRepo).filter(
        MonitoredRepo.repo_full_name == repo_full_name
    ).first()

    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    repo.enabled = not repo.enabled
    db.commit()

    status = "enabled" if repo.enabled else "disabled"
    logger.info(f"Repository monitoring {status}: {repo_full_name}")

    return {"repo_full_name": repo_full_name, "enabled": repo.enabled}
