# Changelog

All notable changes to AutoResolve will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Project documentation files (CONTRIBUTING.md, CHANGELOG.md, SECURITY.md)
- GitHub issue and pull request templates

## [1.0.0] - 2026-01-22

### Added
- Core AutoResolve system implementation
  - **Monitoring Module**: GitHub webhook handling and fallback polling
  - **Validation Module**: Issue parsing, sandbox reproduction, context extraction
  - **Fix Generation Module**: LLM-based patch generation with retry logic
  - **Security Audit Module**: Bandit and Semgrep integration for vulnerability scanning
  - **Approval Module**: PR creation, maintainer approval polling, auto-merge
- FastAPI REST API with endpoints for:
  - Webhook receiver (`POST /webhook/github`)
  - Repository management (`/api/repos`)
  - Issue tracking (`/api/issues`)
  - Fix proposals (`/api/proposals`)
  - Security reports (`/api/reports`)
- Celery task queue integration with RabbitMQ
- PostgreSQL database with SQLAlchemy ORM models
- Redis caching for rate limiting and deduplication
- Docker sandbox environments for safe issue reproduction
- Utility modules:
  - Diff parser for unified diff handling
  - Language detector for multi-language support
  - Error signature extraction
  - Structured logging with structlog
- Jinja2 templates for GitHub comments and LLM prompts
- Comprehensive test suite with pytest
- Docker Compose configuration for local development
- Makefile with common development commands
- Alembic database migrations

### Security
- Webhook signature verification (X-Hub-Signature-256)
- Network-isolated Docker sandboxes
- Resource limits on sandbox containers
- Mandatory security scanning before PR creation
- API key authentication for management endpoints

## [0.2.0] - 2026-01-21

### Changed
- Applied Black code formatting to entire codebase
- Fixed mypy type errors across all modules
- Fixed isort import ordering issues
- Addressed Pylint and Bandit static analysis findings
- Added docstrings to functions and reduced cyclomatic complexity

### Removed
- Unused imports and variables

## [0.1.0] - 2026-01-20

### Added
- Initial project structure and README specification
- MIT License
- Basic .gitignore for Python projects
- Sandbox Dockerfiles for Python and Node.js
- Database migration infrastructure with Alembic
- Test fixtures and configuration validation

---

## Version History Summary

| Version | Date       | Highlights                                    |
|---------|------------|-----------------------------------------------|
| 1.0.0   | 2026-01-22 | Full system implementation, production-ready  |
| 0.2.0   | 2026-01-21 | Code quality improvements, static analysis    |
| 0.1.0   | 2026-01-20 | Initial release with core infrastructure      |
