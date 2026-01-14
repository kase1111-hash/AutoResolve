"""
Signature verification utility for AutoResolve.

Handles cryptographic signature verification for webhooks and API requests.
"""

import hashlib
import hmac
import secrets
import time
from typing import Optional


def verify_github_signature(payload: bytes, signature_header: str, secret: str) -> bool:
    """
    Verify a GitHub webhook signature.

    Args:
        payload: Raw request body
        signature_header: X-Hub-Signature-256 header value
        secret: Webhook secret

    Returns:
        True if signature is valid
    """
    if not signature_header:
        return False

    try:
        # GitHub sends signature as "sha256=<hash>"
        if "=" not in signature_header:
            return False

        hash_algorithm, signature = signature_header.split("=", 1)
        if hash_algorithm != "sha256":
            return False

        expected_signature = hmac.new(
            secret.encode(), payload, hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(expected_signature, signature)

    except Exception:
        return False


def generate_webhook_secret(length: int = 32) -> str:
    """
    Generate a secure webhook secret.

    Args:
        length: Length of the secret in bytes

    Returns:
        Hex-encoded secret
    """
    return secrets.token_hex(length)


def compute_signature(payload: bytes, secret: str, algorithm: str = "sha256") -> str:
    """
    Compute HMAC signature for a payload.

    Args:
        payload: Data to sign
        secret: Secret key
        algorithm: Hash algorithm (sha256, sha1)

    Returns:
        Signature in format "algorithm=hexdigest"
    """
    if algorithm == "sha256":
        digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    elif algorithm == "sha1":
        digest = hmac.new(secret.encode(), payload, hashlib.sha1).hexdigest()
    else:
        raise ValueError(f"Unsupported algorithm: {algorithm}")

    return f"{algorithm}={digest}"


def generate_api_key(prefix: str = "ar") -> str:
    """
    Generate a secure API key.

    Args:
        prefix: Key prefix for identification

    Returns:
        API key in format "prefix_randomhex"
    """
    random_part = secrets.token_hex(24)
    return f"{prefix}_{random_part}"


def hash_api_key(api_key: str) -> str:
    """
    Hash an API key for secure storage.

    Args:
        api_key: The API key to hash

    Returns:
        SHA256 hash of the key
    """
    return hashlib.sha256(api_key.encode()).hexdigest()


def verify_api_key(provided_key: str, stored_hash: str) -> bool:
    """
    Verify an API key against its stored hash.

    Args:
        provided_key: The key provided in the request
        stored_hash: The stored hash to compare against

    Returns:
        True if the key is valid
    """
    provided_hash = hash_api_key(provided_key)
    return hmac.compare_digest(provided_hash, stored_hash)


def generate_nonce(length: int = 16) -> str:
    """
    Generate a random nonce for request deduplication.

    Args:
        length: Length of the nonce in bytes

    Returns:
        Hex-encoded nonce
    """
    return secrets.token_hex(length)


def generate_idempotency_key() -> str:
    """
    Generate an idempotency key for API requests.

    Returns:
        Unique idempotency key
    """
    timestamp = int(time.time() * 1000)
    random_part = secrets.token_hex(8)
    return f"{timestamp}-{random_part}"


def verify_timestamp(timestamp: int, max_age_seconds: int = 300) -> bool:
    """
    Verify that a timestamp is recent enough.

    Args:
        timestamp: Unix timestamp to verify
        max_age_seconds: Maximum age in seconds

    Returns:
        True if timestamp is within acceptable range
    """
    current_time = int(time.time())
    age = abs(current_time - timestamp)
    return age <= max_age_seconds


def extract_error_signature(stderr: str) -> Optional[str]:
    """
    Extract a unique error signature from stderr output.

    Args:
        stderr: Standard error output

    Returns:
        Error signature or None
    """
    import re

    # Python exception patterns
    patterns = [
        r"((?:TypeError|ValueError|KeyError|AttributeError|RuntimeError|Exception|ImportError|ModuleNotFoundError):\s*.+?)(?:\n|$)",
        r"((?:AssertionError|IndexError|ZeroDivisionError|FileNotFoundError|PermissionError):\s*.+?)(?:\n|$)",
    ]

    for pattern in patterns:
        match = re.search(pattern, stderr)
        if match:
            return match.group(1).strip()

    # Generic error pattern
    error_match = re.search(
        r"(?:error|exception|failed):\s*(.+?)(?:\n|$)", stderr, re.IGNORECASE
    )
    if error_match:
        return error_match.group(1).strip()[:200]

    return None
