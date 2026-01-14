"""
Logging middleware for AutoResolve API.

Provides request/response logging and correlation IDs.
"""

import logging
import time
import uuid
from typing import Callable, Optional

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware to log all HTTP requests and responses."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request with logging of start, completion, and errors."""
        # Generate request ID
        request_id = str(uuid.uuid4())[:8]
        request.state.request_id = request_id

        # Start timer
        start_time = time.time()

        # Log request
        logger.info(
            f"Request started",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "query": str(request.query_params),
                "client_ip": request.client.host if request.client else None,
                "user_agent": request.headers.get("user-agent"),
            },
        )

        # Process request
        try:
            response = await call_next(request)

            # Calculate duration
            duration_ms = (time.time() - start_time) * 1000

            # Log response
            logger.info(
                f"Request completed",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": round(duration_ms, 2),
                },
            )

            # Add request ID to response headers
            response.headers["X-Request-ID"] = request_id

            return response

        except Exception as e:
            # Calculate duration
            duration_ms = (time.time() - start_time) * 1000

            # Log error
            logger.error(
                f"Request failed",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "error": str(e),
                    "duration_ms": round(duration_ms, 2),
                },
                exc_info=True,
            )

            raise


class CorrelationIDMiddleware(BaseHTTPMiddleware):
    """Middleware to propagate correlation IDs for distributed tracing."""

    CORRELATION_ID_HEADER = "X-Correlation-ID"

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request with correlation ID propagation."""
        # Get or generate correlation ID
        correlation_id = request.headers.get(
            self.CORRELATION_ID_HEADER, str(uuid.uuid4())
        )

        # Store in request state
        request.state.correlation_id = correlation_id

        # Process request
        response = await call_next(request)

        # Add to response headers
        response.headers[self.CORRELATION_ID_HEADER] = correlation_id

        return response


def get_request_id(request: Request) -> str:
    """Get the request ID from request state."""
    return getattr(request.state, "request_id", "unknown")


def get_correlation_id(request: Request) -> str:
    """Get the correlation ID from request state."""
    return getattr(request.state, "correlation_id", "unknown")


class AuditLogMiddleware(BaseHTTPMiddleware):
    """Middleware to create audit log entries for sensitive operations."""

    AUDITED_PATHS = {
        "/api/repos": ["POST", "DELETE"],
        "/api/proposals": ["POST"],
        "/webhook/github": ["POST"],
    }

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and create audit log entries for sensitive operations."""
        # Check if this path should be audited
        should_audit = False
        for path_prefix, methods in self.AUDITED_PATHS.items():
            if request.url.path.startswith(path_prefix) and request.method in methods:
                should_audit = True
                break

        if not should_audit:
            return await call_next(request)

        # Get request body for audit (careful with large payloads)
        body = None
        if request.method in ("POST", "PUT", "PATCH"):
            try:
                body = await request.body()
                # Reset body for downstream handlers
                request._body = body
            except Exception:
                pass

        # Process request
        response = await call_next(request)

        # Create audit log entry
        if response.status_code < 400:
            await self._create_audit_entry(
                request=request, response=response, body=body
            )

        return response

    async def _create_audit_entry(
        self, request: Request, response: Response, body: Optional[bytes] = None
    ):
        """Create an audit log entry in the database."""
        try:
            from models.database import AuditLog, get_session_factory

            SessionLocal = get_session_factory()
            db = SessionLocal()

            try:
                # Determine actor
                actor = None
                if hasattr(request.state, "user"):
                    actor = request.state.user
                elif request.headers.get("X-API-Key"):
                    actor = f"api_key:{request.headers.get('X-API-Key')[:8]}"

                # Create entry
                entry = AuditLog(
                    event_type=f"api.{request.method.lower()}.{request.url.path.replace('/', '.')}",
                    actor=actor,
                    details={
                        "method": request.method,
                        "path": request.url.path,
                        "status_code": response.status_code,
                        "client_ip": request.client.host if request.client else None,
                        "request_id": get_request_id(request),
                    },
                )

                db.add(entry)
                db.commit()

            finally:
                db.close()

        except Exception as e:
            logger.error(f"Failed to create audit log entry: {e}")


def setup_middleware(app):
    """
    Set up all logging middleware for the application.

    Args:
        app: FastAPI application instance
    """
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(CorrelationIDMiddleware)
    app.add_middleware(AuditLogMiddleware)
