"""Shared helpers for the step scripts."""

from __future__ import annotations

import logging
import warnings

warnings.filterwarnings("ignore", message=".*langchain.mcp.*beta.*")

from agentescrow.config import ConfigError, Settings  # noqa: E402
from agentescrow.logging_setup import configure_logging  # noqa: E402


def bootstrap(service: str) -> tuple[Settings, logging.Logger]:
    """Load settings, configure logging, and return ``(settings, logger)``."""
    settings = Settings.from_env()
    configure_logging(settings.log_level, settings.log_dir, service=service)
    try:
        settings.validate_modes()
    except ConfigError as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc
    return settings, logging.getLogger(service)


def mask(value: str) -> str:
    if not value:
        return "(not set)"
    return f"{value[:4]}...{value[-2:]}" if len(value) > 10 else "***"
