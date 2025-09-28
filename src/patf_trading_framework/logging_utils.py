"""Centralised logging utilities for PATF."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

from .configuration import LoggingConfig


def setup_logging(config: LoggingConfig, handlers: Iterable[logging.Handler]) -> None:
    """Initialise logging according to ``config`` using ``handlers``."""

    logging.basicConfig(
        level=getattr(logging, config.level.upper(), logging.INFO),
        format=config.fmt,
        datefmt=config.datefmt,
        handlers=list(handlers),
    )


def ensure_directory(path: Path) -> None:
    """Ensure the provided directory exists."""

    path.mkdir(parents=True, exist_ok=True)
