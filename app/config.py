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


class FilterConfig(BaseSettings):
    """Issue filtering configuration."""

    model_config = {"extra": "ignore"}

    trigger_labels: list[str] = ["bug", "error", "defect", "crash", "regression"]
    trigger_keywords: list[str] = [
        "TypeError",
        "ValueError",
        "AttributeError",
        "KeyError",
        "NullPointerException",
        "IndexOutOfBounds",
        "SegmentationFault",
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


class NotificationConfig(BaseSettings):
    """Notification configuration."""

    model_config = {"extra": "ignore"}

    slack_enabled: bool = False
    slack_webhook_url: str = Field(default="")
    slack_channel: str = "#autoresolve"
    email_enabled: bool = False
    smtp_host: str = "smtp.example.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_from: str = "autoresolve@example.com"


class DatabaseConfig(BaseSettings):
    """Database configuration."""

    model_config = {"extra": "ignore"}

    url: str = Field(
        default="postgresql://autoresolve:password@localhost:5432/autoresolve"
    )
    pool_size: int = 10


class RedisConfig(BaseSettings):
    """Redis configuration."""

    model_config = {"extra": "ignore"}

    url: str = Field(default="redis://localhost:6379/0")


class CeleryConfig(BaseSettings):
    """Celery configuration."""

    model_config = {"extra": "ignore"}

    broker_url: str = Field(default="amqp://guest:guest@localhost:5672//")
    result_backend: str = Field(default="redis://localhost:6379/1")


class APIConfig(BaseSettings):
    """API configuration."""

    model_config = {"extra": "ignore"}

    host: str = "0.0.0.0"
    port: int = 8000
    api_key: str = Field(default="")


class LoggingConfig(BaseSettings):
    """Logging configuration."""

    model_config = {"extra": "ignore"}

    level: str = "INFO"
    format: str = "json"
    output: str = "stdout"


class ObservabilityConfig(BaseSettings):
    """Observability configuration."""

    model_config = {"extra": "ignore"}

    sentry_dsn: str = Field(default="")
    prometheus_enabled: bool = True
    prometheus_port: int = 9090


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
    notifications: NotificationConfig = NotificationConfig()
    database: DatabaseConfig = DatabaseConfig()
    redis: RedisConfig = RedisConfig()
    celery: CeleryConfig = CeleryConfig()
    api: APIConfig = APIConfig()
    logging: LoggingConfig = LoggingConfig()
    observability: ObservabilityConfig = ObservabilityConfig()
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
        if "app" in yaml_config:
            settings.app = AppSettings(
                **{**settings.app.model_dump(), **yaml_config["app"]}
            )
        if "github" in yaml_config:
            settings.github = GitHubSettings(
                **{**settings.github.model_dump(), **yaml_config["github"]}
            )
        if "filtering" in yaml_config:
            settings.filtering = FilterConfig(
                **{**settings.filtering.model_dump(), **yaml_config["filtering"]}
            )
        if "monitoring" in yaml_config:
            settings.monitoring = MonitoringConfig(
                **{**settings.monitoring.model_dump(), **yaml_config["monitoring"]}
            )
        if "validation" in yaml_config:
            settings.validation = ValidationConfig(
                **{**settings.validation.model_dump(), **yaml_config["validation"]}
            )
        if "fix_generation" in yaml_config:
            settings.fix_generation = FixGenerationConfig(
                **{
                    **settings.fix_generation.model_dump(),
                    **yaml_config["fix_generation"],
                }
            )
        if "security" in yaml_config:
            settings.security = SecurityAuditConfig(
                **{**settings.security.model_dump(), **yaml_config["security"]}
            )
        if "approval" in yaml_config:
            settings.approval = ApprovalConfig(
                **{**settings.approval.model_dump(), **yaml_config["approval"]}
            )
        if "notifications" in yaml_config:
            notif_config = yaml_config["notifications"]
            # Handle nested slack/email structure from YAML
            flat_notif = {}
            if "slack" in notif_config:
                slack = notif_config["slack"]
                if "enabled" in slack:
                    flat_notif["slack_enabled"] = slack["enabled"]
                if "webhook_url" in slack:
                    flat_notif["slack_webhook_url"] = slack["webhook_url"]
                if "channel" in slack:
                    flat_notif["slack_channel"] = slack["channel"]
            if "email" in notif_config:
                email = notif_config["email"]
                if "enabled" in email:
                    flat_notif["email_enabled"] = email["enabled"]
                if "smtp_host" in email:
                    flat_notif["smtp_host"] = email["smtp_host"]
                if "smtp_port" in email:
                    flat_notif["smtp_port"] = email["smtp_port"]
            settings.notifications = NotificationConfig(
                **{**settings.notifications.model_dump(), **flat_notif}
            )
        if "database" in yaml_config:
            settings.database = DatabaseConfig(
                **{**settings.database.model_dump(), **yaml_config["database"]}
            )
        if "redis" in yaml_config:
            settings.redis = RedisConfig(
                **{**settings.redis.model_dump(), **yaml_config["redis"]}
            )
        if "celery" in yaml_config:
            settings.celery = CeleryConfig(
                **{**settings.celery.model_dump(), **yaml_config["celery"]}
            )
        if "api" in yaml_config:
            settings.api = APIConfig(
                **{**settings.api.model_dump(), **yaml_config["api"]}
            )
        if "logging" in yaml_config:
            settings.logging = LoggingConfig(
                **{**settings.logging.model_dump(), **yaml_config["logging"]}
            )
        if "observability" in yaml_config:
            settings.observability = ObservabilityConfig(
                **{
                    **settings.observability.model_dump(),
                    **yaml_config["observability"],
                }
            )
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
