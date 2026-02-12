# AutoResolve

Automated GitHub issue resolution system that monitors repositories for bug reports, validates reproducibility in isolated sandboxes, generates AI-assisted patches using LLMs, audits patches for security vulnerabilities, and applies changes only after explicit owner approval.

## Tech Stack

- **Language**: Python 3.11+
- **Framework**: FastAPI with Uvicorn (ASGI)
- **Database**: PostgreSQL 16 with SQLAlchemy 2.0+ ORM
- **Migrations**: Alembic
- **Cache**: Redis 7+
- **Task Queue**: Celery 5.3+ with RabbitMQ 3.12+
- **Validation**: Pydantic v2.5+
- **External APIs**: httpx (GitHub API), OpenAI, Docker SDK
- **Security Scanning**: Bandit, Semgrep
- **Testing**: pytest with pytest-cov, pytest-asyncio

## Project Structure

```
app/                    # FastAPI application core (main.py, config.py, dependencies.py)
api/routes/             # REST API endpoints (webhook, repos, issues, proposals)
api/middleware/         # Auth, rate limiting, logging middleware
modules/                # Core business logic (5 modules in pipeline)
  monitoring.py         # Webhook handling, issue filtering
  validation.py         # Issue parsing, sandbox reproduction
  fix_generator.py      # LLM-based patch generation
  security_auditor.py   # Bandit/Semgrep scanning
  approval.py           # PR creation, maintainer polling
models/                 # SQLAlchemy ORM models + Pydantic schemas
services/               # External integrations (GitHub, LLM, Docker)
tasks/                  # Celery async tasks and app configuration
utils/                  # Utilities (diff parsing, signature verification, logging)
templates/              # Jinja2 templates for comments and LLM prompts
tests/                  # pytest test suite with fixtures
migrations/             # Alembic database migrations
docker/                 # Dockerfiles for API, worker, and sandbox images
scripts/                # Setup and utility scripts
```

## Common Commands

```bash
# Development
make install           # Install dependencies
make dev               # Run dev server (uvicorn with --reload)
make worker            # Run Celery worker
make beat              # Run Celery beat scheduler

# Testing
make test              # Run pytest with coverage

# Code Quality
make lint              # Run flake8 + mypy
make format            # Run black + isort

# Database
make db-migrate        # Run alembic upgrade head
make db-init           # Initialize database

# Docker
make docker-build      # Build Docker images
make docker-up         # Start all services
make docker-down       # Stop all services
```

## Code Style

- **Formatter**: Black (line length 88)
- **Imports**: isort
- **Linting**: Flake8 + mypy
- **Type Hints**: Required for all function parameters and return types
- **Docstrings**: Google-style for all public functions/classes

## Testing

- Test files: `tests/test_*.py`
- Fixtures: `tests/conftest.py`
- Database: SQLite in-memory for tests
- Coverage targets: 90% unit, 80% integration, 100% API endpoints
- Run single test: `pytest tests/test_module.py::TestClass::test_name -v`

## Architecture

Pipeline flow:
```
GitHub Webhook → Monitoring → Task Queue (Celery) → Validation → Fix Generation → Security Audit → Approval → PR Merge
```

All routes are async. Uses dependency injection via FastAPI's `Depends()`. External services are mocked in tests.

## Configuration

- `config.yaml`: Master configuration file
- Environment variables override config values using `${VAR_NAME}` syntax
- Required env vars: `DATABASE_URL`, `REDIS_URL`, `CELERY_BROKER_URL`, `GITHUB_APP_ID`, `GITHUB_WEBHOOK_SECRET`, `OPENAI_API_KEY`

## Key Patterns

- **Dependency Injection**: FastAPI Depends() for DB sessions, config
- **Service Layer**: Separate services for GitHub, LLM, Docker operations
- **Retry Logic**: Exponential backoff for external API calls
- **Structured Logging**: structlog with JSON format
- **Error Handling**: Specific exception types, global FastAPI handler

## Commit Convention

Conventional Commits: `feat:`, `fix:`, `docs:`, `style:`, `refactor:`, `test:`, `chore:`
