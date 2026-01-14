"""
Tests for the monitoring module.
"""

from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from app.config import FilterConfig
from modules.monitoring import (
    should_process,
    is_already_queued,
    mark_as_queued,
    compute_priority,
)


class TestShouldProcess:
    """Tests for the should_process function."""

    def test_excludes_by_label(self):
        """Issues with excluded labels should be filtered out."""
        issue = {
            "labels": [{"name": "wontfix"}],
            "user": {"login": "testuser"},
            "body": "This is a bug report with enough content to pass the minimum length requirement.",
            "title": "Bug report",
            "created_at": datetime.utcnow().isoformat() + "Z"
        }
        config = FilterConfig()

        assert should_process(issue, config) is False

    def test_excludes_bot_authors(self):
        """Issues from bot accounts should be filtered out."""
        issue = {
            "labels": [{"name": "bug"}],
            "user": {"login": "dependabot"},
            "body": "This is a bug report with enough content to pass the minimum length requirement.",
            "title": "Bug report",
            "created_at": datetime.utcnow().isoformat() + "Z"
        }
        config = FilterConfig()

        assert should_process(issue, config) is False

    def test_excludes_short_body(self):
        """Issues with short bodies should be filtered out."""
        issue = {
            "labels": [{"name": "bug"}],
            "user": {"login": "testuser"},
            "body": "Short",
            "title": "Bug",
            "created_at": datetime.utcnow().isoformat() + "Z"
        }
        config = FilterConfig()

        assert should_process(issue, config) is False

    def test_excludes_old_issues(self):
        """Issues older than max_age_days should be filtered out."""
        old_date = (datetime.utcnow() - timedelta(days=60)).isoformat() + "Z"
        issue = {
            "labels": [{"name": "bug"}],
            "user": {"login": "testuser"},
            "body": "This is a bug report with enough content to pass the minimum length requirement.",
            "title": "Bug report",
            "created_at": old_date
        }
        config = FilterConfig()

        assert should_process(issue, config) is False

    def test_triggers_by_label(self):
        """Issues with trigger labels should be processed."""
        issue = {
            "labels": [{"name": "bug"}],
            "user": {"login": "testuser"},
            "body": "This is a bug report with enough content to pass the minimum length requirement.",
            "title": "Bug report",
            "created_at": datetime.utcnow().isoformat() + "Z"
        }
        config = FilterConfig()

        assert should_process(issue, config) is True

    def test_triggers_by_keyword(self):
        """Issues with trigger keywords should be processed."""
        issue = {
            "labels": [],
            "user": {"login": "testuser"},
            "body": "I'm getting a TypeError when running the application. Here's the traceback...",
            "title": "Application crashes",
            "created_at": datetime.utcnow().isoformat() + "Z"
        }
        config = FilterConfig()

        assert should_process(issue, config) is True

    def test_no_trigger_returns_false(self):
        """Issues without triggers should be filtered out."""
        issue = {
            "labels": [{"name": "enhancement"}],
            "user": {"login": "testuser"},
            "body": "It would be nice to have a dark mode feature in the application settings.",
            "title": "Feature request: dark mode",
            "created_at": datetime.utcnow().isoformat() + "Z"
        }
        config = FilterConfig()

        assert should_process(issue, config) is False


class TestComputePriority:
    """Tests for the compute_priority function."""

    def test_critical_label(self):
        """Critical label should return priority 1."""
        issue = {"labels": [{"name": "critical"}]}
        priority_labels = {"critical": 1, "high-priority": 2, "bug": 3}

        assert compute_priority(issue, priority_labels) == 1

    def test_high_priority_label(self):
        """High-priority label should return priority 2."""
        issue = {"labels": [{"name": "high-priority"}]}
        priority_labels = {"critical": 1, "high-priority": 2, "bug": 3}

        assert compute_priority(issue, priority_labels) == 2

    def test_default_priority(self):
        """Unknown labels should return default priority 3."""
        issue = {"labels": [{"name": "unknown"}]}
        priority_labels = {"critical": 1, "high-priority": 2, "bug": 3}

        assert compute_priority(issue, priority_labels) == 3

    def test_first_matching_label(self):
        """Should return priority of first matching label."""
        issue = {"labels": [{"name": "bug"}, {"name": "critical"}]}
        priority_labels = {"critical": 1, "high-priority": 2, "bug": 3}

        # bug comes first in issue labels, so its priority is used
        assert compute_priority(issue, priority_labels) == 3


class TestDeduplication:
    """Tests for deduplication functions."""

    @patch("modules.monitoring.get_redis_client")
    def test_is_already_queued_true(self, mock_redis):
        """Should return True if issue is already queued."""
        mock_client = MagicMock()
        mock_client.exists.return_value = 1
        mock_redis.return_value = mock_client

        assert is_already_queued("org/repo", 123) is True
        mock_client.exists.assert_called_once_with("processed:org/repo:123")

    @patch("modules.monitoring.get_redis_client")
    def test_is_already_queued_false(self, mock_redis):
        """Should return False if issue is not queued."""
        mock_client = MagicMock()
        mock_client.exists.return_value = 0
        mock_redis.return_value = mock_client

        assert is_already_queued("org/repo", 123) is False

    @patch("modules.monitoring.get_redis_client")
    def test_mark_as_queued(self, mock_redis):
        """Should set Redis key with TTL."""
        mock_client = MagicMock()
        mock_redis.return_value = mock_client

        mark_as_queued("org/repo", 123, ttl_hours=24)

        mock_client.setex.assert_called_once()
        args = mock_client.setex.call_args[0]
        assert args[0] == "processed:org/repo:123"
