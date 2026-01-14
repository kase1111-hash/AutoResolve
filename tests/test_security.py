"""
Tests for the security audit module.
"""

import pytest
from uuid import uuid4

from modules.security_auditor import (
    assess_severity,
    compute_risk_score,
    deduplicate_findings,
    generate_recommendation,
)
from models.schemas import Finding, SecurityReport


@pytest.fixture
def critical_finding() -> Finding:
    """Create a critical security finding."""
    return Finding(
        finding_id=uuid4(),
        scanner="bandit",
        rule_id="B602",
        cwe="CWE-78",
        severity="critical",
        confidence="high",
        file="test.py",
        line_start=10,
        line_end=10,
        message="Possible shell injection",
    )


@pytest.fixture
def high_finding() -> Finding:
    """Create a high severity finding."""
    return Finding(
        finding_id=uuid4(),
        scanner="semgrep",
        rule_id="sql-injection",
        cwe="CWE-89",
        severity="high",
        confidence="high",
        file="db.py",
        line_start=20,
        line_end=20,
        message="SQL injection vulnerability",
    )


@pytest.fixture
def medium_finding() -> Finding:
    """Create a medium severity finding."""
    return Finding(
        finding_id=uuid4(),
        scanner="bandit",
        rule_id="B303",
        cwe="CWE-327",
        severity="medium",
        confidence="medium",
        file="crypto.py",
        line_start=5,
        line_end=5,
        message="Use of weak hash function",
    )


class TestAssessSeverity:
    """Tests for severity assessment."""

    def test_cwe_mapping_critical(self, critical_finding):
        """Should map CWE to critical severity."""
        assert assess_severity(critical_finding) == "critical"

    def test_cwe_mapping_high(self, high_finding):
        """Should map CWE to high severity."""
        assert assess_severity(high_finding) == "critical"  # CWE-89 maps to critical

    def test_fallback_to_scanner_severity(self):
        """Should fall back to scanner severity."""
        finding = Finding(
            finding_id=uuid4(),
            scanner="custom",
            rule_id="test",
            severity="low",
            file="test.py",
            line_start=1,
            line_end=1,
            message="Test"
        )
        assert assess_severity(finding) == "low"


class TestComputeRiskScore:
    """Tests for risk score computation."""

    def test_no_findings(self):
        """Should return 0 for no findings."""
        assert compute_risk_score([]) == 0.0

    def test_critical_findings(self, critical_finding):
        """Should return high score for critical findings."""
        score = compute_risk_score([critical_finding])

        assert score >= 0.8

    def test_mixed_findings(self, critical_finding, medium_finding):
        """Should compute weighted score."""
        score = compute_risk_score([critical_finding, medium_finding])

        assert 0.0 < score <= 1.0


class TestDeduplicateFindings:
    """Tests for finding deduplication."""

    def test_removes_duplicates(self):
        """Should remove duplicate findings."""
        finding1 = Finding(
            finding_id=uuid4(),
            scanner="bandit",
            rule_id="B101",
            severity="medium",
            file="test.py",
            line_start=10,
            line_end=10,
            message="Test"
        )
        finding2 = Finding(
            finding_id=uuid4(),
            scanner="semgrep",
            rule_id="B101",  # Same rule_id as finding1
            severity="medium",
            file="test.py",
            line_start=10,
            line_end=10,
            message="Test similar"
        )

        result = deduplicate_findings([finding1, finding2])

        assert len(result) == 1  # Both findings have same file, line, and rule_id prefix

    def test_keeps_different_findings(self):
        """Should keep different findings."""
        finding1 = Finding(
            finding_id=uuid4(),
            scanner="bandit",
            rule_id="B101",
            severity="medium",
            file="test.py",
            line_start=10,
            line_end=10,
            message="Test"
        )
        finding2 = Finding(
            finding_id=uuid4(),
            scanner="bandit",
            rule_id="B102",
            severity="medium",
            file="other.py",
            line_start=20,
            line_end=20,
            message="Other"
        )

        result = deduplicate_findings([finding1, finding2])

        assert len(result) == 2


class TestGenerateRecommendation:
    """Tests for recommendation generation."""

    def test_rejects_critical_findings(self):
        """Should reject when critical findings exist."""
        report = SecurityReport(
            proposal_id=uuid4(),
            has_vulnerabilities=True,
            risk_score=0.9,
            findings_by_severity={"critical": 1},
            findings=[],
        )

        assert generate_recommendation(report) == "reject"

    def test_rejects_multiple_high_findings(self):
        """Should reject when many high findings exist."""
        report = SecurityReport(
            proposal_id=uuid4(),
            has_vulnerabilities=True,
            risk_score=0.7,
            findings_by_severity={"high": 3},
            findings=[],
        )

        assert generate_recommendation(report) == "reject"

    def test_reviews_high_findings(self):
        """Should require review for high findings."""
        report = SecurityReport(
            proposal_id=uuid4(),
            has_vulnerabilities=True,
            risk_score=0.5,
            findings_by_severity={"high": 1},
            findings=[],
        )

        assert generate_recommendation(report) == "review"

    def test_approves_clean_report(self):
        """Should approve when no significant findings."""
        report = SecurityReport(
            proposal_id=uuid4(),
            has_vulnerabilities=False,
            risk_score=0.0,
            findings_by_severity={},
            findings=[],
        )

        assert generate_recommendation(report) == "approve"

    def test_reviews_failed_dynamic_scan(self):
        """Should require review when dynamic scan fails."""
        report = SecurityReport(
            proposal_id=uuid4(),
            has_vulnerabilities=False,
            risk_score=0.1,
            findings_by_severity={},
            findings=[],
            dynamic_scan_passed=False,
        )

        assert generate_recommendation(report) == "review"
