"""Structured logging setup — stdout + file, level from config."""
import logging
import os
from pathlib import Path

from src import config


def setup_logging() -> None:
    log_dir = Path(config.LOG_FILE).parent
    log_dir.mkdir(parents=True, exist_ok=True)

    level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

    handlers: list[logging.Handler] = [
        logging.StreamHandler(),
        logging.FileHandler(config.LOG_FILE),
    ]

    logging.basicConfig(level=level, format=fmt, handlers=handlers)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
