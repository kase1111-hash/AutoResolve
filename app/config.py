"""
Configuration loader for AutoResolve.

Loads configuration from config.yaml and environment variables.
"""

import os
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings


def load_yaml_config(config_path: str = "config.yaml") -> dict[str, Any]:
    """Load configuration from YAML file."""
    path = Path(config_path)
    if not path.exists():
        return {}

    with open(path) as f:
        config = yaml.safe_load(f)

    # Expand environment variables in string values
    return _expand_env_vars(config)


def _expand_env_vars(obj: Any) -> Any:
    """Recursively expand environment variables in configuration."""
    if isinstance(obj, str):
        # Handle ${VAR} syntax
        if obj.startswith("${") and obj.endswith("}"):
            var_name = obj[2:-1]
            return os.environ.get(var_name, "")
        return obj
    elif isinstance(obj, dict):
        return {k: _expand_env_vars(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_expand_env_vars(item) for item in obj]
    return obj


class AppSettings(BaseSettings):
    """Application-level settings."""

    model_config = {"extra": "ignore"}

    name: str = "AutoResolve"
    version: str = "1.0.0"
    debug: bool = False
    secret_key: str = Field(default="")


class GitHubSettings(BaseSettings):
    """GitHub integration settings."""

    model_config = {"extra": "ignore"}

    app_id: int = Field(default=0)
    private_key_path: str = "/secrets/github-app.pem"
    webhook_secret: str = Field(default="")
    api_base_url: str = "https://api.github.com"
    rate_limit_buffer: int = 100
    api_timeout_seconds: float = 30.0
    api_max_retries: int = 3


class FilterConfig(BaseSettings):
    """Issue filtering configuration."""

    model_config = {"extra": "ignore"}

    trigger_labels: list[str] = ["bug", "error", "defect", "crash", "regression"]
    trigger_keywords: list[str] = [
        "TypeError",
        "ValueError",
        "AttributeError",
        "KeyError",
        "traceback",
        "stack trace",
        "exception",
        "fails",
        "broken",
        "doesn't work",
        "error when",
        "crash when",
    ]
    exclude_labels: list[str] = ["wontfix", "duplicate", "invalid", "question"]
    exclude_authors: list[str] = ["dependabot", "renovate", "github-actions"]
    min_body_length: int = 50
    max_age_days: int = 30


class MonitoringConfig(BaseSettings):
    """Monitoring module configuration."""

    model_config = {"extra": "ignore"}

    webhook_path: str = "/webhook/github"
    poll_interval_minutes: int = 5
    poll_lookback_minutes: int = 10
    max_queue_size: int = 1000
    priority_labels: dict[str, int] = {"critical": 1, "high-priority": 2, "bug": 3}
    rate_limit_buffer: int = 100
    webhook_rate_limit_per_minute: int = 120


class ValidationConfig(BaseSettings):
    """Validation module configuration."""

    model_config = {"extra": "ignore"}

    clone_depth: int = 1
    clone_timeout_seconds: int = 120
    sandbox_timeout_seconds: int = 300
    sandbox_memory_limit: str = "512m"
    sandbox_cpu_quota: int = 50000
    sandbox_network: str = "none"
    max_stderr_size: int = 10000
    max_stdout_size: int = 10000
    context_lines_around_error: int = 20
    min_match_score_for_valid: float = 0.6
    llm_parse_model: str = "gpt-4o"
    llm_parse_temperature: float = 0.1
    temp_directory: str = "/tmp/autoresolve"


class FixGenerationConfig(BaseSettings):
    """Fix generation module configuration."""

    model_config = {"extra": "ignore"}

    llm_provider: str = "openai"
    llm_model: str = "gpt-5-code"
    llm_temperature: float = 0.2
    llm_max_tokens: int = 4096
    max_generation_attempts: int = 3
    max_diff_size_lines: int = 200
    context_lines_in_prompt: int = 50
    include_test_files: bool = False
    timeout_seconds: int = 120
    syntax_check_timeout: int = 30


class SecurityAuditConfig(BaseSettings):
    """Security audit module configuration."""

    model_config = {"extra": "ignore"}

    enabled_scanners: list[str] = ["bandit", "semgrep"]
    semgrep_rulesets: list[str] = ["auto", "p/security-audit", "p/owasp-top-ten"]
    bandit_severity_threshold: str = "low"
    enable_dynamic_scan: bool = False
    dynamic_scan_timeout: int = 300
    max_findings_for_approval: int = 5
    auto_reject_severities: list[str] = ["critical"]
    false_positive_patterns: list[str] = [r"test_.*\.py", r".*_test\.py"]
    timeout_seconds: int = 180


class ApprovalConfig(BaseSettings):
    """Approval module configuration."""

    model_config = {"extra": "ignore"}

    timeout_days: int = 7
    poll_interval_minutes: int = 5
    require_maintainer: bool = True
    auto_merge_enabled: bool = True
    auto_merge_wait_for_checks: bool = True
    auto_merge_method: str = "squash"
    branch_prefix: str = "autoresolve/fix-"
    pr_labels: list[str] = ["automated", "autoresolve"]
    close_issue_on_merge: bool = True
    ci_checks_timeout_seconds: int = 300


class DatabaseConfig(BaseSettings):
    """Database configuration."""

    model_config = {"extra": "ignore"}

    # No default credentials - must be set via environment or config
    url: str = Field(default="")
    pool_size: int = 10


class RedisConfig(BaseSettings):
    """Redis configuration."""

    model_config = {"extra": "ignore"}

    # No default - must be set via environment or config
    url: str = Field(default="")


class CeleryConfig(BaseSettings):
    """Celery configuration."""

    model_config = {"extra": "ignore"}

    # No default credentials - must be set via environment or config
    broker_url: str = Field(default="")
    result_backend: str = Field(default="")


class APIConfig(BaseSettings):
    """API configuration."""

    model_config = {"extra": "ignore"}

    host: str = "0.0.0.0"
    port: int = 8000
    api_key: str = Field(default="")
    # CORS origins - empty list means development mode (allow all, no credentials)
    # Set explicit origins for production (e.g., ["https://your-domain.com"])
    cors_origins: list[str] = []


class LoggingConfig(BaseSettings):
    """Logging configuration."""

    model_config = {"extra": "ignore"}

    level: str = "INFO"
    format: str = "json"
    output: str = "stdout"


class Settings(BaseSettings):
    """Master configuration aggregating all settings."""

    app: AppSettings = AppSettings()
    github: GitHubSettings = GitHubSettings()
    filtering: FilterConfig = FilterConfig()
    monitoring: MonitoringConfig = MonitoringConfig()
    validation: ValidationConfig = ValidationConfig()
    fix_generation: FixGenerationConfig = FixGenerationConfig()
    security: SecurityAuditConfig = SecurityAuditConfig()
    approval: ApprovalConfig = ApprovalConfig()
    database: DatabaseConfig = DatabaseConfig()
    redis: RedisConfig = RedisConfig()
    celery: CeleryConfig = CeleryConfig()
    api: APIConfig = APIConfig()
    logging: LoggingConfig = LoggingConfig()
    monitored_repos: list[str] = []

    @classmethod
    def from_yaml(cls, config_path: str = "config.yaml") -> "Settings":
        """Load settings from YAML file and environment variables."""
        yaml_config = load_yaml_config(config_path)

        settings = cls()

        # Override with YAML values
        if yaml_config:
            settings = cls._merge_yaml_config(settings, yaml_config)

        return settings

    @classmethod
    def _merge_yaml_config(cls, settings: "Settings", yaml_config: dict) -> "Settings":
        """Merge YAML configuration into settings."""
        # Mapping of YAML keys to (attribute name, config class)
        config_mapping = {
            "app": ("app", AppSettings),
            "github": ("github", GitHubSettings),
            "filtering": ("filtering", FilterConfig),
            "monitoring": ("monitoring", MonitoringConfig),
            "validation": ("validation", ValidationConfig),
            "fix_generation": ("fix_generation", FixGenerationConfig),
            "security": ("security", SecurityAuditConfig),
            "approval": ("approval", ApprovalConfig),
            "database": ("database", DatabaseConfig),
            "redis": ("redis", RedisConfig),
            "celery": ("celery", CeleryConfig),
            "api": ("api", APIConfig),
            "logging": ("logging", LoggingConfig),
        }

        # Merge standard config sections
        for yaml_key, (attr_name, config_class) in config_mapping.items():
            if yaml_key in yaml_config:
                current = getattr(settings, attr_name)
                merged = {**current.model_dump(), **yaml_config[yaml_key]}
                setattr(settings, attr_name, config_class(**merged))

        # Handle monitored_repos list
        if "monitored_repos" in yaml_config:
            settings.monitored_repos = yaml_config["monitored_repos"]

        return settings



# Global settings instance
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get the global settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings.from_yaml()
    return _settings


def reload_settings(config_path: str = "config.yaml") -> Settings:
    """Reload settings from configuration file."""
    global _settings
    _settings = Settings.from_yaml(config_path)
    return _settings


class ConfigurationError(Exception):
    """Raised when required configuration is missing."""

    pass


def validate_settings(settings: Settings) -> list[str]:
    """
    Validate that all required settings are configured.

    Args:
        settings: The settings instance to validate

    Returns:
        List of validation error messages (empty if valid)
    """
    errors = []

    # Required settings for production deployment
    if not settings.database.url:
        errors.append(
            "DATABASE_URL is required. Set via environment variable or config.yaml "
            "(database.url). Example: postgresql://user:pass@host:5432/dbname"
        )

    if not settings.redis.url:
        errors.append(
            "REDIS_URL is required. Set via environment variable or config.yaml "
            "(redis.url). Example: redis://localhost:6379/0"
        )

    if not settings.celery.broker_url:
        errors.append(
            "CELERY_BROKER_URL is required. Set via environment variable or config.yaml "
            "(celery.broker_url). Example: amqp://user:pass@host:5672//"
        )

    if not settings.github.webhook_secret:
        errors.append(
            "GITHUB_WEBHOOK_SECRET is required for security. Set via environment "
            "variable or config.yaml (github.webhook_secret)"
        )

    # Warnings (not errors) for recommended settings
    if not settings.app.secret_key:
        errors.append(
            "WARNING: APP_SECRET_KEY is recommended. Set via environment variable "
            "or config.yaml (app.secret_key)"
        )

    return errors


def validate_settings_or_raise(settings: Settings) -> None:
    """
    Validate settings and raise ConfigurationError if invalid.

    Args:
        settings: The settings instance to validate

    Raises:
        ConfigurationError: If required settings are missing
    """
    errors = validate_settings(settings)
    # Filter out warnings (they start with "WARNING:")
    critical_errors = [e for e in errors if not e.startswith("WARNING:")]

    if critical_errors:
        error_msg = "Configuration validation failed:\n" + "\n".join(
            f"  - {e}" for e in critical_errors
        )
        raise ConfigurationError(error_msg)
