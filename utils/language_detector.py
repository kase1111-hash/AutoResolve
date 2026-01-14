"""
Language detection utility for AutoResolve.

Detects programming languages in repositories and files.
"""

from pathlib import Path
from typing import Optional

# Language indicators - files that indicate a specific language
LANGUAGE_INDICATORS = {
    "python": [
        "requirements.txt",
        "setup.py",
        "pyproject.toml",
        "Pipfile",
        "setup.cfg",
        "tox.ini",
        ".python-version"
    ],
    "javascript": [
        "package.json",
        "yarn.lock",
        "package-lock.json",
        ".npmrc"
    ],
    "typescript": [
        "tsconfig.json",
        "tsconfig.base.json"
    ],
    "go": [
        "go.mod",
        "go.sum"
    ],
    "rust": [
        "Cargo.toml",
        "Cargo.lock"
    ],
    "java": [
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "settings.gradle"
    ],
    "ruby": [
        "Gemfile",
        "Gemfile.lock",
        ".ruby-version"
    ],
    "php": [
        "composer.json",
        "composer.lock"
    ],
    "csharp": [
        "*.csproj",
        "*.sln"
    ]
}

# File extension to language mapping
EXTENSION_MAP = {
    ".py": "python",
    ".pyw": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "csharp",
    ".c": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".swift": "swift",
    ".scala": "scala",
    ".r": "r",
    ".R": "r",
    ".lua": "lua",
    ".pl": "perl",
    ".pm": "perl",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell"
}

# Normalized language names
LANGUAGE_ALIASES = {
    "node": "javascript",
    "nodejs": "javascript",
    "js": "javascript",
    "ts": "typescript",
    "py": "python",
    "python3": "python",
    "rb": "ruby",
    "golang": "go",
    "c++": "cpp",
    "c#": "csharp"
}


def detect_language(repo_dir: str) -> str:
    """
    Detect the primary programming language of a repository.

    Args:
        repo_dir: Path to the repository

    Returns:
        Detected language name
    """
    repo_path = Path(repo_dir)

    # Check for language indicator files
    for lang, indicators in LANGUAGE_INDICATORS.items():
        for indicator in indicators:
            if "*" in indicator:
                # Glob pattern
                pattern = indicator
                if list(repo_path.glob(pattern)):
                    return lang
            else:
                if (repo_path / indicator).exists():
                    return lang

    # Count files by extension
    ext_counts = {}
    for ext, lang in EXTENSION_MAP.items():
        count = len(list(repo_path.rglob(f"*{ext}")))
        if count > 0:
            ext_counts[lang] = ext_counts.get(lang, 0) + count

    if ext_counts:
        return max(ext_counts, key=ext_counts.get)

    return "python"  # Default


def detect_file_language(file_path: str) -> Optional[str]:
    """
    Detect the programming language of a file.

    Args:
        file_path: Path to the file

    Returns:
        Detected language or None
    """
    path = Path(file_path)
    ext = path.suffix.lower()

    return EXTENSION_MAP.get(ext)


def normalize_language(language: str) -> str:
    """
    Normalize a language name to standard form.

    Args:
        language: Language name (may be alias)

    Returns:
        Normalized language name
    """
    lower = language.lower()
    return LANGUAGE_ALIASES.get(lower, lower)


def is_code_file(file_path: str) -> bool:
    """
    Check if a file is a code file.

    Args:
        file_path: Path to the file

    Returns:
        True if it's a code file
    """
    return detect_file_language(file_path) is not None


def get_file_extensions(language: str) -> list[str]:
    """
    Get common file extensions for a language.

    Args:
        language: Language name

    Returns:
        List of extensions (including dot)
    """
    normalized = normalize_language(language)
    return [ext for ext, lang in EXTENSION_MAP.items() if lang == normalized]


def get_test_command(repo_dir: str, language: Optional[str] = None) -> str:
    """
    Get the default test command for a repository.

    Args:
        repo_dir: Path to repository
        language: Language (auto-detected if not provided)

    Returns:
        Test command string
    """
    if language is None:
        language = detect_language(repo_dir)

    repo_path = Path(repo_dir)

    commands = {
        "python": _get_python_test_command(repo_path),
        "javascript": "npm test",
        "typescript": "npm test",
        "go": "go test ./...",
        "rust": "cargo test",
        "java": _get_java_test_command(repo_path),
        "ruby": "bundle exec rspec",
        "php": "vendor/bin/phpunit"
    }

    return commands.get(language, "pytest")


def _get_python_test_command(repo_path: Path) -> str:
    """Get Python test command based on project setup."""
    if (repo_path / "pytest.ini").exists():
        return "pytest"
    if (repo_path / "pyproject.toml").exists():
        return "pytest"
    if (repo_path / "setup.cfg").exists():
        return "pytest"
    if (repo_path / "tox.ini").exists():
        return "tox"
    return "python -m pytest"


def _get_java_test_command(repo_path: Path) -> str:
    """Get Java test command based on build tool."""
    if (repo_path / "pom.xml").exists():
        return "mvn test"
    if (repo_path / "build.gradle").exists() or (repo_path / "build.gradle.kts").exists():
        return "gradle test"
    return "mvn test"
