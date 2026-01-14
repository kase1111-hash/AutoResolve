"""
Authentication middleware for AutoResolve API.

Handles API key verification and request authentication.
"""

import logging
from typing import Optional

from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader

from app.config import get_settings
from utils.signature import hash_api_key

logger = logging.getLogger(__name__)

# API key header
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key_header(
    api_key: Optional[str] = Security(api_key_header),
) -> bool:
    """
    Verify API key from request header.

    Args:
        api_key: API key from X-API-Key header

    Returns:
        True if valid

    Raises:
        HTTPException: If API key is invalid or missing
    """
    settings = get_settings()

    # If no API key configured, allow all requests (development mode)
    if not settings.api.api_key:
        return True

    if not api_key:
        logger.warning("Missing API key in request")
        raise HTTPException(
            status_code=401,
            detail="Missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    if api_key != settings.api.api_key:
        logger.warning(f"Invalid API key: {api_key[:8]}...")
        raise HTTPException(
            status_code=401,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    return True


async def get_current_user(request: Request) -> Optional[str]:
    """
    Extract current user from request.

    For now, returns the API key prefix as user identifier.
    In production, this would integrate with proper auth.

    Args:
        request: FastAPI request

    Returns:
        User identifier or None
    """
    api_key = request.headers.get("X-API-Key")

    if api_key and "_" in api_key:
        # Return prefix as user ID (e.g., "ar" from "ar_xxxxx")
        return api_key.split("_")[0]

    return None


class RateLimiter:
    """Simple rate limiter using Redis."""

    def __init__(self, redis_url: str, requests_per_minute: int = 60):
        self.requests_per_minute = requests_per_minute
        self._redis = None
        self._redis_url = redis_url

    def _get_redis(self):
        if self._redis is None:
            import redis

            self._redis = redis.from_url(self._redis_url)
        return self._redis

    async def check_rate_limit(self, identifier: str) -> bool:
        """
        Check if request is within rate limit.

        Args:
            identifier: Unique identifier (IP, API key, etc.)

        Returns:
            True if within limit
        """
        try:
            r = self._get_redis()
            key = f"rate_limit:{identifier}"

            current = r.get(key)
            if current is None:
                r.setex(key, 60, 1)
                return True

            if int(current) >= self.requests_per_minute:
                return False

            r.incr(key)
            return True

        except Exception as e:
            logger.error(f"Rate limit check failed: {e}")
            return True  # Fail open


async def rate_limit_middleware(request: Request, call_next):
    """
    Rate limiting middleware.

    Limits requests based on IP address or API key.
    """
    settings = get_settings()

    # Get identifier
    api_key = request.headers.get("X-API-Key")
    if api_key:
        identifier = hash_api_key(api_key)[:16]
    else:
        identifier = request.client.host if request.client else "unknown"

    # Check rate limit
    limiter = RateLimiter(redis_url=settings.redis.url, requests_per_minute=60)

    if not await limiter.check_rate_limit(identifier):
        raise HTTPException(
            status_code=429, detail="Rate limit exceeded", headers={"Retry-After": "60"}
        )

    return await call_next(request)


def require_maintainer(repo: str):
    """
    Dependency to require maintainer access for an endpoint.

    Args:
        repo: Repository full name

    Returns:
        Dependency function
    """

    async def check_maintainer(request: Request):
        # Get user from GitHub token or API key
        user = await get_current_user(request)

        if not user:
            raise HTTPException(status_code=401, detail="Authentication required")

        # Check if user is maintainer
        from services.github_service import GitHubService

        github = GitHubService()

        try:
            is_maintainer = await github.is_maintainer(repo, user)
            if not is_maintainer:
                raise HTTPException(
                    status_code=403, detail="Maintainer access required"
                )
        finally:
            await github.close()

        return user

    return check_maintainer
