"""Logging configuration.

One call to :func:`configure_logging` gives every process (API, MCP servers, scripts)
the same format on stderr plus a rotating file. Log lines carry the current job id,
which is set with :func:`job_logging_context`, so one job can be followed across
modules with a simple ``grep job=job_ab12cd34 logs/*.log``.

Secrets (client secrets, API keys, mandate tokens) must never be logged.
"""

from __future__ import annotations

import contextvars
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

_job_id: contextvars.ContextVar[str] = contextvars.ContextVar("job_id", default="-")
_LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)-34s | job=%(job_id)s | %(message)s"
_NOISY_LOGGERS = ("httpx", "httpcore", "urllib3", "werkzeug", "asyncio", "mcp", "fastmcp")


class _JobContextFilter(logging.Filter):
    """Adds ``record.job_id`` so the format string can always reference it."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.job_id = _job_id.get()
        return True


@contextmanager
def job_logging_context(job_id: str) -> Iterator[None]:
    """Tag every log line emitted inside the ``with`` block with ``job_id``."""
    token = _job_id.set(job_id)
    try:
        yield
    finally:
        _job_id.reset(token)


def configure_logging(level: str = "INFO", log_dir: Path | None = None, service: str = "agentescrow") -> None:
    """Configure the root logger. Safe to call more than once."""
    root = logging.getLogger()
    if getattr(root, "_agentescrow_configured", False):
        return

    formatter = logging.Formatter(_LOG_FORMAT)
    context_filter = _JobContextFilter()

    # stderr, never stdout: stdout may carry protocol data for stdio MCP servers.
    console = logging.StreamHandler(sys.stderr)
    handlers: list[logging.Handler] = [console]

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingFileHandler(log_dir / f"{service}.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        )

    for handler in handlers:
        handler.setFormatter(formatter)
        handler.addFilter(context_filter)
        root.addHandler(handler)

    root.setLevel(level)
    for noisy in _NOISY_LOGGERS:
        logging.getLogger(noisy).setLevel(logging.WARNING)

    root._agentescrow_configured = True  # type: ignore[attr-defined]
    logging.getLogger(__name__).info("Logging configured: service=%s level=%s", service, level)
