"""
GitHub Service for AutoResolve.

Handles all GitHub API interactions.
"""

import base64
import logging
from datetime import datetime
from typing import Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class GitHubService:
    """Service for interacting with GitHub API."""

    def __init__(self):
        """Initialize the GitHub service."""
        self.settings = get_settings()
        self.base_url = self.settings.github.api_base_url
        self._token: Optional[str] = None
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            headers = {
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "AutoResolve/1.0"
            }

            # Add authentication if available
            token = await self._get_token()
            if token:
                headers["Authorization"] = f"token {token}"

            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=30.0
            )

        return self._client

    async def _get_token(self) -> Optional[str]:
        """Get GitHub access token."""
        if self._token:
            return self._token

        # TODO: Implement GitHub App authentication
        # For now, use environment variable
        import os
        self._token = os.environ.get("GITHUB_TOKEN")
        return self._token

    async def get_issues(
        self,
        repo: str,
        state: str = "open",
        since: Optional[datetime] = None,
        sort: str = "updated",
        direction: str = "desc"
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
        client = await self._get_client()

        params = {
            "state": state,
            "sort": sort,
            "direction": direction,
            "per_page": 100
        }

        if since:
            params["since"] = since.isoformat()

        response = await client.get(f"/repos/{repo}/issues", params=params)
        response.raise_for_status()

        return response.json()

    async def get_issue(self, repo: str, issue_number: int) -> dict:
        """Get a specific issue."""
        client = await self._get_client()
        response = await client.get(f"/repos/{repo}/issues/{issue_number}")
        response.raise_for_status()
        return response.json()

    async def get_issue_comments(
        self,
        repo: str,
        issue_number: int,
        since: Optional[datetime] = None
    ) -> list[dict]:
        """Get comments on an issue."""
        client = await self._get_client()

        params = {"per_page": 100}
        if since:
            params["since"] = since.isoformat()

        response = await client.get(
            f"/repos/{repo}/issues/{issue_number}/comments",
            params=params
        )
        response.raise_for_status()

        return response.json()

    async def create_issue_comment(
        self,
        repo: str,
        issue_number: int,
        body: str
    ) -> int:
        """
        Create a comment on an issue.

        Returns:
            Comment ID
        """
        client = await self._get_client()

        response = await client.post(
            f"/repos/{repo}/issues/{issue_number}/comments",
            json={"body": body}
        )
        response.raise_for_status()

        return response.json().get("id", 0)

    async def get_issue_reactions(
        self,
        repo: str,
        issue_number: int
    ) -> list[dict]:
        """Get reactions on an issue."""
        client = await self._get_client()

        headers = {"Accept": "application/vnd.github.squirrel-girl-preview+json"}
        response = await client.get(
            f"/repos/{repo}/issues/{issue_number}/reactions",
            headers=headers
        )
        response.raise_for_status()

        return response.json()

    async def is_maintainer(self, repo: str, username: str) -> bool:
        """Check if a user is a maintainer of the repository."""
        client = await self._get_client()

        try:
            response = await client.get(
                f"/repos/{repo}/collaborators/{username}/permission"
            )
            if response.status_code == 200:
                permission = response.json().get("permission", "")
                return permission in ("admin", "maintain", "write")
            return False
        except Exception:
            return False

    async def get_default_branch(self, repo: str) -> str:
        """Get the default branch of a repository."""
        client = await self._get_client()

        response = await client.get(f"/repos/{repo}")
        response.raise_for_status()

        return response.json().get("default_branch", "main")

    async def create_branch(
        self,
        repo: str,
        branch: str,
        from_ref: str
    ) -> None:
        """Create a new branch from a reference."""
        client = await self._get_client()

        # Get the SHA of the source ref
        response = await client.get(f"/repos/{repo}/git/refs/heads/{from_ref}")
        response.raise_for_status()
        sha = response.json().get("object", {}).get("sha")

        # Create the new branch
        response = await client.post(
            f"/repos/{repo}/git/refs",
            json={
                "ref": f"refs/heads/{branch}",
                "sha": sha
            }
        )
        response.raise_for_status()

    async def get_file_contents(
        self,
        repo: str,
        path: str,
        ref: str
    ) -> str:
        """Get the contents of a file."""
        client = await self._get_client()

        response = await client.get(
            f"/repos/{repo}/contents/{path}",
            params={"ref": ref}
        )
        response.raise_for_status()

        content = response.json().get("content", "")
        return base64.b64decode(content).decode("utf-8")

    async def update_file(
        self,
        repo: str,
        path: str,
        content: str,
        branch: str,
        message: str
    ) -> None:
        """Update or create a file in a repository."""
        client = await self._get_client()

        # Get current file SHA if it exists
        sha = None
        try:
            response = await client.get(
                f"/repos/{repo}/contents/{path}",
                params={"ref": branch}
            )
            if response.status_code == 200:
                sha = response.json().get("sha")
        except Exception:
            pass

        # Update or create file
        data = {
            "message": message,
            "content": base64.b64encode(content.encode()).decode(),
            "branch": branch
        }
        if sha:
            data["sha"] = sha

        response = await client.put(f"/repos/{repo}/contents/{path}", json=data)
        response.raise_for_status()

    async def create_pull_request(
        self,
        repo: str,
        title: str,
        body: str,
        head: str,
        base: str,
        labels: Optional[list[str]] = None
    ) -> dict:
        """Create a pull request."""
        client = await self._get_client()

        data = {
            "title": title,
            "body": body,
            "head": head,
            "base": base
        }

        response = await client.post(f"/repos/{repo}/pulls", json=data)
        response.raise_for_status()

        pr = response.json()

        # Add labels if specified
        if labels:
            await client.post(
                f"/repos/{repo}/issues/{pr['number']}/labels",
                json={"labels": labels}
            )

        return pr

    async def create_pr_comment(
        self,
        repo: str,
        pr_number: int,
        body: str
    ) -> None:
        """Create a comment on a pull request."""
        await self.create_issue_comment(repo, pr_number, body)

    async def get_pr_check_status(self, repo: str, pr_number: int) -> str:
        """Get the combined check status for a PR."""
        client = await self._get_client()

        # Get the PR to find the head SHA
        response = await client.get(f"/repos/{repo}/pulls/{pr_number}")
        response.raise_for_status()
        sha = response.json().get("head", {}).get("sha")

        # Get combined status
        response = await client.get(f"/repos/{repo}/commits/{sha}/status")
        response.raise_for_status()

        return response.json().get("state", "pending")

    async def merge_pull_request(
        self,
        repo: str,
        pr_number: int,
        merge_method: str = "squash"
    ) -> None:
        """Merge a pull request."""
        client = await self._get_client()

        response = await client.put(
            f"/repos/{repo}/pulls/{pr_number}/merge",
            json={"merge_method": merge_method}
        )
        response.raise_for_status()

    async def close_issue(self, repo: str, issue_number: int) -> None:
        """Close an issue."""
        client = await self._get_client()

        response = await client.patch(
            f"/repos/{repo}/issues/{issue_number}",
            json={"state": "closed"}
        )
        response.raise_for_status()

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
