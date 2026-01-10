"""
Diff parser utility for AutoResolve.

Provides functions for parsing and manipulating unified diffs.
"""

import re
from typing import Optional

from models.schemas import DiffHunk, DiffLine, FileDiff, ParsedDiff


def parse_unified_diff(diff_text: str) -> ParsedDiff:
    """
    Parse a unified diff into structured format.

    Args:
        diff_text: Raw unified diff text

    Returns:
        Parsed diff structure
    """
    try:
        from unidiff import PatchSet
        patch = PatchSet(diff_text)

        files = []
        for patched_file in patch:
            hunks = []
            for hunk in patched_file:
                lines = []
                for line in hunk:
                    if line.is_context:
                        line_type = "context"
                    elif line.is_added:
                        line_type = "add"
                    elif line.is_removed:
                        line_type = "remove"
                    else:
                        continue

                    lines.append(DiffLine(
                        type=line_type,
                        content=line.value.rstrip('\n'),
                        old_lineno=line.source_line_no,
                        new_lineno=line.target_line_no
                    ))

                hunks.append(DiffHunk(
                    old_start=hunk.source_start,
                    old_count=hunk.source_length,
                    new_start=hunk.target_start,
                    new_count=hunk.target_length,
                    lines=lines
                ))

            files.append(FileDiff(
                path=patched_file.path,
                old_path=patched_file.source_file if patched_file.source_file != patched_file.path else None,
                hunks=hunks,
                is_new=patched_file.is_added_file,
                is_deleted=patched_file.is_removed_file
            ))

        return ParsedDiff(files=files)

    except Exception as e:
        raise ValueError(f"Invalid diff format: {e}")


def extract_diff_from_text(text: str) -> Optional[str]:
    """
    Extract a unified diff from text that may contain other content.

    Args:
        text: Text that may contain a diff

    Returns:
        Extracted diff or None
    """
    # Try markdown code block
    diff_match = re.search(r'```diff\n(.*?)```', text, re.DOTALL)
    if diff_match:
        return diff_match.group(1).strip()

    # Try plain code block starting with diff markers
    diff_match = re.search(r'```\n(---.*?)```', text, re.DOTALL)
    if diff_match:
        return diff_match.group(1).strip()

    # Check if text itself is a diff
    if text.strip().startswith("---") or text.strip().startswith("diff --git"):
        return text.strip()

    # Look for diff markers anywhere
    lines = text.split('\n')
    diff_lines = []
    in_diff = False

    for line in lines:
        if line.startswith('---') or line.startswith('diff --git'):
            in_diff = True
        if in_diff:
            if line.startswith('```') and diff_lines:
                break
            diff_lines.append(line)

    if diff_lines:
        return '\n'.join(diff_lines).strip()

    return None


def count_changes(parsed_diff: ParsedDiff) -> tuple[int, int]:
    """
    Count added and removed lines in a diff.

    Args:
        parsed_diff: Parsed diff structure

    Returns:
        Tuple of (lines_added, lines_removed)
    """
    added = 0
    removed = 0

    for file_diff in parsed_diff.files:
        for hunk in file_diff.hunks:
            for line in hunk.lines:
                if line.type == "add":
                    added += 1
                elif line.type == "remove":
                    removed += 1

    return added, removed


def apply_diff_to_content(content: str, diff: str, file_path: str) -> str:
    """
    Apply a unified diff to file content.

    Args:
        content: Original file content
        diff: Unified diff text
        file_path: Path of the file being patched

    Returns:
        Patched content
    """
    import subprocess
    import tempfile
    import os

    with tempfile.TemporaryDirectory() as tmpdir:
        # Write original content
        file_full_path = os.path.join(tmpdir, os.path.basename(file_path))
        with open(file_full_path, 'w') as f:
            f.write(content)

        # Try to apply patch with different strip levels
        for strip_level in [1, 0, 2]:
            result = subprocess.run(
                ["patch", f"-p{strip_level}", "-i", "-"],
                input=diff.encode(),
                cwd=tmpdir,
                capture_output=True
            )
            if result.returncode == 0:
                break

        # Read patched content
        with open(file_full_path) as f:
            return f.read()


def validate_diff_syntax(diff: str) -> tuple[bool, Optional[str]]:
    """
    Validate that a diff has correct syntax.

    Args:
        diff: Unified diff text

    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        parse_unified_diff(diff)
        return True, None
    except ValueError as e:
        return False, str(e)


def get_affected_files(diff: str) -> list[str]:
    """
    Get list of files affected by a diff.

    Args:
        diff: Unified diff text

    Returns:
        List of file paths
    """
    try:
        parsed = parse_unified_diff(diff)
        return [f.path for f in parsed.files]
    except ValueError:
        # Fallback to regex
        files = re.findall(r'^[-+]{3} [ab]/(.+)$', diff, re.MULTILINE)
        return list(set(files))
