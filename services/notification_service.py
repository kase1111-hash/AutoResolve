"""
Notification Service for AutoResolve.

Handles Slack and email notifications for system events.
"""

import logging
from datetime import datetime
from typing import Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


# Slack message templates
SLACK_TEMPLATES = {
    "issue.validated": {
        "color": "#36a64f",
        "title": "Issue Validated",
        "text": "Issue #{issue_id} in {repo} has been validated and confirmed reproducible."
    },
    "fix.generated": {
        "color": "#2196F3",
        "title": "Fix Generated",
        "text": "A fix has been generated for issue #{issue_id} in {repo}."
    },
    "security.critical_finding": {
        "color": "#F44336",
        "title": "Critical Security Finding",
        "text": "A critical security issue was detected in the proposed fix for #{issue_id}."
    },
    "approval.pending": {
        "color": "#FFC107",
        "title": "Approval Pending",
        "text": "Fix for issue #{issue_id} in {repo} is awaiting maintainer approval."
    },
    "approval.approved": {
        "color": "#4CAF50",
        "title": "Fix Approved",
        "text": "Fix for issue #{issue_id} in {repo} has been approved by @{approved_by}."
    },
    "approval.rejected": {
        "color": "#F44336",
        "title": "Fix Rejected",
        "text": "Fix for issue #{issue_id} in {repo} was rejected."
    },
    "pr.created": {
        "color": "#2196F3",
        "title": "Pull Request Created",
        "text": "PR #{pr_number} created for issue #{issue_id} in {repo}."
    },
    "pr.merged": {
        "color": "#4CAF50",
        "title": "Pull Request Merged",
        "text": "PR #{pr_number} for issue #{issue_id} in {repo} has been merged!"
    }
}


async def send_slack_notification(
    event_type: str,
    repo: str,
    issue_id: Optional[int] = None,
    details: Optional[dict] = None
) -> bool:
    """
    Send a Slack notification.

    Args:
        event_type: Type of event
        repo: Repository name
        issue_id: Optional issue number
        details: Additional event details

    Returns:
        True if successful
    """
    settings = get_settings()

    if not settings.notifications.slack_enabled:
        return False

    webhook_url = settings.notifications.slack_webhook_url
    if not webhook_url:
        logger.warning("Slack webhook URL not configured")
        return False

    template = SLACK_TEMPLATES.get(event_type)
    if not template:
        logger.warning(f"No Slack template for event type: {event_type}")
        return False

    # Format message
    format_data = {
        "repo": repo,
        "issue_id": issue_id or "N/A",
        **(details or {})
    }

    try:
        text = template["text"].format(**format_data)
    except KeyError as e:
        logger.error(f"Missing format key in notification: {e}")
        text = template["text"]

    # Build Slack message
    message = {
        "channel": settings.notifications.slack_channel,
        "attachments": [
            {
                "color": template["color"],
                "title": template["title"],
                "text": text,
                "footer": "AutoResolve",
                "ts": int(datetime.utcnow().timestamp())
            }
        ]
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(webhook_url, json=message)
            response.raise_for_status()
            logger.info(f"Sent Slack notification: {event_type}")
            return True
    except Exception as e:
        logger.error(f"Failed to send Slack notification: {e}")
        return False


async def send_email_notification(
    event_type: str,
    repo: str,
    issue_id: Optional[int] = None,
    details: Optional[dict] = None
) -> bool:
    """
    Send an email notification.

    Args:
        event_type: Type of event
        repo: Repository name
        issue_id: Optional issue number
        details: Additional event details

    Returns:
        True if successful
    """
    settings = get_settings()

    if not settings.notifications.email_enabled:
        return False

    # Build email content
    subject = f"[AutoResolve] {event_type.replace('.', ' ').title()} - {repo}"

    body_lines = [
        f"Event: {event_type}",
        f"Repository: {repo}",
    ]

    if issue_id:
        body_lines.append(f"Issue: #{issue_id}")

    if details:
        body_lines.append("")
        body_lines.append("Details:")
        for key, value in details.items():
            body_lines.append(f"  {key}: {value}")

    body_lines.extend([
        "",
        "---",
        "AutoResolve - Automated GitHub Issue Resolution"
    ])

    body = "\n".join(body_lines)

    try:
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        msg = MIMEMultipart()
        msg["From"] = settings.notifications.email_from
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        # Get recipients (TODO: configure per-repo recipients)
        recipients = []  # Would be fetched from config or database

        if not recipients:
            logger.warning("No email recipients configured")
            return False

        with smtplib.SMTP(
            settings.notifications.smtp_host,
            settings.notifications.smtp_port
        ) as server:
            server.starttls()
            if settings.notifications.smtp_user:
                server.login(
                    settings.notifications.smtp_user,
                    settings.notifications.smtp_password
                )

            for recipient in recipients:
                msg["To"] = recipient
                server.send_message(msg)

        logger.info(f"Sent email notification: {event_type}")
        return True

    except Exception as e:
        logger.error(f"Failed to send email notification: {e}")
        return False


def format_notification_details(
    _event_type: str,
    data: dict
) -> dict:
    """
    Format notification details for display.

    Args:
        _event_type: Type of event (reserved for future use)
        data: Raw event data

    Returns:
        Formatted details dict
    """
    details = {}

    if "issue_title" in data:
        details["Issue"] = data["issue_title"]

    if "proposal_id" in data:
        details["Proposal ID"] = str(data["proposal_id"])[:8]

    if "pr_number" in data:
        details["PR"] = f"#{data['pr_number']}"

    if "pr_url" in data:
        details["PR URL"] = data["pr_url"]

    if "approved_by" in data:
        details["Approved By"] = f"@{data['approved_by']}"

    if "rejected_by" in data:
        details["Rejected By"] = f"@{data['rejected_by']}"

    if "rejection_reason" in data:
        details["Reason"] = data["rejection_reason"][:100]

    if "security_findings" in data:
        details["Security Findings"] = str(data["security_findings"])

    return details
