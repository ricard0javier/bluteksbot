"""Structured logging setup — stdout + file, level from config."""

import logging
from pathlib import Path

from src import config

_RESET = "\033[0m"
_LEVEL_COLORS = {
    logging.DEBUG: "\033[36m",  # cyan
    logging.INFO: "\033[32m",  # green
    logging.WARNING: "\033[33m",  # yellow
    logging.ERROR: "\033[31m",  # red
    logging.CRITICAL: "\033[1;31m",  # bold red
}


class _ColorFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        color = _LEVEL_COLORS.get(record.levelno, "")
        record = logging.makeLogRecord(record.__dict__)
        record.levelname = f"{color}{record.levelname}{_RESET}"
        record.msg = f"{color}{record.msg}{_RESET}"
        return super().format(record)


def setup_logging() -> None:
    log_dir = Path(config.LOG_FILE).parent
    log_dir.mkdir(parents=True, exist_ok=True)

    level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

    plain_fmt = logging.Formatter(fmt)

    console = logging.StreamHandler()
    console.setFormatter(_ColorFormatter(fmt) if config.ENVIRONMENT == "development" else plain_fmt)

    file_handler = logging.FileHandler(config.LOG_FILE)
    file_handler.setFormatter(plain_fmt)

    logging.basicConfig(level=level, handlers=[console, file_handler])
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
