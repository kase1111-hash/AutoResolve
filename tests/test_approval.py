"""
Tests for the approval module.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from models.schemas import Finding, SecurityReport
from modules.approval import (
    _extract_feedback,
    _extract_reason,
    format_security_summary,
)


class TestFormatSecuritySummary:
    """Tests for security summary formatting."""

    def test_no_vulnerabilities(self):
        """Should return clean message for no vulnerabilities."""
        report = SecurityReport(
            proposal_id=uuid4(),
            has_vulnerabilities=False,
            risk_score=0.0,
            findings=[],
        )

        summary = format_security_summary(report)

        assert "No security issues" in summary

    def test_with_vulnerabilities(self):
        """Should format vulnerability summary."""
        report = SecurityReport(
            proposal_id=uuid4(),
            has_vulnerabilities=True,
            risk_score=0.5,
            findings_by_severity={"high": 1, "medium": 2},
            findings=[],
            critical_findings=[
                Finding(
                    finding_id=uuid4(),
                    scanner="bandit",
                    rule_id="B602",
                    severity="high",
                    file="test.py",
                    line_start=10,
                    line_end=10,
                    message="Possible injection",
                )
            ],
        )

        summary = format_security_summary(report)

        assert "Risk Score" in summary
        assert "High" in summary
        assert "Medium" in summary
        assert "Possible injection" in summary


class TestExtractReason:
    """Tests for rejection reason extraction."""

    def test_extracts_reason_with_colon(self):
        """Should extract reason after colon."""
        text = "@autoresolve reject: The fix doesn't handle edge cases"

        reason = _extract_reason(text)

        assert reason is not None
        assert "edge cases" in reason

    def test_extracts_reason_with_dash(self):
        """Should extract reason after dash."""
        text = "@autoresolve reject - This breaks the API"

        reason = _extract_reason(text)

        assert reason is not None
        assert "breaks the API" in reason

    def test_extracts_reason_plain(self):
        """Should extract reason without separator."""
        text = "@autoresolve reject The implementation is wrong"

        reason = _extract_reason(text)

        assert reason is not None
        assert "implementation" in reason

    def test_truncates_long_reason(self):
        """Should truncate very long reasons."""
        long_text = "x" * 1000
        text = f"@autoresolve reject {long_text}"

        reason = _extract_reason(text)

        assert reason is not None
        assert len(reason) <= 500

    def test_returns_none_for_no_reason(self):
        """Should return None when no reason provided."""
        text = "Some other comment"

        reason = _extract_reason(text)

        assert reason is None


class TestExtractFeedback:
    """Tests for regeneration feedback extraction."""

    def test_extracts_feedback(self):
        """Should extract feedback for regeneration."""
        text = "@autoresolve regenerate: Please also fix the error handling"

        feedback = _extract_feedback(text)

        assert feedback is not None
        assert "error handling" in feedback

    def test_truncates_long_feedback(self):
        """Should truncate very long feedback."""
        long_text = "y" * 1000
        text = f"@autoresolve regenerate {long_text}"

        feedback = _extract_feedback(text)

        assert feedback is not None
        assert len(feedback) <= 500


class TestApprovalWorkflow:
    """Integration tests for approval workflow."""

    @pytest.mark.asyncio
    async def test_poll_detects_approval(self, mock_github_service):
        """Should detect approval comment."""
        mock_github_service.get_issue_comments = AsyncMock(
            return_value=[
                {
                    "user": {"login": "maintainer"},
                    "body": "@autoresolve approve",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            ]
        )
        mock_github_service.get_issue_reactions = AsyncMock(return_value=[])

        from models.schemas import FixProposal
        from modules.approval import poll_for_approval

        proposal = FixProposal(
            proposal_id=uuid4(),
            issue_id=123,
            repo_full_name="test/repo",
            suggested_patch="diff",
            generated_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )

        with patch(
            "services.github_service.GitHubService", return_value=mock_github_service
        ):
            result = await poll_for_approval("test/repo", 123, proposal)

        assert result.status == "approved"
        assert result.approved_by == "maintainer"

    @pytest.mark.asyncio
    async def test_poll_detects_rejection(self, mock_github_service):
        """Should detect rejection comment."""
        mock_github_service.get_issue_comments = AsyncMock(
            return_value=[
                {
                    "user": {"login": "maintainer"},
                    "body": "@autoresolve reject: Not the right fix",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            ]
        )
        mock_github_service.get_issue_reactions = AsyncMock(return_value=[])

        from models.schemas import FixProposal
        from modules.approval import poll_for_approval

        proposal = FixProposal(
            proposal_id=uuid4(),
            issue_id=123,
            repo_full_name="test/repo",
            suggested_patch="diff",
            generated_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )

        with patch(
            "services.github_service.GitHubService", return_value=mock_github_service
        ):
            result = await poll_for_approval("test/repo", 123, proposal)

        assert result.status == "rejected"
        assert "right fix" in result.rejection_reason

    @pytest.mark.asyncio
    async def test_poll_detects_thumbs_up(self, mock_github_service):
        """Should detect thumbs up reaction as approval."""
        mock_github_service.get_issue_comments = AsyncMock(return_value=[])
        mock_github_service.get_issue_reactions = AsyncMock(
            return_value=[{"user": {"login": "maintainer"}, "content": "+1"}]
        )

        from models.schemas import FixProposal
        from modules.approval import poll_for_approval

        proposal = FixProposal(
            proposal_id=uuid4(),
            issue_id=123,
            repo_full_name="test/repo",
            suggested_patch="diff",
            generated_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )

        with patch(
            "services.github_service.GitHubService", return_value=mock_github_service
        ):
            result = await poll_for_approval("test/repo", 123, proposal)

        assert result.status == "approved"
