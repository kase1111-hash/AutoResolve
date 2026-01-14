"""
Docker Service for AutoResolve.

Handles sandbox container execution for issue reproduction.
"""

import logging
import time

from app.config import get_settings

logger = logging.getLogger(__name__)


class DockerService:
    """Service for running code in Docker sandboxes."""

    def __init__(self):
        """Initialize the Docker service."""
        self.settings = get_settings()
        self._client = None

    def _get_client(self):
        """Get or create Docker client."""
        if self._client is None:
            try:
                import docker

                self._client = docker.from_env()
            except ImportError:
                logger.error("Docker package not installed")
                raise
            except Exception as e:
                logger.error(f"Failed to connect to Docker: {e}")
                raise

        return self._client

    def run_in_sandbox(
        self,
        image: str,
        repo_dir: str,
        commands: list[str],
        timeout: int = 300,
        memory_limit: str = "512m",
        network_mode: str = "none",
    ) -> dict:
        """
        Run commands in a sandboxed Docker container.

        Args:
            image: Docker image to use
            repo_dir: Path to repository directory
            commands: List of commands to execute
            timeout: Maximum execution time in seconds
            memory_limit: Memory limit (e.g., "512m")
            network_mode: Network mode (e.g., "none", "bridge")

        Returns:
            dict with stdout, stderr, exit_code, and duration
        """
        client = self._get_client()

        # Prepare the command
        combined_command = " && ".join(commands)
        full_command = f'/bin/sh -c "{combined_command}"'

        start_time = time.time()

        try:
            # Create and run container
            container = client.containers.run(
                image=image,
                command=full_command,
                volumes={repo_dir: {"bind": "/code", "mode": "rw"}},
                working_dir="/code",
                network_mode=network_mode,
                mem_limit=memory_limit,
                cpu_quota=50000,  # 50% of one CPU
                detach=True,
                remove=False,
            )

            # Wait for completion with timeout
            try:
                result = container.wait(timeout=timeout)
                exit_code = result.get("StatusCode", 1)
            except Exception:
                # Timeout - kill container
                logger.warning(f"Container {container.short_id} timed out")
                container.kill()
                exit_code = -1

            # Get logs
            stdout = container.logs(stdout=True, stderr=False).decode(
                "utf-8", errors="replace"
            )
            stderr = container.logs(stdout=False, stderr=True).decode(
                "utf-8", errors="replace"
            )

            duration = time.time() - start_time

            # Cleanup
            try:
                container.remove(force=True)
            except Exception:
                pass

            return {
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": exit_code,
                "duration": duration,
            }

        except Exception as e:
            logger.error(f"Docker execution failed: {e}")
            return {
                "stdout": "",
                "stderr": str(e),
                "exit_code": -1,
                "duration": time.time() - start_time,
            }

    def pull_image(self, image: str) -> bool:
        """
        Pull a Docker image if not present.

        Args:
            image: Image name and tag

        Returns:
            True if successful
        """
        client = self._get_client()

        try:
            client.images.get(image)
            return True
        except Exception:
            pass

        try:
            logger.info(f"Pulling Docker image: {image}")
            client.images.pull(image)
            return True
        except Exception as e:
            logger.error(f"Failed to pull image {image}: {e}")
            return False

    def cleanup_containers(self, label: str = "autoresolve") -> int:
        """
        Clean up orphaned containers.

        Args:
            label: Label to filter containers

        Returns:
            Number of containers removed
        """
        client = self._get_client()
        removed = 0

        try:
            containers = client.containers.list(all=True, filters={"label": label})

            for container in containers:
                try:
                    container.remove(force=True)
                    removed += 1
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"Container cleanup failed: {e}")

        return removed

    def get_available_images(self) -> list[str]:
        """Get list of available sandbox images."""
        client = self._get_client()

        try:
            images = client.images.list()
            return [tag for image in images for tag in image.tags if tag]
        except Exception:
            return []
