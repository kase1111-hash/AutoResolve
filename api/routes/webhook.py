"""
GitHub webhook endpoint for AutoResolve.
"""

import hashlib
import hmac
import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request

from app.config import get_settings
from models.schemas import QueuedIssue

logger = logging.getLogger(__name__)

router = APIRouter()


def verify_signature(payload_body: bytes, signature_header: str, secret: str) -> bool:
    """Verify GitHub webhook signature."""
    if not signature_header:
        return False

    try:
        # GitHub sends signature as "sha256=<hash>"
        hash_algorithm, signature = signature_header.split("=", 1)
        if hash_algorithm != "sha256":
            return False

        expected_signature = hmac.new(
            secret.encode(),
            payload_body,
            hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(expected_signature, signature)
    except Exception:
        return False


@router.post("/webhook/github")
async def handle_github_webhook(
    request: Request,
    x_hub_signature_256: Optional[str] = Header(None),
    x_github_event: Optional[str] = Header(None),
):
    """
    Handle incoming GitHub webhooks.

    Validates signature, filters events, and enqueues issues for processing.
    """
    settings = get_settings()
    body = await request.body()

    # Verify webhook signature
    if settings.github.webhook_secret:
        if not verify_signature(body, x_hub_signature_256 or "", settings.github.webhook_secret):
            logger.warning("Invalid webhook signature received")
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    # Parse payload
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Only process issue events
    if x_github_event != "issues":
        logger.debug(f"Ignoring non-issue event: {x_github_event}")
        return {"status": "ignored", "reason": "not an issue event"}

    # Check action type
    action = payload.get("action")
    if action not in ["opened", "reopened", "labeled"]:
        logger.debug(f"Ignoring issue action: {action}")
        return {"status": "ignored", "reason": f"action '{action}' not processed"}

    # Import here to avoid circular imports
    from modules.monitoring import enqueue_issue, is_already_queued, should_process

    issue = payload.get("issue", {})
    repo = payload.get("repository", {})

    # Check if issue should be processed
    if not should_process(issue, settings.filtering):
        logger.debug(f"Issue {issue.get('number')} filtered out")
        return {"status": "filtered", "reason": "issue does not match filter criteria"}

    # Check deduplication
    repo_full_name = repo.get("full_name", "")
    issue_number = issue.get("number", 0)

    if is_already_queued(repo_full_name, issue_number):
        logger.debug(f"Issue {repo_full_name}#{issue_number} already queued")
        return {"status": "duplicate", "reason": "issue already in queue"}

    # Create queued issue
    from datetime import datetime

    queued_issue = QueuedIssue(
        issue_id=issue_number,
        repo_url=repo.get("html_url", ""),
        repo_full_name=repo_full_name,
        title=issue.get("title", ""),
        body=issue.get("body", ""),
        labels=[label.get("name", "") for label in issue.get("labels", [])],
        author=issue.get("user", {}).get("login", ""),
        created_at=datetime.fromisoformat(
            issue.get("created_at", "").replace("Z", "+00:00")
        ) if issue.get("created_at") else datetime.utcnow(),
    )

    # Enqueue for processing
    enqueue_issue(queued_issue)

    logger.info(f"Enqueued issue: {repo_full_name}#{issue_number}")

    return {
        "status": "queued",
        "queue_id": str(queued_issue.queue_id),
        "issue_id": issue_number,
        "repo": repo_full_name
    }
