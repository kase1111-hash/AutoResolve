"""
Tests for the fix generation module.
"""

from modules.fix_generator import (
    extract_diff,
    validate_diff_syntax,
    count_diff_lines,
)
from models.schemas import ParsedDiff


class TestExtractDiff:
    """Tests for diff extraction from LLM responses."""

    def test_extracts_from_markdown_block(self):
        """Should extract diff from markdown code block."""
        response = """
Here's the fix:

```diff
--- a/test.py
+++ b/test.py
@@ -1,3 +1,3 @@
 def foo():
-    return None
+    return "fixed"
```

This should fix the issue.
"""
        diff = extract_diff(response)

        assert diff is not None
        assert "--- a/test.py" in diff
        assert "+    return \"fixed\"" in diff

    def test_extracts_from_plain_block(self):
        """Should extract diff from plain code block."""
        response = """
```
--- a/test.py
+++ b/test.py
@@ -1,3 +1,3 @@
-old
+new
```
"""
        diff = extract_diff(response)

        assert diff is not None
        assert "--- a/test.py" in diff

    def test_extracts_raw_diff(self):
        """Should extract raw diff without code blocks."""
        response = """--- a/test.py
+++ b/test.py
@@ -1 +1 @@
-old
+new
"""
        diff = extract_diff(response)

        assert diff is not None
        assert "-old" in diff
        assert "+new" in diff

    def test_returns_none_for_no_diff(self):
        """Should return None when no diff found."""
        response = "I couldn't generate a fix for this issue."

        diff = extract_diff(response)

        assert diff is None


class TestValidateDiffSyntax:
    """Tests for diff syntax validation."""

    def test_valid_diff(self, sample_diff):
        """Should validate correct diff syntax."""
        is_valid, error = validate_diff_syntax(sample_diff)

        assert is_valid is True
        assert error is None

    def test_invalid_diff(self):
        """Should reject invalid diff syntax."""
        invalid_diff = "This is not a diff"

        is_valid, error = validate_diff_syntax(invalid_diff)

        assert is_valid is False
        assert error is not None


class TestCountDiffLines:
    """Tests for counting diff changes."""

    def test_counts_additions_and_removals(self):
        """Should count added and removed lines."""
        from utils.diff_parser import parse_unified_diff

        diff = """--- a/test.py
+++ b/test.py
@@ -1,4 +1,5 @@
 context
-removed1
-removed2
+added1
+added2
+added3
 context
"""
        parsed = parse_unified_diff(diff)
        added, removed = count_diff_lines(parsed)

        assert added == 3
        assert removed == 2

    def test_empty_diff(self):
        """Should handle empty diff."""
        parsed = ParsedDiff(files=[])
        added, removed = count_diff_lines(parsed)

        assert added == 0
        assert removed == 0
