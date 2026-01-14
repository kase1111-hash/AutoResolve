"""
LLM Service for AutoResolve.

Handles interactions with language model APIs.
"""

import logging
import os
from typing import Optional

from app.config import get_settings

logger = logging.getLogger(__name__)


class LLMService:
    """Service for interacting with LLM APIs."""

    def __init__(self):
        """Initialize the LLM service."""
        self.settings = get_settings()
        self._client = None

    def _get_openai_client(self):
        """Get or create OpenAI client."""
        if self._client is None:
            try:
                from openai import AsyncOpenAI

                self._client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
            except ImportError:
                logger.error("OpenAI package not installed")
                raise

        return self._client

    async def complete(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        system_prompt: Optional[str] = None,
    ) -> str:
        """
        Generate a completion from the LLM.

        Args:
            prompt: The prompt to complete
            model: Model to use (defaults to config)
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            system_prompt: Optional system message

        Returns:
            Generated text
        """
        model = model or self.settings.fix_generation.llm_model
        provider = self.settings.fix_generation.llm_provider

        if provider == "openai":
            return await self._complete_openai(
                prompt=prompt,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                system_prompt=system_prompt,
            )
        else:
            raise ValueError(f"Unsupported LLM provider: {provider}")

    async def _complete_openai(
        self,
        prompt: str,
        model: str,
        temperature: float,
        max_tokens: int,
        system_prompt: Optional[str],
    ) -> str:
        """Generate completion using OpenAI API."""
        client = self._get_openai_client()

        messages = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        messages.append({"role": "user", "content": prompt})

        try:
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )

            return response.choices[0].message.content or ""

        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            raise

    async def count_tokens(self, text: str, model: Optional[str] = None) -> int:
        """
        Count the number of tokens in a text.

        Args:
            text: Text to count tokens for
            model: Model to use for tokenization

        Returns:
            Token count
        """
        model = model or self.settings.fix_generation.llm_model

        try:
            import tiktoken

            encoding = tiktoken.encoding_for_model(model)
            return len(encoding.encode(text))
        except Exception:
            # Fallback: approximate tokens as words * 1.3
            return int(len(text.split()) * 1.3)

    async def close(self) -> None:
        """Close any open connections."""
        self._client = None
