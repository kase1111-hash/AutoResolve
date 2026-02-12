"""
End-to-end integration tests for AutoResolve pipeline.

Tests the full flow: webhook → queue → validate → fix → audit → approve → PR.
External services (GitHub, LLM, Docker, Redis, Celery) are mocked so the test
exercises real database writes, schema transformations, and inter-module wiring.
"""

import hashlib
import hmac
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from models.database import (
    Approval,
    Base,
)
from models.database import FixProposal as DBFixProposal
from models.database import (
    Issue,
)
from models.database import SecurityReport as DBSecurityReport
from models.database import (
    Validation,
)
from models.schemas import (
    CodeContext,
    EnvironmentInfo,
    FixProposal,
    FunctionContext,
    IssueContext,
    ReproductionResult,
    SecurityReport,
    ValidationResult,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

WEBHOOK_SECRET = "test-webhook-secret-1234"

SAMPLE_DIFF = """\
--- a/auth/login.py
+++ b/auth/login.py
@@ -7,5 +7,5 @@
 def authenticate(username, password):
     \"\"\"Authenticate a user.\"\"\"
-    user = get_user(None)
+    user = get_user(username)
     if user:
         return True
"""

BUGGY_SOURCE = """\
def get_user(username):
    \"\"\"Get user by username.\"\"\"
    if username is None:
        return None
    return {"username": username}

def authenticate(username, password):
    \"\"\"Authenticate a user.\"\"\"
    user = get_user(None)  # Bug: should be get_user(username)
    if user:
        return True
    return False
"""

ISSUE_BODY = """\
## Description
When trying to login, I get a TypeError.

## Error
```
Traceback (most recent call last):
  File "auth/login.py", line 42, in authenticate
    user = get_user(None)
TypeError: 'NoneType' object is not subscriptable
```

## Steps to reproduce
```bash
$ python -m pytest tests/test_auth.py
```

## Expected behavior
User should be logged in successfully.

## Environment
- Python 3.11
"""


def _make_webhook_payload(action="opened"):
    """Build a realistic GitHub webhook payload."""
    return {
        "action": action,
        "issue": {
            "number": 42,
            "title": "TypeError in user authentication",
            "body": ISSUE_BODY,
            "labels": [{"name": "bug"}, {"name": "high-priority"}],
            "user": {"login": "alice"},
            "created_at": "2026-02-10T10:00:00Z",
            "html_url": "https://github.com/acme/webapp/issues/42",
            "state": "open",
        },
        "repository": {
            "full_name": "acme/webapp",
            "html_url": "https://github.com/acme/webapp",
            "default_branch": "main",
        },
        "sender": {"login": "alice"},
    }


def _sign_payload(payload_bytes: bytes, secret: str) -> str:
    """Produce the X-Hub-Signature-256 header GitHub would send."""
    sig = hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


def _build_validation_result(issue_id: int = 42) -> ValidationResult:
    """Return a passing ValidationResult with realistic data."""
    return ValidationResult(
        issue_id=issue_id,
        repo_full_name="acme/webapp",
        valid=True,
        validity_status="confirmed",
        issue_context=IssueContext(
            error_type="TypeError",
            error_message="'NoneType' object is not subscriptable",
            affected_files=["auth/login.py"],
            affected_functions=["authenticate", "get_user"],
            stack_trace=(
                "Traceback (most recent call last):\n"
                '  File "auth/login.py", line 42, in authenticate\n'
                "    user = get_user(None)\n"
                "TypeError: 'NoneType' object is not subscriptable"
            ),
            reproduction_steps=["python -m pytest tests/test_auth.py"],
            expected_behavior="User logged in",
            actual_behavior="TypeError raised",
            environment=EnvironmentInfo(python_version="3.11"),
            code_snippets=[],
            parse_confidence=0.85,
        ),
        reproduction_result=ReproductionResult(
            valid=True,
            validity_status="confirmed",
            match_score=0.92,
            stdout="",
            stderr="TypeError: 'NoneType' object is not subscriptable",
            exit_code=1,
            error_signature="TypeError: 'NoneType' object is not subscriptable",
            execution_time=3.2,
            sandbox_image="python:3.11-slim",
        ),
        code_context=CodeContext(
            affected_files=["auth/login.py"],
            functions=[
                FunctionContext(
                    file="auth/login.py",
                    name="authenticate",
                    start_line=7,
                    end_line=12,
                    source=BUGGY_SOURCE,
                )
            ],
            error_signature="TypeError: 'NoneType' object is not subscriptable",
            test_command="pytest -v",
            language="python",
            repo_commit="abc1234",
        ),
        validation_duration=5.6,
    )


def _build_fix_proposal(issue_id: int = 42) -> FixProposal:
    """Return a FixProposal for the sample bug."""
    return FixProposal(
        issue_id=issue_id,
        repo_full_name="acme/webapp",
        suggested_patch=SAMPLE_DIFF,
        affected_files=["auth/login.py"],
        lines_added=1,
        lines_removed=1,
        llm_model="gpt-4",
        generation_attempts=1,
    )


def _build_security_report(proposal_id) -> SecurityReport:
    """Return a clean SecurityReport (no findings)."""
    return SecurityReport(
        proposal_id=proposal_id,
        has_vulnerabilities=False,
        risk_score=0.0,
        findings_count=0,
        findings_by_severity={},
        findings=[],
        critical_findings=[],
        scanners_used=["bandit"],
        dynamic_scan_passed=True,
        scan_duration=2.1,
        recommendation="approve",
    )


# ---------------------------------------------------------------------------
# Database fixtures (per-function isolation)
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def db_session(db_engine):
    SessionLocal = sessionmaker(bind=db_engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture()
def client(db_session):
    """TestClient wired to the in-memory DB."""

    def override_get_db():
        yield db_session

    from app.dependencies import get_db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestWebhookAcceptance:
    """Verify the webhook endpoint accepts, filters, and enqueues issues."""

    def test_rejects_missing_signature(self, client):
        """Webhook without signature is rejected (fail-closed)."""
        payload = json.dumps(_make_webhook_payload()).encode()
        resp = client.post(
            "/webhook/github",
            content=payload,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "issues",
            },
        )
        # Should be 401 or 500 depending on config
        assert resp.status_code in (401, 500)

    @patch("api.routes.webhook.get_settings")
    @patch("api.routes.webhook.check_webhook_rate_limit", new_callable=AsyncMock)
    def test_rejects_invalid_signature(self, _rate, mock_settings, client):
        mock_settings.return_value.github.webhook_secret = WEBHOOK_SECRET
        payload = json.dumps(_make_webhook_payload()).encode()
        resp = client.post(
            "/webhook/github",
            content=payload,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "issues",
                "X-Hub-Signature-256": "sha256=bad",
            },
        )
        assert resp.status_code == 401

    @patch("api.routes.webhook.get_settings")
    @patch("api.routes.webhook.check_webhook_rate_limit", new_callable=AsyncMock)
    def test_ignores_non_issue_events(self, _rate, mock_settings, client):
        mock_settings.return_value.github.webhook_secret = WEBHOOK_SECRET
        payload = json.dumps({"action": "created"}).encode()
        sig = _sign_payload(payload, WEBHOOK_SECRET)
        resp = client.post(
            "/webhook/github",
            content=payload,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "push",
                "X-Hub-Signature-256": sig,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ignored"

    @patch("api.routes.webhook.get_settings")
    @patch("api.routes.webhook.check_webhook_rate_limit", new_callable=AsyncMock)
    @patch("modules.monitoring.enqueue_issue")
    @patch("modules.monitoring.is_already_queued", return_value=False)
    @patch("modules.monitoring.mark_as_queued")
    def test_enqueues_valid_issue(
        self,
        mock_mark,
        mock_dedup,
        mock_enqueue,
        _rate,
        mock_settings,
        client,
    ):
        """A valid webhook with correct signature enqueues the issue."""
        mock_settings.return_value.github.webhook_secret = WEBHOOK_SECRET
        mock_settings.return_value.filtering.exclude_labels = ["wontfix"]
        mock_settings.return_value.filtering.exclude_authors = ["dependabot"]
        mock_settings.return_value.filtering.min_body_length = 10
        mock_settings.return_value.filtering.max_issue_age_days = 30
        mock_settings.return_value.filtering.trigger_labels = ["bug"]
        mock_settings.return_value.filtering.trigger_keywords = [
            "TypeError",
            "ValueError",
            "Exception",
        ]
        mock_settings.return_value.monitoring.webhook_rate_limit_per_minute = 60
        mock_settings.return_value.redis.url = ""

        payload_bytes = json.dumps(_make_webhook_payload()).encode()
        sig = _sign_payload(payload_bytes, WEBHOOK_SECRET)

        resp = client.post(
            "/webhook/github",
            content=payload_bytes,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "issues",
                "X-Hub-Signature-256": sig,
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "queued"
        assert data["issue_id"] == 42
        assert data["repo"] == "acme/webapp"

        # enqueue_issue was called with a QueuedIssue
        mock_enqueue.assert_called_once()
        queued = mock_enqueue.call_args[0][0]
        assert queued.issue_id == 42
        assert queued.repo_full_name == "acme/webapp"


class TestProcessingPipeline:
    """Exercise the Celery pipeline stages against a real DB."""

    @pytest.fixture(autouse=True)
    def _seed_issue(self, db_session):
        """Insert a pending Issue row for all tests in this class."""
        self.issue = Issue(
            queue_id=uuid4(),
            github_issue_id=42,
            repo_full_name="acme/webapp",
            repo_url="https://github.com/acme/webapp",
            title="TypeError in user authentication",
            body=ISSUE_BODY,
            labels=["bug", "high-priority"],
            author="alice",
            priority=2,
            status="pending",
        )
        db_session.add(self.issue)
        db_session.commit()
        db_session.refresh(self.issue)
        self.db = db_session

    # -- helpers --

    def _get_issue(self):
        self.db.refresh(self.issue)
        return self.issue

    # -- Stage 1: Validation saved to DB --

    def test_validation_saved(self):
        """_save_validation_result writes a Validation row and returns it."""
        from tasks.processing import _save_validation_result

        vr = _build_validation_result()
        val = _save_validation_result(self.db, self.issue.id, vr)

        assert val.id is not None
        assert val.valid is True
        assert val.validity_status == "confirmed"
        assert val.match_score == pytest.approx(0.92)
        assert val.error_signature == "TypeError: 'NoneType' object is not subscriptable"

        # Persisted in DB
        rows = self.db.query(Validation).filter_by(issue_id=self.issue.id).all()
        assert len(rows) == 1

    # -- Stage 2: Proposal saved to DB --

    def test_proposal_saved(self):
        """_save_proposal writes a FixProposal row linked to issue + validation."""
        from tasks.processing import _save_proposal, _save_validation_result

        vr = _build_validation_result()
        val = _save_validation_result(self.db, self.issue.id, vr)

        fp = _build_fix_proposal()
        db_prop = _save_proposal(self.db, self.issue.id, val.id, fp)

        assert db_prop.id is not None
        assert db_prop.status == "pending_audit"
        assert db_prop.suggested_patch == SAMPLE_DIFF
        assert db_prop.lines_added == 1
        assert db_prop.lines_removed == 1
        assert db_prop.llm_model == "gpt-4"

        rows = self.db.query(DBFixProposal).filter_by(issue_id=self.issue.id).all()
        assert len(rows) == 1

    # -- Stage 3: Security report saved to DB --

    def test_security_report_saved(self):
        """_save_security_report writes a SecurityReport row linked to proposal."""
        from tasks.processing import (
            _save_proposal,
            _save_security_report,
            _save_validation_result,
        )

        vr = _build_validation_result()
        val = _save_validation_result(self.db, self.issue.id, vr)

        fp = _build_fix_proposal()
        db_prop = _save_proposal(self.db, self.issue.id, val.id, fp)

        sr = _build_security_report(fp.proposal_id)
        db_sr = _save_security_report(self.db, db_prop.id, sr)

        assert db_sr.id is not None
        assert db_sr.has_vulnerabilities is False
        assert db_sr.risk_score == pytest.approx(0.0)
        assert db_sr.recommendation == "approve"

        rows = (
            self.db.query(DBSecurityReport)
            .filter_by(proposal_id=db_prop.id)
            .all()
        )
        assert len(rows) == 1

    # -- Full pipeline: process_issue --

    @patch("tasks.processing.get_session_factory")
    @patch("modules.validation.validate_issue", new_callable=AsyncMock)
    @patch("modules.validation.clone_repository")
    @patch("modules.fix_generator.generate_fix", new_callable=AsyncMock)
    @patch("modules.security_auditor.audit_fix", new_callable=AsyncMock)
    @patch("modules.approval.post_proposal_comment", new_callable=AsyncMock)
    @patch("tasks.polling.poll_approval")
    def test_full_pipeline_happy_path(
        self,
        mock_poll,
        mock_comment,
        mock_audit,
        mock_gen_fix,
        mock_clone,
        mock_validate,
        mock_session_factory,
    ):
        """
        End-to-end: issue goes from 'pending' to 'pending_approval'
        with all intermediate DB records created.
        """
        # -- Wire mocks --
        # Session factory returns our test session
        mock_session_factory.return_value = sessionmaker(bind=self.db.get_bind())

        # Validation: confirmed
        mock_validate.return_value = _build_validation_result()

        # Clone: returns a dummy dir (we mock generate_fix so it's unused)
        mock_clone.return_value = "/tmp/fake-repo"

        # Fix generation: returns a proposal
        fp = _build_fix_proposal()
        mock_gen_fix.return_value = fp

        # Security audit: clean
        mock_audit.return_value = _build_security_report(fp.proposal_id)

        # Approval comment: returns a fake comment ID
        mock_comment.return_value = 99999
        mock_poll.apply_async = MagicMock()

        # -- Execute --
        from tasks.processing import process_issue

        # Call the inner function directly (no Celery broker needed)
        # We need to bypass the @shared_task decorator
        process_issue(self.issue.id)

        # -- Assertions --
        # Expire cached objects so the test session re-reads from DB
        self.db.expire_all()

        # 1. Issue status updated to pending_approval
        issue = self.db.query(Issue).filter_by(id=self.issue.id).first()
        assert issue.status == "pending_approval"

        # 2. Validation record exists
        vals = self.db.query(Validation).filter_by(issue_id=self.issue.id).all()
        assert len(vals) == 1
        assert vals[0].valid is True
        assert vals[0].validity_status == "confirmed"

        # 3. Proposal record exists with correct status
        props = self.db.query(DBFixProposal).filter_by(issue_id=self.issue.id).all()
        assert len(props) == 1
        assert props[0].status == "pending_approval"
        assert props[0].suggested_patch == SAMPLE_DIFF

        # 4. Security report exists
        reports = (
            self.db.query(DBSecurityReport)
            .filter_by(proposal_id=props[0].id)
            .all()
        )
        assert len(reports) == 1
        assert reports[0].recommendation == "approve"

        # 5. Approval record exists
        approvals = (
            self.db.query(Approval)
            .filter_by(proposal_id=props[0].id)
            .all()
        )
        assert len(approvals) == 1
        assert approvals[0].status == "pending"
        assert approvals[0].comment_id == 99999

        # 6. Approval polling was scheduled
        mock_poll.apply_async.assert_called_once()

    @patch("tasks.processing.get_session_factory")
    @patch("modules.validation.validate_issue", new_callable=AsyncMock)
    def test_pipeline_stops_when_not_reproducible(
        self,
        mock_validate,
        mock_session_factory,
    ):
        """If validation fails, issue is marked 'not_reproducible' and no fix is generated."""
        mock_session_factory.return_value = sessionmaker(bind=self.db.get_bind())

        # Return a failing validation
        vr = _build_validation_result()
        vr.valid = False
        vr.validity_status = "not_reproduced"
        vr.reproduction_result.valid = False
        vr.reproduction_result.validity_status = "not_reproduced"
        vr.reproduction_result.match_score = 0.0
        mock_validate.return_value = vr

        from tasks.processing import process_issue

        process_issue(self.issue.id)

        self.db.expire_all()
        issue = self.db.query(Issue).filter_by(id=self.issue.id).first()
        assert issue.status == "not_reproducible"

        # No proposal should be created
        assert self.db.query(DBFixProposal).filter_by(issue_id=self.issue.id).count() == 0

    @patch("tasks.processing.get_session_factory")
    @patch("modules.validation.validate_issue", new_callable=AsyncMock)
    @patch("modules.validation.clone_repository")
    @patch("modules.fix_generator.generate_fix", new_callable=AsyncMock)
    def test_pipeline_stops_when_fix_fails(
        self,
        mock_gen_fix,
        mock_clone,
        mock_validate,
        mock_session_factory,
    ):
        """If LLM fails to produce a fix, issue is marked 'fix_failed'."""
        mock_session_factory.return_value = sessionmaker(bind=self.db.get_bind())
        mock_validate.return_value = _build_validation_result()
        mock_clone.return_value = "/tmp/fake-repo"
        mock_gen_fix.return_value = None  # No fix produced

        from tasks.processing import process_issue

        process_issue(self.issue.id)

        self.db.expire_all()
        issue = self.db.query(Issue).filter_by(id=self.issue.id).first()
        assert issue.status == "fix_failed"

    @patch("tasks.processing.get_session_factory")
    @patch("modules.validation.validate_issue", new_callable=AsyncMock)
    @patch("modules.validation.clone_repository")
    @patch("modules.fix_generator.generate_fix", new_callable=AsyncMock)
    @patch("modules.security_auditor.audit_fix", new_callable=AsyncMock)
    def test_pipeline_stops_when_security_rejects(
        self,
        mock_audit,
        mock_gen_fix,
        mock_clone,
        mock_validate,
        mock_session_factory,
    ):
        """If security audit recommends 'reject', issue is marked 'security_rejected'."""
        mock_session_factory.return_value = sessionmaker(bind=self.db.get_bind())
        mock_validate.return_value = _build_validation_result()
        mock_clone.return_value = "/tmp/fake-repo"

        fp = _build_fix_proposal()
        mock_gen_fix.return_value = fp

        sr = _build_security_report(fp.proposal_id)
        sr.has_vulnerabilities = True
        sr.risk_score = 0.95
        sr.recommendation = "reject"
        mock_audit.return_value = sr

        from tasks.processing import process_issue

        process_issue(self.issue.id)

        self.db.expire_all()
        issue = self.db.query(Issue).filter_by(id=self.issue.id).first()
        assert issue.status == "security_rejected"

        props = self.db.query(DBFixProposal).filter_by(issue_id=self.issue.id).all()
        assert len(props) == 1
        assert props[0].status == "security_rejected"


class TestApprovalComment:
    """Verify the proposal comment contains expected sections."""

    def test_format_security_summary_clean(self):
        """Clean report produces a short 'no issues' summary."""
        from modules.approval import format_security_summary

        sr = _build_security_report(uuid4())
        result = format_security_summary(sr)
        assert result == "No security issues detected"

    def test_format_security_summary_with_findings(self):
        """Report with findings includes severity table, CWE tags, fix suggestions."""
        from models.schemas import Finding
        from modules.approval import format_security_summary

        finding = Finding(
            scanner="bandit",
            rule_id="B602",
            cwe="CWE-78",
            severity="critical",
            confidence="high",
            file="auth/login.py",
            line_start=10,
            line_end=10,
            message="Possible shell injection via subprocess",
            recommendation="Use subprocess with shell=False",
        )

        sr = SecurityReport(
            proposal_id=uuid4(),
            has_vulnerabilities=True,
            risk_score=0.85,
            findings_count=1,
            findings_by_severity={"critical": 1},
            findings=[finding],
            critical_findings=[finding],
            scanners_used=["bandit"],
            scan_duration=1.5,
            recommendation="reject",
        )

        result = format_security_summary(sr)

        # Risk score present
        assert "0.85" in result
        # Severity table
        assert "critical" in result.lower()
        # CWE tag
        assert "[CWE-78]" in result
        # Fix suggestion
        assert "shell=False" in result
        # OWASP reference
        assert "owasp.org" in result


class TestDiffValidation:
    """Verify diff parsing and syntax validation on realistic inputs."""

    def test_extract_and_parse_round_trip(self):
        """extract_diff → parse_unified_diff produces correct structure."""
        from modules.fix_generator import extract_diff, parse_unified_diff

        llm_response = f"Here is the fix:\n\n```diff\n{SAMPLE_DIFF}```\n"
        diff = extract_diff(llm_response)
        assert diff is not None

        parsed = parse_unified_diff(diff)
        assert len(parsed.files) == 1
        assert parsed.files[0].path == "auth/login.py"

        # Should have exactly 1 hunk
        assert len(parsed.files[0].hunks) == 1
        hunk = parsed.files[0].hunks[0]

        # The hunk should contain both an add and a remove line
        types = {line.type for line in hunk.lines}
        assert "add" in types
        assert "remove" in types

    def test_validate_diff_syntax_good(self):
        from modules.fix_generator import validate_diff_syntax

        ok, err = validate_diff_syntax(SAMPLE_DIFF)
        assert ok is True
        assert err is None

    def test_validate_diff_syntax_bad(self):
        from modules.fix_generator import validate_diff_syntax

        ok, err = validate_diff_syntax("This is not a diff at all")
        assert ok is False
        assert err is not None


class TestTokenEstimation:
    """Verify tiktoken-based estimation works and fallback is sane."""

    def test_estimate_tokens_returns_positive(self):
        from modules.fix_generator import estimate_tokens

        count = estimate_tokens("Hello, world! This is a test.")
        assert count > 0

    def test_truncate_preserves_short_text(self):
        from modules.fix_generator import truncate_for_context

        short = "Small text."
        assert truncate_for_context(short, max_tokens=1000) == short

    def test_truncate_adds_marker(self):
        from modules.fix_generator import truncate_for_context

        long_text = "word " * 5000  # ~5000 tokens
        result = truncate_for_context(long_text, max_tokens=50)
        assert "[truncated]" in result
        assert len(result) < len(long_text)

    def test_truncate_preserve_end(self):
        from modules.fix_generator import truncate_for_context

        long_text = "word " * 5000
        result = truncate_for_context(long_text, max_tokens=50, preserve_end=True)
        assert result.startswith("... [truncated] ...")


class TestSimilarityScoring:
    """Verify the improved _compute_similarity scoring tiers."""

    def test_exact_match(self):
        from modules.validation import _compute_similarity

        score = _compute_similarity("TypeError: bad", "TypeError: bad")
        assert score == 1.0

    def test_containment(self):
        from modules.validation import _compute_similarity

        score = _compute_similarity(
            "TypeError: bad",
            "Lots of output\nTypeError: bad\nmore stuff",
        )
        assert score >= 0.9

    def test_type_match_boosts(self):
        from modules.validation import _compute_similarity

        score = _compute_similarity(
            "TypeError: expected str",
            "TypeError: unexpected None value",
        )
        # Error type matches → should be at least 0.7
        assert score >= 0.7

    def test_no_match(self):
        from modules.validation import _compute_similarity

        score = _compute_similarity(
            "TypeError: something",
            "All tests passed successfully",
        )
        assert score < 0.5

    def test_empty_returns_zero(self):
        from modules.validation import _compute_similarity

        assert _compute_similarity("", "something") == 0.0
        assert _compute_similarity("something", "") == 0.0


class TestSecurityAuditCWE:
    """Verify expanded CWE mapping covers OWASP Top 10."""

    def test_cwe_map_has_owasp_coverage(self):
        from modules.security_auditor import CWE_SEVERITY_MAP

        # At least 100 CWE entries (we expanded to ~150)
        assert len(CWE_SEVERITY_MAP) >= 100

        # Spot-check key entries from each OWASP category
        assert CWE_SEVERITY_MAP["CWE-78"] == "critical"  # A03 Injection
        assert CWE_SEVERITY_MAP["CWE-89"] == "critical"  # A03 SQL Injection
        assert CWE_SEVERITY_MAP["CWE-22"] == "high"  # A01 Path Traversal
        assert CWE_SEVERITY_MAP["CWE-327"] == "medium"  # A02 Crypto
        assert CWE_SEVERITY_MAP["CWE-918"] == "high"  # A10 SSRF
        assert CWE_SEVERITY_MAP["CWE-502"] == "critical"  # Deserialization
        assert CWE_SEVERITY_MAP["CWE-287"] == "high"  # A07 Auth
        assert CWE_SEVERITY_MAP["CWE-611"] == "high"  # A05 XXE

    def test_owasp_references_present(self):
        from modules.security_auditor import OWASP_REFERENCES

        assert "CWE-78" in OWASP_REFERENCES
        assert "CWE-89" in OWASP_REFERENCES
        assert "CWE-918" in OWASP_REFERENCES
        assert "owasp.org" in OWASP_REFERENCES["CWE-78"]


class TestFallbackParseBashExtraction:
    """Verify bash/sh code block extraction from issue bodies."""

    def test_extracts_bash_commands(self):
        from modules.validation import _fallback_parse

        title = "Bug: crash on startup"
        body = """\
The app crashes. To reproduce:

```bash
$ pip install -e .
$ python main.py --verbose
```

Expected: no crash.
"""
        ctx = _fallback_parse(title, body)
        assert len(ctx.reproduction_steps) >= 2
        assert "pip install -e ." in ctx.reproduction_steps
        assert "python main.py --verbose" in ctx.reproduction_steps

    def test_strips_comment_lines(self):
        from modules.validation import _fallback_parse

        title = "Error"
        body = """\
```sh
# This is a comment
$ python run.py
```
"""
        ctx = _fallback_parse(title, body)
        assert any("python run.py" in step for step in ctx.reproduction_steps)
        assert not any(step.startswith("#") for step in ctx.reproduction_steps)
