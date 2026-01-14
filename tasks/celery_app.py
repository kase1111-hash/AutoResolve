"""
Celery application configuration for AutoResolve.
"""

from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "autoresolve",
    broker=settings.celery.broker_url,
    backend=settings.celery.result_backend,
    include=["tasks.processing", "tasks.polling"],
)

# Celery configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_routes={
        "tasks.processing.process_issue": {"queue": "processing"},
        "tasks.processing.generate_fix": {"queue": "processing"},
        "tasks.processing.audit_fix": {"queue": "processing"},
        "tasks.polling.poll_approval": {"queue": "polling"},
        "tasks.polling.poll_repositories": {"queue": "polling"},
    },
    task_annotations={
        "tasks.processing.process_issue": {"rate_limit": "10/m"},
        "tasks.processing.create_pr": {"rate_limit": "30/m"},
    },
    task_default_retry_delay=60,
    task_max_retries=3,
)

# Celery beat schedule
celery_app.conf.beat_schedule = {
    "poll-repos": {
        "task": "tasks.polling.poll_repositories",
        "schedule": crontab(minute="*/5"),
    },
    "cleanup-expired": {
        "task": "tasks.polling.cleanup_expired_proposals",
        "schedule": crontab(hour=0, minute=0),
    },
}
