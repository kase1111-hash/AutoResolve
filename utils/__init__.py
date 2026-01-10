"""
Utility modules for AutoResolve.

- diff_parser: Parse and manipulate unified diffs
- language_detector: Detect programming languages
- signature: Cryptographic signature verification
- logging: Structured logging utilities
"""

from utils.diff_parser import (
    parse_unified_diff,
    extract_diff_from_text,
    count_changes,
    apply_diff_to_content,
    validate_diff_syntax,
    get_affected_files,
)
from utils.language_detector import (
    detect_language,
    detect_file_language,
    normalize_language,
    is_code_file,
    get_file_extensions,
    get_test_command,
)
from utils.signature import (
    verify_github_signature,
    generate_webhook_secret,
    compute_signature,
    generate_api_key,
    hash_api_key,
    verify_api_key,
)
from utils.logging import (
    setup_logging,
    get_logger,
    get_structured_logger,
    LogContext,
)

__all__ = [
    # diff_parser
    "parse_unified_diff",
    "extract_diff_from_text",
    "count_changes",
    "apply_diff_to_content",
    "validate_diff_syntax",
    "get_affected_files",
    # language_detector
    "detect_language",
    "detect_file_language",
    "normalize_language",
    "is_code_file",
    "get_file_extensions",
    "get_test_command",
    # signature
    "verify_github_signature",
    "generate_webhook_secret",
    "compute_signature",
    "generate_api_key",
    "hash_api_key",
    "verify_api_key",
    # logging
    "setup_logging",
    "get_logger",
    "get_structured_logger",
    "LogContext",
]
