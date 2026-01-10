"""
Tests for the validation module.
"""

import pytest
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

from modules.validation import (
    _fallback_parse,
    detect_language,
    get_sandbox_image,
    _compute_similarity,
    _extract_error_signature,
    _is_code_file,
)


class TestFallbackParse:
    """Tests for fallback regex-based parsing."""

    def test_extracts_python_error_type(self):
        """Should extract Python exception types."""
        title = "Application crashes"
        body = "Getting a TypeError when calling the function"

        result = _fallback_parse(title, body)

        assert result.error_type == "TypeError"

    def test_extracts_file_paths(self):
        """Should extract file paths from text."""
        title = "Bug"
        body = 'File "auth/login.py", line 42, in authenticate'

        result = _fallback_parse(title, body)

        assert "auth/login.py" in result.affected_files

    def test_extracts_code_blocks(self):
        """Should extract code blocks."""
        title = "Error"
        body = """
Here's the code:
```python
def foo():
    return bar()
```
"""
        result = _fallback_parse(title, body)

        assert len(result.code_snippets) > 0
        assert "def foo():" in result.code_snippets[0]

    def test_extracts_stack_trace(self):
        """Should extract stack traces."""
        title = "Error"
        body = """
Traceback (most recent call last):
  File "test.py", line 1, in <module>
    foo()
TypeError: error
"""
        result = _fallback_parse(title, body)

        assert result.stack_trace is not None
        assert "Traceback" in result.stack_trace


class TestDetectLanguage:
    """Tests for language detection."""

    def test_detects_python_by_requirements(self, temp_repo):
        """Should detect Python by requirements.txt."""
        assert detect_language(temp_repo) == "python"

    def test_detects_python_by_extension(self, tmp_path):
        """Should detect Python by file extensions."""
        (tmp_path / "main.py").write_text("print('hello')")

        assert detect_language(str(tmp_path)) == "python"

    def test_detects_javascript(self, tmp_path):
        """Should detect JavaScript by package.json."""
        (tmp_path / "package.json").write_text('{"name": "test"}')

        assert detect_language(str(tmp_path)) == "javascript"

    def test_detects_go(self, tmp_path):
        """Should detect Go by go.mod."""
        (tmp_path / "go.mod").write_text("module test")

        assert detect_language(str(tmp_path)) == "go"

    def test_defaults_to_python(self, tmp_path):
        """Should default to Python for unknown repos."""
        assert detect_language(str(tmp_path)) == "python"


class TestSandboxImage:
    """Tests for sandbox image selection."""

    def test_python_default(self):
        """Should return default Python image."""
        assert "python" in get_sandbox_image("python")

    def test_python_version(self):
        """Should return specific Python version."""
        assert "3.10" in get_sandbox_image("python", "3.10")

    def test_node_default(self):
        """Should return default Node image."""
        assert "node" in get_sandbox_image("node")

    def test_unknown_language(self):
        """Should return Python for unknown languages."""
        assert "python" in get_sandbox_image("unknown")


class TestComputeSimilarity:
    """Tests for text similarity computation."""

    def test_exact_match(self):
        """Should return high score for exact match."""
        score = _compute_similarity("TypeError: foo", "Error: TypeError: foo bar")

        assert score >= 0.8

    def test_partial_match(self):
        """Should return moderate score for partial match."""
        score = _compute_similarity("TypeError foo bar", "TypeError something else")

        assert 0.0 < score < 1.0

    def test_no_match(self):
        """Should return low score for no match."""
        score = _compute_similarity("TypeError", "ValueError")

        assert score < 0.5

    def test_empty_strings(self):
        """Should handle empty strings."""
        assert _compute_similarity("", "test") == 0.0
        assert _compute_similarity("test", "") == 0.0


class TestExtractErrorSignature:
    """Tests for error signature extraction."""

    def test_extracts_python_error(self):
        """Should extract Python exception signatures."""
        stderr = """
Traceback (most recent call last):
  File "test.py", line 1
TypeError: 'NoneType' object is not subscriptable
"""
        sig = _extract_error_signature(stderr)

        assert sig is not None
        assert "TypeError" in sig

    def test_extracts_generic_error(self):
        """Should extract generic error messages."""
        stderr = "Error: something went wrong"

        sig = _extract_error_signature(stderr)

        assert sig is not None
        assert "something went wrong" in sig

    def test_returns_none_for_no_error(self):
        """Should return None when no error found."""
        stderr = "All tests passed"

        sig = _extract_error_signature(stderr)

        assert sig is None


class TestIsCodeFile:
    """Tests for code file detection."""

    def test_python_files(self):
        """Should recognize Python files."""
        assert _is_code_file("main.py") is True
        assert _is_code_file("src/utils.py") is True

    def test_javascript_files(self):
        """Should recognize JavaScript files."""
        assert _is_code_file("index.js") is True
        assert _is_code_file("app.ts") is True

    def test_non_code_files(self):
        """Should not recognize non-code files."""
        assert _is_code_file("README.md") is False
        assert _is_code_file("data.json") is False
        assert _is_code_file("config.yaml") is False
