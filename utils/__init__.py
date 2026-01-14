"""
Utility modules for AutoResolve.

- diff_parser: Parse and manipulate unified diffs
- language_detector: Detect programming languages
- signature: Cryptographic signature verification
- logging: Structured logging utilities
"""

from utils.diff_parser import (
    apply_diff_to_content,
    count_changes,
    extract_diff_from_text,
    get_affected_files,
    parse_unified_diff,
    validate_diff_syntax,
)
from utils.language_detector import (
    detect_file_language,
    detect_language,
    get_file_extensions,
    get_test_command,
    is_code_file,
    normalize_language,
)
from utils.logging import (
    LogContext,
    get_logger,
    get_structured_logger,
    setup_logging,
)
from utils.signature import (
    compute_signature,
    generate_api_key,
    generate_webhook_secret,
    hash_api_key,
    verify_api_key,
    verify_github_signature,
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
