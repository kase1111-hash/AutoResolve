"""
Fix Generation Module for AutoResolve.

Handles LLM-based patch generation, diff validation, and retry logic.
"""

import ast
import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from app.config import get_settings


from models.schemas import (
    CodeContext,
    DiffHunk,
    DiffLine,
    FileDiff,
    FixProposal,
    FixValidation,
    ParsedDiff,
    QueuedIssue,
    ValidationResult,
)

logger = logging.getLogger(__name__)

# Approximate token limits for different models
MODEL_CONTEXT_LIMITS = {
    "gpt-4": 8192,
    "gpt-4-turbo": 128000,
    "gpt-3.5-turbo": 4096,
    "claude-3-opus": 200000,
    "claude-3-sonnet": 200000,
    "default": 8000,
}

# Approximate chars per token (conservative estimate)
CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """Estimate the number of tokens in a text string."""
    return len(text) // CHARS_PER_TOKEN


def truncate_for_context(text: str, max_tokens: int, preserve_end: bool = False) -> str:
    """
    Truncate text to fit within token limit.

    Args:
        text: Text to truncate
        max_tokens: Maximum allowed tokens
        preserve_end: If True, preserve the end of the text instead of the beginning

    Returns:
        Truncated text
    """
    max_chars = max_tokens * CHARS_PER_TOKEN
    if len(text) <= max_chars:
        return text

    if preserve_end:
        truncated = "... [truncated] ...\n" + text[-max_chars:]
    else:
        truncated = text[:max_chars] + "\n... [truncated] ..."

    return truncated

# Fix generation prompt template
FIX_PROMPT_TEMPLATE = """You are an expert software engineer fixing a bug. Generate a minimal, focused patch.

## Bug Information
Repository: {repo_full_name}
Error Type: {error_type}
Error Message: {error_message}
Error Signature: {error_signature}

## Stack Trace
{stack_trace}

## Affected Code

### File: {file_path}
```{language}
{function_source}
```

## Issue Description
{issue_body}

## Expected Behavior
{expected_behavior}

## Actual Behavior
{actual_behavior}

## Instructions
1. Analyze the bug and identify the root cause
2. Generate a MINIMAL fix that addresses only this specific issue
3. Do not refactor unrelated code or add new features
4. Ensure the fix handles edge cases mentioned in the issue
5. Output ONLY a unified diff format patch

## Output Format
Respond with ONLY the unified diff, no explanation:

```diff
--- a/{file_path}
+++ b/{file_path}
@@ -line,count +line,count @@
 context line
-removed line
+added line
 context line
```

Generate the patch now:"""

RETRY_PROMPT_TEMPLATE = """Your previous fix attempt failed with the following error:

{error_details}

Please try again, being more careful to:
1. Ensure the diff format is valid
2. Match the exact content of the original file
3. Include sufficient context lines

Original request:
{original_prompt}

Generate a corrected patch:"""


def build_fix_prompt(
    context: CodeContext,
    issue: QueuedIssue,
    validation: ValidationResult,
    previous_errors: Optional[list[str]] = None,
) -> str:
    """
    Build the LLM prompt for fix generation.

    Args:
        context: Code context for the fix
        issue: The original issue
        validation: Validation result
        previous_errors: List of previous attempt errors

    Returns:
        Formatted prompt string
    """
    settings = get_settings()

    # Get model context limit
    model_name = settings.fix_generation.llm_model.lower()
    context_limit = MODEL_CONTEXT_LIMITS.get(model_name, MODEL_CONTEXT_LIMITS["default"])

    # Reserve tokens for output and prompt template
    reserved_tokens = settings.fix_generation.llm_max_tokens + 1000
    available_tokens = context_limit - reserved_tokens

    # Get the first affected function or file content
    if context.functions:
        func = context.functions[0]
        file_path = func.file
        function_source = func.source
    elif context.affected_files:
        file_path = context.affected_files[0]
        function_source = f"[Full file: {file_path}]"
    else:
        file_path = "unknown"
        function_source = "[No code context available]"

    # Truncate large content to fit within context window
    # Allocate tokens: 40% for function source, 30% for stack trace, 30% for issue body
    max_function_tokens = int(available_tokens * 0.4)
    max_trace_tokens = int(available_tokens * 0.3)
    max_body_tokens = int(available_tokens * 0.3)

    function_source = truncate_for_context(function_source, max_function_tokens)
    stack_trace = truncate_for_context(
        validation.issue_context.stack_trace or "Not available",
        max_trace_tokens,
        preserve_end=True,  # Preserve the end of stack traces (most relevant)
    )
    issue_body = truncate_for_context(issue.body, max_body_tokens)

    prompt = FIX_PROMPT_TEMPLATE.format(
        repo_full_name=issue.repo_full_name,
        error_type=validation.issue_context.error_type or "Unknown",
        error_message=validation.issue_context.error_message or "",
        error_signature=context.error_signature or "",
        stack_trace=stack_trace,
        file_path=file_path,
        language=context.language,
        function_source=function_source,
        issue_body=issue_body,
        expected_behavior=validation.issue_context.expected_behavior or "Not specified",
        actual_behavior=validation.issue_context.actual_behavior or "See error above",
    )

    # Add retry context if there were previous errors
    if previous_errors:
        error_details = "\n".join(f"- {err}" for err in previous_errors[-3:])
        prompt = RETRY_PROMPT_TEMPLATE.format(
            error_details=error_details, original_prompt=prompt
        )

    return prompt


async def call_llm(prompt: str, temperature: float = 0.2, attempt: int = 0) -> str:
    """
    Call the LLM to generate a fix.

    Args:
        prompt: The prompt to send
        temperature: Sampling temperature (increased on retries)
        attempt: Current attempt number

    Returns:
        LLM response text
    """
    settings = get_settings()

    # Increase temperature slightly on retries
    adjusted_temp = temperature + (attempt * 0.1)
    adjusted_temp = min(adjusted_temp, 0.9)

    from services.llm_service import LLMService

    llm = LLMService()

    response = await llm.complete(
        prompt=prompt,
        model=settings.fix_generation.llm_model,
        temperature=adjusted_temp,
        max_tokens=settings.fix_generation.llm_max_tokens,
    )

    return response


def extract_diff(response: str) -> Optional[str]:
    """
    Extract a unified diff from an LLM response.

    Args:
        response: Raw LLM response text

    Returns:
        Extracted diff or None if not found
    """
    # Try to extract from markdown code block
    diff_match = re.search(r"```diff\n(.*?)```", response, re.DOTALL)
    if diff_match:
        return diff_match.group(1).strip()

    # Try plain diff block
    diff_match = re.search(r"```\n(---.*?)```", response, re.DOTALL)
    if diff_match:
        return diff_match.group(1).strip()

    # Try to find raw diff
    if response.strip().startswith("---") or response.strip().startswith("diff --git"):
        return response.strip()

    # Look for diff indicators anywhere in response
    lines = response.split("\n")
    diff_lines = []
    in_diff = False

    for line in lines:
        if line.startswith("---") or line.startswith("diff --git"):
            in_diff = True
        if in_diff:
            if line.startswith("```") and diff_lines:
                break
            diff_lines.append(line)

    if diff_lines:
        return "\n".join(diff_lines).strip()

    return None


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

                    lines.append(
                        DiffLine(
                            type=line_type,
                            content=line.value.rstrip("\n"),
                            old_lineno=line.source_line_no,
                            new_lineno=line.target_line_no,
                        )
                    )

                hunks.append(
                    DiffHunk(
                        old_start=hunk.source_start,
                        old_count=hunk.source_length,
                        new_start=hunk.target_start,
                        new_count=hunk.target_length,
                        lines=lines,
                    )
                )

            files.append(
                FileDiff(
                    path=patched_file.path,
                    old_path=(
                        patched_file.source_file
                        if patched_file.source_file != patched_file.path
                        else None
                    ),
                    hunks=hunks,
                    is_new=patched_file.is_added_file,
                    is_deleted=patched_file.is_removed_file,
                )
            )

        return ParsedDiff(files=files)

    except Exception as e:
        logger.error(f"Failed to parse diff: {e}")
        raise ValueError(f"Invalid diff format: {e}")


def validate_fix(diff: str, repo_dir: str, language: str) -> FixValidation:
    """
    Validate that a generated fix is syntactically correct and applies cleanly.

    Args:
        diff: Unified diff text
        repo_dir: Path to repository
        language: Programming language

    Returns:
        Validation result
    """
    settings = get_settings()

    # Step 1: Parse the diff
    try:
        parsed = parse_unified_diff(diff)
    except ValueError as e:
        return FixValidation(valid=False, error="Invalid diff format", details=str(e))

    # Step 2: Check diff applies cleanly
    result = subprocess.run(
        ["git", "apply", "--check", "--verbose"],
        input=diff.encode(),
        cwd=repo_dir,
        capture_output=True,
    )

    if result.returncode != 0:
        return FixValidation(
            valid=False,
            error="Diff does not apply cleanly",
            details=result.stderr.decode(),
        )

    # Step 3: Apply diff temporarily and validate syntax
    try:
        subprocess.run(["git", "apply"], input=diff.encode(), cwd=repo_dir, check=True)

        # Validate syntax for each changed file
        for file_diff in parsed.files:
            file_path = Path(repo_dir) / file_diff.path

            # Python syntax validation via AST
            if str(file_path).endswith(".py"):
                try:
                    with open(file_path) as f:
                        ast.parse(f.read())
                except SyntaxError as e:
                    return FixValidation(
                        valid=False,
                        error="Syntax error in patched code",
                        details=str(e),
                    )

        return FixValidation(valid=True, parsed_diff=parsed)

    except subprocess.CalledProcessError as e:
        return FixValidation(valid=False, error="Failed to apply diff", details=str(e))

    finally:
        # Revert the applied diff
        subprocess.run(["git", "checkout", "."], cwd=repo_dir, capture_output=True)


def count_diff_lines(parsed: ParsedDiff) -> tuple[int, int]:
    """Count added and removed lines in a diff."""
    added = 0
    removed = 0

    for file_diff in parsed.files:
        for hunk in file_diff.hunks:
            for line in hunk.lines:
                if line.type == "add":
                    added += 1
                elif line.type == "remove":
                    removed += 1

    return added, removed


def validate_diff_syntax(diff: str) -> tuple[bool, Optional[str]]:
    """
    Validate diff syntax without applying it.

    Args:
        diff: Unified diff text

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not diff or not diff.strip():
        return False, "Empty diff"

    # Check for basic diff markers
    lines = diff.strip().split("\n")

    has_file_header = any(line.startswith("---") for line in lines)
    has_file_target = any(line.startswith("+++") for line in lines)
    has_hunk_header = any(line.startswith("@@") for line in lines)

    if not has_file_header:
        return False, "Missing file header (--- a/...)"

    if not has_file_target:
        return False, "Missing target file (+++ b/...)"

    if not has_hunk_header:
        return False, "Missing hunk header (@@ ...)"

    # Try to parse it
    try:
        parse_unified_diff(diff)
        return True, None
    except ValueError as e:
        return False, str(e)
    except Exception as e:
        return False, f"Parse error: {str(e)}"


async def generate_fix(
    issue: QueuedIssue, validation: ValidationResult, repo_dir: str
) -> Optional[FixProposal]:
    """
    Generate a fix for an issue with retry logic.

    Args:
        issue: The queued issue
        validation: Validation result with code context
        repo_dir: Path to cloned repository

    Returns:
        Fix proposal or None if generation failed
    """
    settings = get_settings()

    if not validation.code_context:
        logger.warning("No code context available for fix generation")
        return None

    previous_errors = []
    max_attempts = settings.fix_generation.max_generation_attempts

    for attempt in range(max_attempts):
        logger.info(f"Fix generation attempt {attempt + 1}/{max_attempts}")

        try:
            # Build prompt
            prompt = build_fix_prompt(
                context=validation.code_context,
                issue=issue,
                validation=validation,
                previous_errors=previous_errors if attempt > 0 else None,
            )

            # Call LLM
            response = await call_llm(
                prompt=prompt,
                temperature=settings.fix_generation.llm_temperature,
                attempt=attempt,
            )

            # Extract diff
            diff = extract_diff(response)
            if not diff:
                previous_errors.append(
                    f"Attempt {attempt + 1}: No valid diff found in response"
                )
                continue

            # Validate
            fix_validation = validate_fix(
                diff=diff, repo_dir=repo_dir, language=validation.code_context.language
            )

            if fix_validation.valid:
                lines_added, lines_removed = count_diff_lines(
                    fix_validation.parsed_diff
                )

                return FixProposal(
                    issue_id=issue.issue_id,
                    repo_full_name=issue.repo_full_name,
                    suggested_patch=diff,
                    parsed_diff=fix_validation.parsed_diff,
                    affected_files=[f.path for f in fix_validation.parsed_diff.files],
                    lines_added=lines_added,
                    lines_removed=lines_removed,
                    llm_model=settings.fix_generation.llm_model,
                    generation_attempts=attempt + 1,
                )
            else:
                error_msg = f"Attempt {attempt + 1}: {fix_validation.error}"
                if fix_validation.details:
                    error_msg += f" - {fix_validation.details[:200]}"
                previous_errors.append(error_msg)

        except Exception as e:
            logger.error(f"Fix generation attempt {attempt + 1} failed: {e}")
            previous_errors.append(f"Attempt {attempt + 1}: {str(e)}")

    # All attempts failed
    logger.error(
        f"Fix generation failed after {max_attempts} attempts: {previous_errors}"
    )
    return None


async def regenerate_fix(
    issue: QueuedIssue, validation: ValidationResult, feedback: Optional[str] = None
) -> Optional[FixProposal]:
    """
    Regenerate a fix based on feedback.

    Args:
        issue: The queued issue
        validation: Validation result
        feedback: Optional maintainer feedback

    Returns:
        New fix proposal or None
    """
    settings = get_settings()

    # Clone repository again
    import shutil

    from modules.validation import clone_repository

    repo_dir = None
    try:
        repo_dir = clone_repository(
            issue.repo_url, depth=settings.validation.clone_depth
        )

        # If feedback provided, add to context
        if feedback:
            if validation.issue_context.actual_behavior:
                validation.issue_context.actual_behavior += (
                    f"\n\nMaintainer feedback: {feedback}"
                )
            else:
                validation.issue_context.actual_behavior = (
                    f"Maintainer feedback: {feedback}"
                )

        return await generate_fix(issue, validation, repo_dir)

    finally:
        if repo_dir:
            shutil.rmtree(repo_dir, ignore_errors=True)
