"""
Pytest configuration and fixtures for AutoResolve tests.
"""

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Generator
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings, get_settings
from app.main import app
from models.database import Base, Issue, FixProposal, Validation, SecurityReport, Approval
from models.schemas import QueuedIssue, IssueContext, FixProposal as FixProposalSchema


# Test database URL (SQLite in memory)
TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """Create test settings."""
    settings = Settings()
    settings.app.debug = True
    settings.database.url = TEST_DATABASE_URL
    return settings


@pytest.fixture(scope="function")
def db_engine():
    """Create test database engine."""
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def db_session(db_engine):
    """Create test database session."""
    SessionLocal = sessionmaker(bind=db_engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def client(db_session) -> Generator:
    """Create test client with database session override."""
    def override_get_db():
        yield db_session

    from app.dependencies import get_db
    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def sample_issue() -> dict:
    """Sample GitHub issue payload."""
    return {
        "number": 123,
        "title": "TypeError in user authentication",
        "body": """## Description
When trying to login, I get a TypeError.

## Error
```
Traceback (most recent call last):
  File "auth/login.py", line 42, in authenticate
    user = get_user(None)
TypeError: 'NoneType' object is not subscriptable
```

## Steps to reproduce
1. Go to login page
2. Enter valid credentials
3. Click login button

## Expected behavior
User should be logged in successfully.

## Environment
- Python 3.11
- Django 4.2
""",
        "labels": [{"name": "bug"}, {"name": "high-priority"}],
        "user": {"login": "testuser"},
        "created_at": "2026-01-09T10:00:00Z",
        "html_url": "https://github.com/testorg/testrepo/issues/123",
        "state": "open"
    }


@pytest.fixture
def sample_webhook_payload(sample_issue) -> dict:
    """Sample GitHub webhook payload."""
    return {
        "action": "opened",
        "issue": sample_issue,
        "repository": {
            "full_name": "testorg/testrepo",
            "html_url": "https://github.com/testorg/testrepo",
            "default_branch": "main"
        },
        "sender": {"login": "testuser"}
    }


@pytest.fixture
def queued_issue() -> QueuedIssue:
    """Create a queued issue for testing."""
    return QueuedIssue(
        issue_id=123,
        repo_url="https://github.com/testorg/testrepo",
        repo_full_name="testorg/testrepo",
        title="TypeError in user authentication",
        body="Error when logging in: TypeError",
        labels=["bug"],
        author="testuser",
        created_at=datetime.utcnow(),
        priority=2
    )


@pytest.fixture
def issue_context() -> IssueContext:
    """Create an issue context for testing."""
    from models.schemas import EnvironmentInfo

    return IssueContext(
        error_type="TypeError",
        error_message="'NoneType' object is not subscriptable",
        affected_files=["auth/login.py"],
        affected_functions=["authenticate", "get_user"],
        stack_trace="Traceback...",
        reproduction_steps=["Go to login", "Enter credentials", "Click login"],
        expected_behavior="User logged in",
        actual_behavior="TypeError raised",
        environment=EnvironmentInfo(python_version="3.11"),
        code_snippets=[],
        parse_confidence=0.85
    )


@pytest.fixture
def sample_diff() -> str:
    """Sample unified diff."""
    return """--- a/auth/login.py
+++ b/auth/login.py
@@ -1,5 +1,5 @@
 def authenticate(username, password):
     \"\"\"Authenticate a user.\"\"\"
-    user = get_user(None)
+    user = get_user(username)
     if user:
         return True
"""


@pytest.fixture
def db_issue(db_session) -> Issue:
    """Create a database issue for testing."""
    issue = Issue(
        queue_id=uuid4(),
        github_issue_id=123,
        repo_full_name="testorg/testrepo",
        repo_url="https://github.com/testorg/testrepo",
        title="TypeError in authentication",
        body="Error description",
        labels=["bug"],
        author="testuser",
        priority=2,
        status="pending"
    )
    db_session.add(issue)
    db_session.commit()
    db_session.refresh(issue)
    return issue


@pytest.fixture
def db_validation(db_session, db_issue) -> Validation:
    """Create a database validation for testing."""
    validation = Validation(
        issue_id=db_issue.id,
        valid=True,
        validity_status="confirmed",
        match_score=0.92,
        error_signature="TypeError: 'NoneType' object is not subscriptable"
    )
    db_session.add(validation)
    db_session.commit()
    db_session.refresh(validation)
    return validation


@pytest.fixture
def db_proposal(db_session, db_issue, db_validation, sample_diff) -> FixProposal:
    """Create a database fix proposal for testing."""
    proposal = FixProposal(
        proposal_id=uuid4(),
        issue_id=db_issue.id,
        validation_id=db_validation.id,
        suggested_patch=sample_diff,
        affected_files=["auth/login.py"],
        lines_added=1,
        lines_removed=1,
        llm_model="gpt-4",
        status="pending_approval"
    )
    db_session.add(proposal)
    db_session.commit()
    db_session.refresh(proposal)
    return proposal


@pytest.fixture
def temp_repo() -> Generator[str, None, None]:
    """Create a temporary git repository for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        import subprocess

        # Initialize git repo
        subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmpdir, capture_output=True
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmpdir, capture_output=True
        )

        # Create sample files
        (Path(tmpdir) / "auth").mkdir()
        (Path(tmpdir) / "auth" / "__init__.py").write_text("")
        (Path(tmpdir) / "auth" / "login.py").write_text("""
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
""")
        (Path(tmpdir) / "requirements.txt").write_text("pytest>=7.0\n")

        # Commit files
        subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"],
            cwd=tmpdir, capture_output=True
        )

        yield tmpdir


@pytest.fixture
def mock_github_service():
    """Mock GitHub service for testing."""
    with patch("services.github_service.GitHubService") as mock:
        instance = mock.return_value
        instance.get_issues = AsyncMock(return_value=[])
        instance.get_issue = AsyncMock(return_value={})
        instance.create_issue_comment = AsyncMock(return_value=12345)
        instance.is_maintainer = AsyncMock(return_value=True)
        instance.get_default_branch = AsyncMock(return_value="main")
        instance.create_branch = AsyncMock()
        instance.create_pull_request = AsyncMock(return_value={
            "number": 1,
            "html_url": "https://github.com/test/repo/pull/1"
        })
        instance.close = AsyncMock()
        yield instance


@pytest.fixture
def mock_llm_service():
    """Mock LLM service for testing."""
    with patch("services.llm_service.LLMService") as mock:
        instance = mock.return_value
        instance.complete = AsyncMock(return_value="""```diff
--- a/auth/login.py
+++ b/auth/login.py
@@ -10,7 +10,7 @@ def authenticate(username, password):
-    user = get_user(None)
+    user = get_user(username)
```""")
        yield instance


@pytest.fixture
def mock_docker_service():
    """Mock Docker service for testing."""
    with patch("services.docker_service.DockerService") as mock:
        instance = mock.return_value
        instance.run_in_sandbox = MagicMock(return_value={
            "stdout": "",
            "stderr": "TypeError: 'NoneType' object is not subscriptable",
            "exit_code": 1,
            "duration": 5.0
        })
        instance.pull_image = MagicMock(return_value=True)
        yield instance
