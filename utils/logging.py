"""
Logging utility for AutoResolve.

Provides structured logging with JSON output support.
"""

import json
import logging
import sys
from datetime import datetime

import structlog


class JSONFormatter(logging.Formatter):
    """JSON log formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add extra fields
        for key, value in record.__dict__.items():
            if key not in (
                "name",
                "msg",
                "args",
                "created",
                "filename",
                "funcName",
                "levelname",
                "levelno",
                "lineno",
                "module",
                "msecs",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "stack_info",
                "exc_info",
                "exc_text",
                "thread",
                "threadName",
                "message",
            ):
                try:
                    json.dumps(value)  # Check if serializable
                    log_data[key] = value
                except (TypeError, ValueError):
                    log_data[key] = str(value)

        return json.dumps(log_data)


def setup_logging(
    level: str = "INFO", format_type: str = "json", output: str = "stdout"
) -> None:
    """
    Set up logging configuration.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        format_type: Output format (json, text)
        output: Output destination (stdout, stderr, or file path)
    """
    # Get the root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))

    # Remove existing handlers
    root_logger.handlers = []

    # Create handler
    if output == "stdout":
        handler = logging.StreamHandler(sys.stdout)
    elif output == "stderr":
        handler = logging.StreamHandler(sys.stderr)
    else:
        handler = logging.FileHandler(output)

    # Set formatter
    if format_type == "json":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )

    root_logger.addHandler(handler)

    # Configure structlog
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance.

    Args:
        name: Logger name (usually __name__)

    Returns:
        Logger instance
    """
    return logging.getLogger(name)


def get_structured_logger(name: str) -> structlog.BoundLogger:
    """
    Get a structured logger instance.

    Args:
        name: Logger name

    Returns:
        Structured logger instance
    """
    return structlog.get_logger(name)


class LogContext:
    """Context manager for adding context to log messages."""

    def __init__(self, logger: logging.Logger, **context):
        self.logger = logger
        self.context = context
        self.old_factory = None

    def __enter__(self):
        self.old_factory = logging.getLogRecordFactory()

        context = self.context

        def record_factory(*args, **kwargs):
            record = self.old_factory(*args, **kwargs)
            for key, value in context.items():
                setattr(record, key, value)
            return record

        logging.setLogRecordFactory(record_factory)
        return self

    def __exit__(self, _exc_type, _exc_val, _exc_tb):
        logging.setLogRecordFactory(self.old_factory)


def log_issue_event(
    logger: logging.Logger, event: str, issue_id: int, repo: str, **extra
) -> None:
    """
    Log an issue-related event.

    Args:
        logger: Logger instance
        event: Event name
        issue_id: GitHub issue number
        repo: Repository full name
        **extra: Additional context
    """
    logger.info(
        f"{event}: {repo}#{issue_id}",
        extra={"event": event, "issue_id": issue_id, "repo": repo, **extra},
    )


def log_proposal_event(
    logger: logging.Logger,
    event: str,
    proposal_id: str,
    issue_id: int,
    repo: str,
    **extra,
) -> None:
    """
    Log a proposal-related event.

    Args:
        logger: Logger instance
        event: Event name
        proposal_id: Proposal UUID
        issue_id: GitHub issue number
        repo: Repository full name
        **extra: Additional context
    """
    logger.info(
        f"{event}: proposal {proposal_id[:8]} for {repo}#{issue_id}",
        extra={
            "event": event,
            "proposal_id": proposal_id,
            "issue_id": issue_id,
            "repo": repo,
            **extra,
        },
    )


def log_security_event(
    logger: logging.Logger,
    event: str,
    severity: str,
    finding_count: int,
    proposal_id: str,
    **extra,
) -> None:
    """
    Log a security-related event.

    Args:
        logger: Logger instance
        event: Event name
        severity: Highest severity found
        finding_count: Number of findings
        proposal_id: Proposal UUID
        **extra: Additional context
    """
    log_method = logger.warning if severity in ("critical", "high") else logger.info

    log_method(
        f"{event}: {finding_count} findings (max severity: {severity})",
        extra={
            "event": event,
            "severity": severity,
            "finding_count": finding_count,
            "proposal_id": proposal_id,
            **extra,
        },
    )


def log_api_request(
    logger: logging.Logger,
    method: str,
    path: str,
    status_code: int,
    duration_ms: float,
    **extra,
) -> None:
    """
    Log an API request.

    Args:
        logger: Logger instance
        method: HTTP method
        path: Request path
        status_code: Response status code
        duration_ms: Request duration in milliseconds
        **extra: Additional context
    """
    log_method = logger.warning if status_code >= 400 else logger.info

    log_method(
        f"{method} {path} -> {status_code} ({duration_ms:.2f}ms)",
        extra={
            "event": "api_request",
            "method": method,
            "path": path,
            "status_code": status_code,
            "duration_ms": duration_ms,
            **extra,
        },
    )
