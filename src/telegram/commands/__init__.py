"""Telegram command registry — singleton ready for import."""

from .registry import CommandRegistry
from . import handlers as _handlers  # noqa: F401 — registers commands as side-effect

registry = CommandRegistry()
_handlers.register_all(registry)

__all__ = ["registry"]
