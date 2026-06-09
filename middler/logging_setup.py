"""Minimal, consistent logging setup.

stdlib logging only — a console handler plus an optional rotating file handler.
Call :func:`setup_logging` once at process start.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s | %(message)s"


def setup_logging(level: str | None = None, log_file: str | Path | None = None) -> None:
    """Configure root logging for the process.

    Args:
        level: Log level name (e.g. ``"INFO"``). Defaults to ``$LOG_LEVEL`` or
            ``"INFO"``.
        log_file: Optional path for a rotating file handler (5 MB × 3 backups).
    """
    resolved = (level or os.getenv("LOG_LEVEL") or "INFO").upper()
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(log_file, maxBytes=5_000_000, backupCount=3))
    logging.basicConfig(level=resolved, format=_FORMAT, handlers=handlers, force=True)
    # Third-party noise we never want at INFO.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger (thin convenience wrapper)."""
    return logging.getLogger(name)
