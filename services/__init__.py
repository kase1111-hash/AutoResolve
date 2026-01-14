"""
Services for AutoResolve.

- github_service: GitHub API interactions
- llm_service: LLM API interactions
- docker_service: Docker sandbox execution
- notification_service: Slack and email notifications
"""

from services.docker_service import DockerService
from services.github_service import GitHubService
from services.llm_service import LLMService

__all__ = ["GitHubService", "LLMService", "DockerService"]
