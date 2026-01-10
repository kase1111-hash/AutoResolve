"""
API middleware for AutoResolve.

- auth: Authentication and authorization
- logging: Request logging and audit trails
"""

from api.middleware.auth import (
    verify_api_key_header,
    get_current_user,
    RateLimiter,
    require_maintainer,
)
from api.middleware.logging import (
    RequestLoggingMiddleware,
    CorrelationIDMiddleware,
    AuditLogMiddleware,
    get_request_id,
    get_correlation_id,
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
