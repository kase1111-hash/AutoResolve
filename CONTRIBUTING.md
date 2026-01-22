# Contributing to AutoResolve

Thank you for your interest in contributing to AutoResolve! This document provides guidelines and instructions for contributing to the project.

## Table of Contents

- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Project Structure](#project-structure)
- [Making Changes](#making-changes)
- [Code Style](#code-style)
- [Testing](#testing)
- [Pull Request Process](#pull-request-process)
- [Reporting Issues](#reporting-issues)

## Getting Started

1. Fork the repository on GitHub
2. Clone your fork locally:
   ```bash
   git clone https://github.com/YOUR_USERNAME/AutoResolve.git
   cd AutoResolve
   ```
3. Add the upstream repository as a remote:
   ```bash
   git remote add upstream https://github.com/kase1111-hash/AutoResolve.git
   ```

## Development Setup

### Prerequisites

- Python 3.11 or higher
- Docker and Docker Compose
- PostgreSQL 16 (or use Docker)
- Redis 7+ (or use Docker)
- RabbitMQ 3.12+ (or use Docker)

### Installation

1. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. Install dependencies:
   ```bash
   make install
   # Or manually:
   pip install -r requirements.txt
   ```

3. Set up environment variables:
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

4. Start infrastructure services with Docker:
   ```bash
   make docker-up
   ```

5. Run database migrations:
   ```bash
   make db-migrate
   ```

6. Start the development server:
   ```bash
   make dev
   ```

### Using Docker Compose (Full Stack)

For a complete development environment:

```bash
docker-compose up -d
```

This starts the API server, Celery workers, PostgreSQL, Redis, and RabbitMQ.

## Project Structure

```
AutoResolve/
├── app/                    # FastAPI application core
├── api/                    # REST API routes and middleware
├── modules/                # Core business logic modules
│   ├── monitoring.py       # GitHub event monitoring
│   ├── validation.py       # Issue reproduction validation
│   ├── fix_generator.py    # LLM-based patch generation
│   ├── security_auditor.py # Vulnerability scanning
│   └── approval.py         # PR approval workflow
├── services/               # External service integrations
├── models/                 # Database and Pydantic models
├── tasks/                  # Celery async tasks
├── utils/                  # Utility modules
├── templates/              # Jinja2 templates
├── tests/                  # Test suite
├── migrations/             # Alembic migrations
├── docker/                 # Docker build files
└── scripts/                # Setup and utility scripts
```

## Making Changes

1. Create a new branch for your changes:
   ```bash
   git checkout -b feature/your-feature-name
   # or
   git checkout -b fix/issue-description
   ```

2. Make your changes, following the code style guidelines below

3. Write or update tests as needed

4. Commit your changes with a descriptive message:
   ```bash
   git commit -m "feat: add new feature description"
   ```

### Commit Message Format

We follow the [Conventional Commits](https://www.conventionalcommits.org/) specification:

- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation changes
- `style:` - Code style changes (formatting, no code change)
- `refactor:` - Code refactoring
- `test:` - Adding or updating tests
- `chore:` - Maintenance tasks

## Code Style

### Python Code Style

- We use [Black](https://github.com/psf/black) for code formatting
- We use [isort](https://github.com/PyCQA/isort) for import sorting
- We use [Flake8](https://flake8.pycqa.org/) for linting
- We use [mypy](https://mypy.readthedocs.io/) for type checking

Run the formatters and linters:

```bash
make format  # Runs black and isort
make lint    # Runs flake8 and mypy
```

### Code Guidelines

1. **Type Hints**: Use type hints for all function parameters and return values
2. **Docstrings**: Add docstrings to all public functions, classes, and modules
3. **Error Handling**: Use specific exception types; avoid bare `except` clauses
4. **Logging**: Use structured logging via `structlog`
5. **Security**: Follow OWASP guidelines; never hardcode secrets

### Example Function

```python
def process_issue(
    issue_id: int,
    repo_name: str,
    *,
    force_reprocess: bool = False,
) -> ProcessingResult:
    """
    Process a GitHub issue through the validation pipeline.

    Args:
        issue_id: The GitHub issue number.
        repo_name: Full repository name (owner/repo).
        force_reprocess: If True, reprocess even if already processed.

    Returns:
        ProcessingResult containing validation status and any generated fix.

    Raises:
        IssueNotFoundError: If the issue does not exist.
        ValidationError: If validation fails unexpectedly.
    """
    ...
```

## Testing

### Running Tests

```bash
# Run all tests
make test

# Run with coverage report
pytest --cov=app --cov-report=html

# Run specific test file
pytest tests/test_validation.py

# Run specific test
pytest tests/test_validation.py::test_valid_issue_reproduction
```

### Writing Tests

- Place tests in the `tests/` directory
- Use descriptive test names that explain the expected behavior
- Use fixtures from `conftest.py` for common setup
- Mock external services (GitHub API, OpenAI, etc.)

Example test:

```python
import pytest
from modules.validation import validate_issue

def test_valid_issue_is_reproduced(mock_github, mock_docker):
    """Confirm that a valid bug report is correctly reproduced."""
    issue = create_test_issue(
        title="TypeError in auth module",
        body="Traceback shows TypeError on line 42"
    )

    result = validate_issue(issue)

    assert result.valid is True
    assert result.match_score >= 0.8
```

### Test Coverage

We aim for:
- Unit tests: >= 90% coverage
- Integration tests: >= 80% coverage
- All API endpoints: 100% coverage

## Pull Request Process

1. **Update your branch** with the latest upstream changes:
   ```bash
   git fetch upstream
   git rebase upstream/main
   ```

2. **Push your branch** to your fork:
   ```bash
   git push origin feature/your-feature-name
   ```

3. **Open a Pull Request** on GitHub with:
   - A clear title describing the change
   - A description of what was changed and why
   - Reference to any related issues (e.g., "Fixes #123")

4. **Address review feedback** by pushing additional commits

5. **Ensure CI passes** - all tests and linters must pass

### PR Requirements

- [ ] Code follows the project style guidelines
- [ ] Tests have been added/updated for the changes
- [ ] Documentation has been updated if needed
- [ ] All CI checks pass
- [ ] The PR has a clear description

## Reporting Issues

### Bug Reports

When reporting a bug, please include:

1. **Environment details**: OS, Python version, package versions
2. **Steps to reproduce**: Detailed steps to reproduce the issue
3. **Expected behavior**: What you expected to happen
4. **Actual behavior**: What actually happened
5. **Logs/Screenshots**: Any relevant error messages or screenshots

### Feature Requests

When requesting a feature, please include:

1. **Use case**: Describe the problem you're trying to solve
2. **Proposed solution**: Your idea for how to solve it
3. **Alternatives considered**: Other solutions you've thought about

## Questions?

If you have questions about contributing, feel free to:

- Open a GitHub Discussion
- Check existing issues for similar questions
- Review the README for project documentation

Thank you for contributing to AutoResolve!
