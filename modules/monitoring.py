"""
Monitoring Module for AutoResolve.

Handles GitHub webhook reception, issue filtering, and queue management.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import redis

from app.config import FilterConfig, get_settings
from models.schemas import QueuedIssue

logger = logging.getLogger(__name__)

# Redis client for deduplication and queue management
_redis_client: Optional[redis.Redis] = None


def get_redis_client() -> redis.Redis:
    """Get Redis client instance."""
    global _redis_client
    if _redis_client is None:
        settings = get_settings()
        _redis_client = redis.from_url(settings.redis.url)
    return _redis_client


def _is_excluded_by_label(labels: list[str], exclude_labels: list[str]) -> bool:
    """Check if issue should be excluded by label."""
    return any(label in exclude_labels for label in labels)


def _is_too_old(created_at: str, max_age_days: int) -> bool:
    """Check if issue is too old to process."""
    if not created_at:
        return False
    try:
        issue_date = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        age_days = (datetime.now(issue_date.tzinfo) - issue_date).days
        return age_days > max_age_days
    except Exception as e:
        logger.warning(f"Failed to parse issue date: {e}")
        return False


def _has_trigger_keyword(text: str, keywords: list[str]) -> bool:
    """Check if text contains any trigger keyword."""
    text_lower = text.lower()
    return any(keyword.lower() in text_lower for keyword in keywords)


def should_process(issue: dict, filter_config: Optional[FilterConfig] = None) -> bool:
    """
    Determine if an issue should be processed based on filtering rules.

    Args:
        issue: GitHub issue data
        filter_config: Filtering configuration (uses default if not provided)

    Returns:
        True if issue should be processed, False otherwise
    """
    if filter_config is None:
        filter_config = get_settings().filtering

    labels = [label.get("name", "") for label in issue.get("labels", [])]
    author = issue.get("user", {}).get("login", "")
    body = issue.get("body", "") or ""
    title = issue.get("title", "") or ""
    created_at = issue.get("created_at", "")

    # Exclusion checks
    if _is_excluded_by_label(labels, filter_config.exclude_labels):
        logger.debug(f"Issue excluded by label: {labels}")
        return False

    if author in filter_config.exclude_authors:
        logger.debug(f"Issue excluded by author: {author}")
        return False

    if len(body) < filter_config.min_body_length:
        logger.debug(f"Issue body too short: {len(body)} < {filter_config.min_body_length}")
        return False

    if _is_too_old(created_at, filter_config.max_age_days):
        logger.debug("Issue too old")
        return False

    # Trigger checks
    if any(label in filter_config.trigger_labels for label in labels):
        logger.debug(f"Issue triggered by label: {labels}")
        return True

    if _has_trigger_keyword(title + " " + body, filter_config.trigger_keywords):
        logger.debug("Issue triggered by keyword")
        return True

    logger.debug("Issue did not match any trigger criteria")
    return False


def is_already_queued(repo_full_name: str, issue_id: int) -> bool:
    """
    Check if an issue is already queued for processing.

    Uses Redis for deduplication with a 24-hour TTL.
    """
    try:
        r = get_redis_client()
        key = f"processed:{repo_full_name}:{issue_id}"
        return r.exists(key) > 0
    except Exception as e:
        logger.error(f"Redis error checking deduplication: {e}")
        return False


def mark_as_queued(repo_full_name: str, issue_id: int, ttl_hours: int = 24) -> None:
    """Mark an issue as queued to prevent reprocessing."""
    try:
        r = get_redis_client()
        key = f"processed:{repo_full_name}:{issue_id}"
        r.setex(key, timedelta(hours=ttl_hours), "1")
    except Exception as e:
        logger.error(f"Redis error marking issue as queued: {e}")


def enqueue_issue(issue: QueuedIssue) -> None:
    """
    Add an issue to the processing queue.

    Marks the issue as queued and dispatches to Celery task queue.
    """
    # Mark as queued for deduplication
    mark_as_queued(issue.repo_full_name, issue.issue_id)

    # Save to database
    from models.database import Issue, get_session_factory

    SessionLocal = get_session_factory()
    db = SessionLocal()

    try:
        db_issue = Issue(
            queue_id=issue.queue_id,
            github_issue_id=issue.issue_id,
            repo_full_name=issue.repo_full_name,
            repo_url=issue.repo_url,
            title=issue.title,
            body=issue.body,
            labels=issue.labels,
            author=issue.author,
            github_created_at=issue.created_at,
            priority=issue.priority,
            status="pending",
        )
        db.add(db_issue)
        db.commit()
        db.refresh(db_issue)

        # Dispatch to Celery
        # TODO: Enable when Celery tasks are implemented
        # from tasks.processing import process_issue
        # process_issue.delay(db_issue.id)

        logger.info(
            f"Enqueued issue {issue.repo_full_name}#{issue.issue_id} (ID: {db_issue.id})"
        )

    except Exception as e:
        logger.error(f"Failed to enqueue issue: {e}")
        db.rollback()
        raise
    finally:
        db.close()


def compute_priority(issue: dict, priority_labels: dict[str, int]) -> int:
    """
    Compute issue priority based on labels.

    Args:
        issue: GitHub issue data
        priority_labels: Mapping of label names to priority values

    Returns:
        Priority value (1 = highest, 5 = lowest)
    """
    labels = [label.get("name", "") for label in issue.get("labels", [])]

    for label in labels:
        if label in priority_labels:
            return priority_labels[label]

    return 3  # Default priority


async def poll_repositories(
    repos: list[str], since_minutes: int = 10
) -> list[QueuedIssue]:
    """
    Poll repositories for new issues.

    Fallback mechanism for missed webhooks.

    Args:
        repos: List of repository full names (org/repo)
        since_minutes: Look back period in minutes

    Returns:
        List of newly queued issues
    """
    from services.github_service import GitHubService

    settings = get_settings()
    github = GitHubService()
    queued = []

    since = datetime.utcnow() - timedelta(minutes=since_minutes)

    try:
        for repo_full_name in repos:
            try:
                issues = await github.get_issues(
                    repo=repo_full_name,
                    state="open",
                    since=since,
                    sort="updated",
                    direction="desc",
                )

                for issue in issues:
                    if should_process(
                        issue, settings.filtering
                    ) and not is_already_queued(repo_full_name, issue.get("number", 0)):
                        queued_issue = QueuedIssue(
                            issue_id=issue.get("number", 0),
                            repo_url=f"https://github.com/{repo_full_name}",
                            repo_full_name=repo_full_name,
                            title=issue.get("title", ""),
                            body=issue.get("body", ""),
                            labels=[l.get("name", "") for l in issue.get("labels", [])],
                            author=issue.get("user", {}).get("login", ""),
                            created_at=(
                                datetime.fromisoformat(
                                    issue.get("created_at", "").replace("Z", "+00:00")
                                )
                                if issue.get("created_at")
                                else datetime.utcnow()
                            ),
                            priority=compute_priority(
                                issue, settings.monitoring.priority_labels
                            ),
                        )
                        enqueue_issue(queued_issue)
                        queued.append(queued_issue)

            except Exception as e:
                logger.error(f"Error polling repository {repo_full_name}: {e}")
    finally:
        await github.close()

    logger.info(f"Polling complete: {len(queued)} new issues queued")
    return queued


def get_queue_stats() -> dict:
    """Get current queue statistics."""
    try:
        r = get_redis_client()
        pending = r.llen("queue:pending")
        processing = r.scard("queue:processing")

        return {
            "pending": pending,
            "processing": processing,
            "total": pending + processing,
        }
    except Exception as e:
        logger.error(f"Error getting queue stats: {e}")
        return {"pending": 0, "processing": 0, "total": 0}
