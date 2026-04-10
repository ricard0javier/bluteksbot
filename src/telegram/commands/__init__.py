"""Telegram command registry — singleton ready for import."""

from . import handlers as _handlers  # noqa: F401 — registers commands as side-effect
from .registry import CommandRegistry

registry = CommandRegistry()
_handlers.register_all(registry)

__all__ = ["registry"]
