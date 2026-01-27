"""
GitHub Service for AutoResolve.

Handles all GitHub API interactions with retry logic and proper resource cleanup.
"""

import asyncio
import base64
import logging
import os
from datetime import datetime
from typing import Optional, TypeVar

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

# Type variable for generic retry function
T = TypeVar("T")

# Retry configuration
MAX_RETRIES = 3
INITIAL_BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 16.0
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


async def retry_with_backoff(
    coro_func,
    max_retries: int = MAX_RETRIES,
    initial_backoff: float = INITIAL_BACKOFF_SECONDS,
    max_backoff: float = MAX_BACKOFF_SECONDS,
):
    """
    Retry an async function with exponential backoff.

    Args:
        coro_func: Async function to call (must be a callable that returns a coroutine)
        max_retries: Maximum number of retry attempts
        initial_backoff: Initial backoff time in seconds
        max_backoff: Maximum backoff time in seconds

    Returns:
        Result of the coroutine

    Raises:
        Last exception if all retries fail
    """
    last_exception = None
    backoff = initial_backoff

    for attempt in range(max_retries + 1):
        try:
            return await coro_func()
        except httpx.HTTPStatusError as e:
            if e.response.status_code not in RETRYABLE_STATUS_CODES:
                raise
            last_exception = e
            if attempt < max_retries:
                # Check for Retry-After header
                retry_after = e.response.headers.get("Retry-After")
                if retry_after:
                    try:
                        wait_time = min(float(retry_after), max_backoff)
                    except ValueError:
                        wait_time = backoff
                else:
                    wait_time = backoff

                logger.warning(
                    f"Request failed with {e.response.status_code}, "
                    f"retrying in {wait_time:.1f}s (attempt {attempt + 1}/{max_retries})"
                )
                await asyncio.sleep(wait_time)
                backoff = min(backoff * 2, max_backoff)
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            last_exception = e
            if attempt < max_retries:
                logger.warning(
                    f"Connection error: {e}, retrying in {backoff:.1f}s "
                    f"(attempt {attempt + 1}/{max_retries})"
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

    raise last_exception


class GitHubService:
    """
    Service for interacting with GitHub API.

    Supports async context manager for proper resource cleanup:
        async with GitHubService() as github:
            issues = await github.get_issues(repo)
    """

    def __init__(self):
        """Initialize the GitHub service."""
        self.settings = get_settings()
        self.base_url = self.settings.github.api_base_url
        self._token: Optional[str] = None
        self._client: Optional[httpx.AsyncClient] = None
        self._client_lock = asyncio.Lock()

    async def __aenter__(self) -> "GitHubService":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit - ensures cleanup."""
        await self.close()

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client (thread-safe)."""
        if self._client is None:
            async with self._client_lock:
                # Double-check pattern to avoid race conditions
                if self._client is None:
                    headers = {
                        "Accept": "application/vnd.github.v3+json",
                        "User-Agent": "AutoResolve/1.0",
                    }

                    # Add authentication if available
                    token = await self._get_token()
                    if token:
                        headers["Authorization"] = f"token {token}"

                    self._client = httpx.AsyncClient(
                        base_url=self.base_url,
                        headers=headers,
                        timeout=self.settings.github.api_timeout_seconds,
                    )

        return self._client

    async def _get_token(self) -> Optional[str]:
        """Get GitHub access token."""
        if self._token:
            return self._token

        # TODO: Implement GitHub App authentication
        # For now, use environment variable
        self._token = os.environ.get("GITHUB_TOKEN")
        return self._token

    async def _request(
        self,
        method: str,
        url: str,
        **kwargs,
    ) -> httpx.Response:
        """
        Make an HTTP request with retry logic.

        Args:
            method: HTTP method (get, post, put, patch, delete)
            url: URL path
            **kwargs: Additional arguments for httpx

        Returns:
            HTTP response

        Raises:
            httpx.HTTPStatusError: If request fails after retries
        """
        client = await self._get_client()

        async def make_request():
            response = await getattr(client, method)(url, **kwargs)
            response.raise_for_status()
            return response

        return await retry_with_backoff(make_request)

    async def get_issues(
        self,
        repo: str,
        state: str = "open",
        since: Optional[datetime] = None,
        sort: str = "updated",
        direction: str = "desc",
    ) -> list[dict]:
        """
        Get issues from a repository.

        Args:
            repo: Repository full name (org/repo)
            state: Issue state (open, closed, all)
            since: Only return issues updated after this time
            sort: Sort field (created, updated, comments)
            direction: Sort direction (asc, desc)

        Returns:
            List of issue data
        """
        params = {"state": state, "sort": sort, "direction": direction, "per_page": 100}

        if since:
            params["since"] = since.isoformat()

        response = await self._request("get", f"/repos/{repo}/issues", params=params)
        return response.json()

    async def get_issue(self, repo: str, issue_number: int) -> dict:
        """Get a specific issue."""
        response = await self._request("get", f"/repos/{repo}/issues/{issue_number}")
        return response.json()

    async def get_issue_comments(
        self, repo: str, issue_number: int, since: Optional[datetime] = None
    ) -> list[dict]:
        """Get comments on an issue."""
        params = {"per_page": 100}
        if since:
            params["since"] = since.isoformat()

        response = await self._request(
            "get", f"/repos/{repo}/issues/{issue_number}/comments", params=params
        )
        return response.json()

    async def create_issue_comment(
        self, repo: str, issue_number: int, body: str
    ) -> int:
        """
        Create a comment on an issue.

        Returns:
            Comment ID
        """
        response = await self._request(
            "post", f"/repos/{repo}/issues/{issue_number}/comments", json={"body": body}
        )
        return response.json().get("id", 0)

    async def get_issue_reactions(self, repo: str, issue_number: int) -> list[dict]:
        """Get reactions on an issue."""
        headers = {"Accept": "application/vnd.github.squirrel-girl-preview+json"}
        response = await self._request(
            "get", f"/repos/{repo}/issues/{issue_number}/reactions", headers=headers
        )
        return response.json()

    async def is_maintainer(self, repo: str, username: str) -> bool:
        """Check if a user is a maintainer of the repository."""
        try:
            response = await self._request(
                "get", f"/repos/{repo}/collaborators/{username}/permission"
            )
            permission = response.json().get("permission", "")
            return permission in ("admin", "maintain", "write")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return False
            raise
        except Exception:
            return False

    async def get_default_branch(self, repo: str) -> str:
        """Get the default branch of a repository."""
        response = await self._request("get", f"/repos/{repo}")
        return response.json().get("default_branch", "main")

    async def create_branch(self, repo: str, branch: str, from_ref: str) -> None:
        """Create a new branch from a reference."""
        # Get the SHA of the source ref
        response = await self._request("get", f"/repos/{repo}/git/refs/heads/{from_ref}")
        sha = response.json().get("object", {}).get("sha")

        # Create the new branch
        await self._request(
            "post", f"/repos/{repo}/git/refs",
            json={"ref": f"refs/heads/{branch}", "sha": sha}
        )

    async def get_file_contents(self, repo: str, path: str, ref: str) -> str:
        """Get the contents of a file."""
        response = await self._request(
            "get", f"/repos/{repo}/contents/{path}", params={"ref": ref}
        )
        content = response.json().get("content", "")
        return base64.b64decode(content).decode("utf-8")

    async def update_file(
        self, repo: str, path: str, content: str, branch: str, message: str
    ) -> None:
        """Update or create a file in a repository."""
        # Get current file SHA if it exists
        sha = None
        try:
            client = await self._get_client()
            response = await client.get(
                f"/repos/{repo}/contents/{path}", params={"ref": branch}
            )
            if response.status_code == 200:
                sha = response.json().get("sha")
        except Exception:
            pass

        # Update or create file
        data = {
            "message": message,
            "content": base64.b64encode(content.encode()).decode(),
            "branch": branch,
        }
        if sha:
            data["sha"] = sha

        await self._request("put", f"/repos/{repo}/contents/{path}", json=data)

    async def create_pull_request(
        self,
        repo: str,
        title: str,
        body: str,
        head: str,
        base: str,
        labels: Optional[list[str]] = None,
    ) -> dict:
        """Create a pull request."""
        data = {"title": title, "body": body, "head": head, "base": base}

        response = await self._request("post", f"/repos/{repo}/pulls", json=data)
        pr = response.json()

        # Add labels if specified
        if labels:
            await self._request(
                "post", f"/repos/{repo}/issues/{pr['number']}/labels",
                json={"labels": labels}
            )

        return pr

    async def create_pr_comment(self, repo: str, pr_number: int, body: str) -> None:
        """Create a comment on a pull request."""
        await self.create_issue_comment(repo, pr_number, body)

    async def get_pr_check_status(self, repo: str, pr_number: int) -> str:
        """Get the combined check status for a PR."""
        # Get the PR to find the head SHA
        response = await self._request("get", f"/repos/{repo}/pulls/{pr_number}")
        sha = response.json().get("head", {}).get("sha")

        # Get combined status
        response = await self._request("get", f"/repos/{repo}/commits/{sha}/status")
        return response.json().get("state", "pending")

    async def merge_pull_request(
        self, repo: str, pr_number: int, merge_method: str = "squash"
    ) -> None:
        """Merge a pull request."""
        await self._request(
            "put", f"/repos/{repo}/pulls/{pr_number}/merge",
            json={"merge_method": merge_method}
        )

    async def close_issue(self, repo: str, issue_number: int) -> None:
        """Close an issue."""
        await self._request(
            "patch", f"/repos/{repo}/issues/{issue_number}", json={"state": "closed"}
        )

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
