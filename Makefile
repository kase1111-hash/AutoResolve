.PHONY: help install dev test lint format clean docker-build docker-up docker-down db-migrate

help:
	@echo "AutoResolve - Automated GitHub Issue Resolution System"
	@echo ""
	@echo "Usage:"
	@echo "  make install      Install dependencies"
	@echo "  make dev          Run development server"
	@echo "  make test         Run tests"
	@echo "  make lint         Run linters"
	@echo "  make format       Format code"
	@echo "  make clean        Clean build artifacts"
	@echo "  make docker-build Build Docker images"
	@echo "  make docker-up    Start all services"
	@echo "  make docker-down  Stop all services"
	@echo "  make db-migrate   Run database migrations"

install:
	pip install -r requirements.txt

dev:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

test:
	pytest tests/ -v --cov=app --cov=modules --cov-report=term-missing

lint:
	flake8 app modules services tasks tests
	mypy app modules services tasks

format:
	black app modules services tasks tests
	isort app modules services tasks tests

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	rm -rf htmlcov .coverage

docker-build:
	docker-compose build

docker-up:
	docker-compose up -d

docker-down:
	docker-compose down

docker-logs:
	docker-compose logs -f

db-migrate:
	alembic upgrade head

db-init:
	python -c "from models.database import init_db; init_db()"

worker:
	celery -A tasks.celery_app worker --loglevel=info -Q processing,polling

beat:
	celery -A tasks.celery_app beat --loglevel=info
