"""
AutoResolve - Automated GitHub Issue Resolution System.

Main FastAPI application entry point.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from api.routes import issues, proposals, repos, webhook
from app.config import get_settings
from models.database import init_db
from models.schemas import HealthResponse

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    logger.info("Starting AutoResolve...")
    settings = get_settings()
    logger.info(f"Running version {settings.app.version}")

    # Initialize database
    try:
        init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")

    yield

    # Shutdown
    logger.info("Shutting down AutoResolve...")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title=settings.app.name,
        version=settings.app.version,
        description="Automated GitHub Issue Resolution System - From issue to merge, securely automated.",
        lifespan=lifespan,
        docs_url="/docs" if settings.app.debug else None,
        redoc_url="/redoc" if settings.app.debug else None,
    )

    # Configure CORS
    # SECURITY: When allow_credentials=True, allow_origins cannot be ["*"]
    # as this enables CSRF-like attacks. Use explicit origins in production.
    cors_origins = settings.api.cors_origins if hasattr(settings.api, 'cors_origins') and settings.api.cors_origins else []

    if cors_origins:
        # Production: explicit origins with credentials
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Hub-Signature-256", "X-GitHub-Event"],
        )
    else:
        # Development fallback: allow all origins but NO credentials
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Hub-Signature-256", "X-GitHub-Event"],
        )

    # Include routers
    app.include_router(webhook.router, tags=["Webhook"])
    app.include_router(repos.router, prefix="/api", tags=["Repositories"])
    app.include_router(issues.router, prefix="/api", tags=["Issues"])
    app.include_router(proposals.router, prefix="/api", tags=["Proposals"])

    # Global exception handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500, content={"detail": "Internal server error"}
        )

    return app


app = create_app()


@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    settings = get_settings()

    # Check database connectivity
    db_status = "connected"
    try:
        from models.database import get_engine

        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        db_status = "disconnected"

    # Check Redis connectivity
    redis_status = "connected"
    try:
        import redis

        r = redis.from_url(settings.redis.url)
        r.ping()
    except Exception:
        redis_status = "disconnected"

    # Check Celery connectivity
    celery_status = "connected"
    try:
        from tasks.celery_app import celery_app

        celery_app.control.ping(timeout=1.0)
    except Exception:
        celery_status = "disconnected"

    # Determine overall status
    if db_status == "connected" and redis_status == "connected":
        overall_status = "healthy"
    elif db_status == "disconnected":
        overall_status = "unhealthy"
    else:
        overall_status = "degraded"

    return HealthResponse(
        status=overall_status,
        version=settings.app.version,
        database=db_status,
        redis=redis_status,
        celery=celery_status,
    )


@app.get("/api/stats")
async def get_stats():
    """Get system statistics."""
    from sqlalchemy import extract, func

    from models.database import (
        Approval,
        FixProposal,
        Issue,
        SecurityReport,
        get_session_factory,
    )

    SessionLocal = get_session_factory()
    db = SessionLocal()

    try:
        # Count issues by status
        issues_by_status = dict(
            db.query(Issue.status, func.count(Issue.id)).group_by(Issue.status).all()
        )

        # Count proposals
        total_proposals = db.query(func.count(FixProposal.id)).scalar()
        proposals_approved = (
            db.query(func.count(FixProposal.id))
            .filter(FixProposal.status == "approved")
            .scalar()
        )
        proposals_rejected = (
            db.query(func.count(FixProposal.id))
            .filter(FixProposal.status == "rejected")
            .scalar()
        )

        # Count security findings that blocked proposals
        security_blocked = (
            db.query(func.count(SecurityReport.id))
            .filter(SecurityReport.recommendation == "reject")
            .scalar()
        )

        # Calculate average fix time (from issue queued to PR merged)
        average_fix_time = 0.0
        merged_approvals = (
            db.query(Issue.queued_at, Approval.resolved_at)
            .join(FixProposal, Issue.id == FixProposal.issue_id)
            .join(Approval, FixProposal.id == Approval.proposal_id)
            .filter(Approval.status == "approved")
            .filter(Approval.pr_merged.is_(True))
            .filter(Approval.resolved_at.isnot(None))
            .all()
        )

        if merged_approvals:
            total_seconds = sum(
                (approval.resolved_at - issue.queued_at).total_seconds()
                for issue, approval in merged_approvals
                if approval.resolved_at and issue.queued_at
            )
            average_fix_time = total_seconds / len(merged_approvals)

        return {
            "total_issues_processed": sum(issues_by_status.values()),
            "issues_by_status": issues_by_status,
            "total_proposals": total_proposals,
            "proposals_approved": proposals_approved,
            "proposals_rejected": proposals_rejected,
            "average_fix_time_seconds": round(average_fix_time, 2),
            "security_findings_blocked": security_blocked,
        }
    finally:
        db.close()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.api.host,
        port=settings.api.port,
        reload=settings.app.debug,
    )
