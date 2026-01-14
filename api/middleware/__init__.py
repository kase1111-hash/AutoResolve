"""
API middleware for AutoResolve.

- auth: Authentication and authorization
- logging: Request logging and audit trails
"""

from api.middleware.auth import (
    RateLimiter,
    get_current_user,
    require_maintainer,
    verify_api_key_header,
)
from api.middleware.logging import (
    AuditLogMiddleware,
    CorrelationIDMiddleware,
    RequestLoggingMiddleware,
    get_correlation_id,
    get_request_id,
    setup_middleware,
)

__all__ = [
    # auth
    "verify_api_key_header",
    "get_current_user",
    "RateLimiter",
    "require_maintainer",
    # logging
    "RequestLoggingMiddleware",
    "CorrelationIDMiddleware",
    "AuditLogMiddleware",
    "get_request_id",
    "get_correlation_id",
    "setup_middleware",
]
