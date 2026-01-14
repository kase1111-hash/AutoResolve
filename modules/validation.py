"""
Validation Module for AutoResolve.

Handles issue parsing, repository cloning, sandbox execution, and reproduction validation.
"""

import ast
import logging
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.config import get_settings
from models.schemas import (
    CodeContext,
    EnvironmentInfo,
    FunctionContext,
    IssueContext,
    QueuedIssue,
    ReproductionResult,
    ValidationResult,
)

logger = logging.getLogger(__name__)

# Sandbox images by language
SANDBOX_IMAGES = {
    "python": {
        "default": "python:3.11-slim",
        "3.8": "python:3.8-slim",
        "3.9": "python:3.9-slim",
        "3.10": "python:3.10-slim",
        "3.11": "python:3.11-slim",
        "3.12": "python:3.12-slim",
    },
    "node": {"default": "node:20-slim", "18": "node:18-slim", "20": "node:20-slim"},
    "go": {"default": "golang:1.21-alpine"},
    "rust": {"default": "rust:1.75-slim"},
    "java": {"default": "eclipse-temurin:21-jdk"},
}

# Default test commands per language
DEFAULT_TEST_COMMANDS = {
    "python": [
        "pip install -r requirements.txt 2>/dev/null || true",
        "pip install pytest 2>/dev/null || true",
        "pytest -v --tb=short 2>&1 || python -m unittest discover 2>&1",
    ],
    "node": ["npm install 2>/dev/null || true", "npm test 2>&1"],
    "go": ["go test ./... 2>&1"],
    "rust": ["cargo test 2>&1"],
    "java": ["mvn test 2>&1 || gradle test 2>&1"],
}


async def parse_issue(title: str, body: str) -> IssueContext:
    """
    Parse an issue to extract structured information.

    Uses LLM for parsing with fallback to regex-based extraction.
    """
    settings = get_settings()

    # Try LLM parsing first
    try:
        from services.llm_service import LLMService

        llm = LLMService()

        prompt = f"""You are a bug report parser. Extract structured information from this GitHub issue.

Issue Title: {title}
Issue Body:
{body}

Extract the following (respond in JSON only):
{{
  "error_type": "The exception or error class (e.g., TypeError, NullPointerException)",
  "error_message": "The specific error message if present",
  "affected_files": ["List of file paths mentioned"],
  "affected_functions": ["List of function/method names mentioned"],
  "stack_trace": "Full stack trace if present, else null",
  "reproduction_steps": ["Ordered list of steps to reproduce"],
  "expected_behavior": "What should happen",
  "actual_behavior": "What actually happens",
  "environment": {{
    "os": "Operating system if mentioned",
    "python_version": "Python version if mentioned",
    "dependencies": ["Relevant package versions"]
  }},
  "code_snippets": ["Any code blocks from the issue"],
  "confidence": 0.0-1.0
}}

If information is not present, use null. Be conservative with confidence."""

        response = await llm.complete(
            prompt=prompt,
            model=settings.validation.llm_parse_model,
            temperature=settings.validation.llm_parse_temperature,
            max_tokens=2000,
        )

        import json

        parsed = json.loads(response)

        return IssueContext(
            error_type=parsed.get("error_type"),
            error_message=parsed.get("error_message"),
            affected_files=parsed.get("affected_files", []),
            affected_functions=parsed.get("affected_functions", []),
            stack_trace=parsed.get("stack_trace"),
            reproduction_steps=parsed.get("reproduction_steps", []),
            expected_behavior=parsed.get("expected_behavior"),
            actual_behavior=parsed.get("actual_behavior"),
            environment=EnvironmentInfo(**parsed.get("environment", {})),
            code_snippets=parsed.get("code_snippets", []),
            parse_confidence=parsed.get("confidence", 0.5),
        )

    except Exception as e:
        logger.warning(f"LLM parsing failed, using fallback: {e}")
        return _fallback_parse(title, body)


def _fallback_parse(title: str, body: str) -> IssueContext:
    """Fallback regex-based parsing when LLM is unavailable."""
    combined = f"{title}\n{body}"

    # Extract error type from common patterns
    error_patterns = [
        r"(TypeError|ValueError|AttributeError|KeyError|IndexError|RuntimeError|Exception)",
        r"(NullPointerException|IndexOutOfBoundsException|IllegalArgumentException)",
        r"(SegmentationFault|SIGSEGV)",
    ]

    error_type = None
    for pattern in error_patterns:
        match = re.search(pattern, combined, re.IGNORECASE)
        if match:
            error_type = match.group(1)
            break

    # Extract file paths
    file_patterns = [
        r'(?:File\s+["\']?)([^"\':\s]+\.py)',
        r"(?:in\s+)([a-zA-Z0-9_/]+\.(?:py|js|ts|go|rs|java))",
        r"([a-zA-Z0-9_/]+\.(?:py|js|ts|go|rs|java))(?:\s*:?\s*\d+)?",
    ]

    affected_files = []
    for pattern in file_patterns:
        matches = re.findall(pattern, combined)
        affected_files.extend(matches)
    affected_files = list(set(affected_files))[:5]

    # Extract function names
    func_patterns = [
        r"(?:in\s+|function\s+|def\s+|fn\s+)([a-zA-Z_][a-zA-Z0-9_]*)",
        r"([a-zA-Z_][a-zA-Z0-9_]*)\s*\([^)]*\)\s*$",
    ]

    affected_functions = []
    for pattern in func_patterns:
        matches = re.findall(pattern, combined)
        affected_functions.extend(matches)
    affected_functions = list(set(affected_functions))[:5]

    # Extract code snippets (markdown code blocks)
    code_blocks = re.findall(r"```(?:\w+)?\n(.*?)```", combined, re.DOTALL)

    # Extract stack trace
    stack_trace = None
    trace_match = re.search(
        r"(Traceback \(most recent call last\):.*?)(?:\n\n|$)", combined, re.DOTALL
    )
    if trace_match:
        stack_trace = trace_match.group(1)

    return IssueContext(
        error_type=error_type,
        error_message=None,
        affected_files=affected_files,
        affected_functions=affected_functions,
        stack_trace=stack_trace,
        reproduction_steps=[],
        expected_behavior=None,
        actual_behavior=None,
        environment=EnvironmentInfo(),
        code_snippets=code_blocks,
        parse_confidence=0.3,
    )


def clone_repository(
    repo_url: str, depth: int = 1, branch: Optional[str] = None
) -> str:
    """
    Clone a repository to a temporary directory.

    Args:
        repo_url: GitHub repository URL
        depth: Clone depth (shallow clone)
        branch: Specific branch to clone

    Returns:
        Path to cloned repository
    """
    settings = get_settings()
    temp_dir = tempfile.mkdtemp(dir=settings.validation.temp_directory)

    cmd = ["git", "clone", "--depth", str(depth)]
    if branch:
        cmd.extend(["--branch", branch])
    cmd.extend([repo_url, temp_dir])

    try:
        subprocess.run(
            cmd,
            capture_output=True,
            timeout=settings.validation.clone_timeout_seconds,
            check=True,
        )
        logger.info(f"Cloned repository to {temp_dir}")
        return temp_dir
    except subprocess.TimeoutExpired:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise TimeoutError("Repository clone timed out")
    except subprocess.CalledProcessError as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise RuntimeError(f"Failed to clone repository: {e.stderr.decode()}")


def detect_language(repo_dir: str) -> str:
    """Detect the primary programming language of a repository."""
    repo_path = Path(repo_dir)

    # Check for language-specific files
    indicators = {
        "python": ["requirements.txt", "setup.py", "pyproject.toml", "Pipfile"],
        "node": ["package.json", "yarn.lock", "package-lock.json"],
        "go": ["go.mod", "go.sum"],
        "rust": ["Cargo.toml", "Cargo.lock"],
        "java": ["pom.xml", "build.gradle", "build.gradle.kts"],
    }

    for lang, files in indicators.items():
        for file in files:
            if (repo_path / file).exists():
                return lang

    # Count file extensions as fallback
    extensions = {
        ".py": "python",
        ".js": "node",
        ".ts": "node",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
    }

    ext_counts = {}
    for ext, lang in extensions.items():
        count = len(list(repo_path.rglob(f"*{ext}")))
        ext_counts[lang] = ext_counts.get(lang, 0) + count

    if ext_counts:
        return max(ext_counts, key=ext_counts.get)

    return "python"  # Default


def get_sandbox_image(language: str, version: Optional[str] = None) -> str:
    """Get the appropriate Docker sandbox image for a language."""
    lang_images = SANDBOX_IMAGES.get(language, SANDBOX_IMAGES["python"])

    if version and version in lang_images:
        return lang_images[version]
    return lang_images.get("default", "python:3.11-slim")


def reproduce_issue(
    issue: QueuedIssue, context: IssueContext, repo_dir: str
) -> ReproductionResult:
    """
    Attempt to reproduce an issue in a sandbox environment.

    Args:
        issue: The queued issue
        context: Parsed issue context
        repo_dir: Path to cloned repository

    Returns:
        Reproduction result with validation status
    """
    settings = get_settings()
    language = detect_language(repo_dir)
    sandbox_image = get_sandbox_image(language)

    # Build reproduction commands
    if context.reproduction_steps:
        commands = context.reproduction_steps
    else:
        commands = DEFAULT_TEST_COMMANDS.get(language, DEFAULT_TEST_COMMANDS["python"])

    # Execute in Docker sandbox
    try:
        from services.docker_service import DockerService

        docker = DockerService()

        result = docker.run_in_sandbox(
            image=sandbox_image,
            repo_dir=repo_dir,
            commands=commands,
            timeout=settings.validation.sandbox_timeout_seconds,
            memory_limit=settings.validation.sandbox_memory_limit,
            network_mode=settings.validation.sandbox_network,
        )

        # Analyze result
        stderr = result.get("stderr", "")[-settings.validation.max_stderr_size :]
        stdout = result.get("stdout", "")[-settings.validation.max_stdout_size :]
        exit_code = result.get("exit_code", 1)

        # Check if error matches expected
        if context.error_type and context.error_type in stderr:
            validity = "confirmed"
            match_score = _compute_similarity(context.error_message or "", stderr)
        elif exit_code != 0:
            validity = "partial"
            match_score = 0.5
        else:
            validity = "not_reproduced"
            match_score = 0.0

        error_signature = _extract_error_signature(stderr)

        return ReproductionResult(
            valid=(validity == "confirmed"),
            validity_status=validity,
            match_score=match_score,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            error_signature=error_signature,
            execution_time=result.get("duration", 0.0),
            sandbox_image=sandbox_image,
        )

    except Exception as e:
        logger.error(f"Sandbox execution failed: {e}")
        return ReproductionResult(
            valid=False,
            validity_status="error",
            match_score=0.0,
            stderr=str(e),
            exit_code=-1,
            sandbox_image=sandbox_image,
        )


def _compute_similarity(expected: str, actual: str) -> float:
    """Compute text similarity between expected and actual error messages."""
    if not expected or not actual:
        return 0.0

    expected_lower = expected.lower()
    actual_lower = actual.lower()

    # Simple containment check
    if expected_lower in actual_lower:
        return 0.9

    # Word overlap
    expected_words = set(expected_lower.split())
    actual_words = set(actual_lower.split())

    if not expected_words:
        return 0.0

    overlap = len(expected_words & actual_words)
    return overlap / len(expected_words)


def _extract_error_signature(stderr: str) -> Optional[str]:
    """Extract a unique error signature from stderr."""
    # Look for Python tracebacks
    tb_match = re.search(
        r"((?:TypeError|ValueError|KeyError|AttributeError|RuntimeError|Exception):\s*.+?)(?:\n|$)",
        stderr,
    )
    if tb_match:
        return tb_match.group(1).strip()

    # Look for other error patterns
    error_match = re.search(
        r"(?:error|exception|failed):\s*(.+?)(?:\n|$)", stderr, re.IGNORECASE
    )
    if error_match:
        return error_match.group(1).strip()

    return None


def extract_context(
    repo_dir: str, context: IssueContext, result: ReproductionResult
) -> CodeContext:
    """
    Extract code context needed for fix generation.

    Args:
        repo_dir: Path to cloned repository
        context: Parsed issue context
        result: Reproduction result

    Returns:
        Code context for fix generation
    """
    settings = get_settings()
    repo_path = Path(repo_dir)

    affected_files = []

    # From parsed issue
    for file_path in context.affected_files:
        full_path = repo_path / file_path
        if full_path.exists() and full_path.is_file():
            affected_files.append(file_path)

    # From stack trace
    if result.stderr:
        trace_files = _parse_stack_trace_files(result.stderr)
        for file_path in trace_files:
            if file_path not in affected_files:
                full_path = repo_path / file_path
                if full_path.exists() and full_path.is_file():
                    affected_files.append(file_path)

    # Deduplicate and filter to code files
    affected_files = list(set(affected_files))
    affected_files = [f for f in affected_files if _is_code_file(f)]

    # Extract function bodies
    functions = []
    language = detect_language(repo_dir)

    for file_path in affected_files:
        full_path = repo_path / file_path

        if language == "python":
            try:
                with open(full_path) as f:
                    source = f.read()
                tree = ast.parse(source)

                for func_name in context.affected_functions:
                    for node in ast.walk(tree):
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            if node.name == func_name:
                                func_source = _get_source_lines(
                                    full_path, node.lineno, node.end_lineno
                                )
                                imports = _extract_imports(tree)
                                functions.append(
                                    FunctionContext(
                                        file=file_path,
                                        name=func_name,
                                        start_line=node.lineno,
                                        end_line=node.end_lineno or node.lineno,
                                        source=func_source,
                                        imports=imports,
                                    )
                                )
            except Exception as e:
                logger.warning(f"Failed to parse {file_path}: {e}")

    # If no specific functions, extract context around error line
    if not functions and result.error_signature:
        line_number = _extract_line_from_trace(result.stderr)
        if line_number and affected_files:
            func_context = _extract_context_around_line(
                repo_path / affected_files[0],
                line_number,
                settings.validation.context_lines_around_error,
            )
            if func_context:
                functions.append(func_context)

    # Get repo commit
    try:
        git_result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo_dir, capture_output=True, text=True
        )
        repo_commit = git_result.stdout.strip()
    except Exception:
        repo_commit = ""

    return CodeContext(
        affected_files=affected_files,
        functions=functions,
        error_signature=result.error_signature or "",
        test_command=_get_test_command(repo_dir, language),
        language=language,
        repo_commit=repo_commit,
    )


def _parse_stack_trace_files(stderr: str) -> list[str]:
    """Extract file paths from a stack trace."""
    # Python traceback format
    files = re.findall(r'File "([^"]+)"', stderr)

    # Filter to relative paths within repo
    result = []
    for f in files:
        if not os.path.isabs(f) and not f.startswith("/"):
            result.append(f)
        elif "/code/" in f:
            # Docker mounted path
            result.append(f.split("/code/")[-1])

    return result


def _is_code_file(path: str) -> bool:
    """Check if a file is a code file."""
    code_extensions = {".py", ".js", ".ts", ".go", ".rs", ".java", ".c", ".cpp", ".rb"}
    return Path(path).suffix in code_extensions


def _get_source_lines(file_path: Path, start: int, end: Optional[int]) -> str:
    """Get source lines from a file."""
    try:
        with open(file_path) as f:
            lines = f.readlines()
        end = end or start
        return "".join(lines[start - 1 : end])
    except Exception:
        return ""


def _extract_imports(tree: ast.AST) -> list[str]:
    """Extract import statements from an AST."""
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                imports.append(f"from {module} import {alias.name}")
    return imports


def _extract_line_from_trace(stderr: str) -> Optional[int]:
    """Extract the error line number from a stack trace."""
    # Python format: File "...", line X
    match = re.search(r"line (\d+)", stderr)
    if match:
        return int(match.group(1))
    return None


def _extract_context_around_line(
    file_path: Path, line: int, context_lines: int
) -> Optional[FunctionContext]:
    """Extract code context around a specific line."""
    try:
        with open(file_path) as f:
            lines = f.readlines()

        start = max(1, line - context_lines)
        end = min(len(lines), line + context_lines)
        source = "".join(lines[start - 1 : end])

        return FunctionContext(
            file=str(file_path.name),
            name=f"context_around_line_{line}",
            start_line=start,
            end_line=end,
            source=source,
            imports=[],
        )
    except Exception:
        return None


def _get_test_command(repo_dir: str, language: str) -> str:
    """Get the appropriate test command for a repository."""
    repo_path = Path(repo_dir)

    if language == "python":
        if (repo_path / "pytest.ini").exists() or (
            repo_path / "pyproject.toml"
        ).exists():
            return "pytest"
        return "python -m unittest discover"
    elif language == "node":
        return "npm test"
    elif language == "go":
        return "go test ./..."
    elif language == "rust":
        return "cargo test"
    elif language == "java":
        if (repo_path / "pom.xml").exists():
            return "mvn test"
        return "gradle test"

    return "pytest"


async def validate_issue(issue: QueuedIssue) -> ValidationResult:
    """
    Complete validation pipeline for an issue.

    Args:
        issue: The queued issue to validate

    Returns:
        Complete validation result
    """
    settings = get_settings()
    start_time = datetime.utcnow()

    # Parse issue
    context = await parse_issue(issue.title, issue.body)

    repo_dir = None
    try:
        # Clone repository
        repo_dir = clone_repository(
            issue.repo_url, depth=settings.validation.clone_depth
        )

        # Reproduce issue
        reproduction = reproduce_issue(issue, context, repo_dir)

        # Extract code context if reproduction was successful
        code_context = None
        if reproduction.valid or reproduction.validity_status == "partial":
            code_context = extract_context(repo_dir, context, reproduction)

        duration = (datetime.utcnow() - start_time).total_seconds()

        return ValidationResult(
            issue_id=issue.issue_id,
            repo_full_name=issue.repo_full_name,
            valid=reproduction.valid,
            validity_status=reproduction.validity_status,
            issue_context=context,
            reproduction_result=reproduction,
            code_context=code_context,
            validation_duration=duration,
        )

    finally:
        # Cleanup
        if repo_dir and os.path.exists(repo_dir):
            shutil.rmtree(repo_dir, ignore_errors=True)
