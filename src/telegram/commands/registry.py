"""Command registry — maps slash commands to handlers with decorator registration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

import telebot

logger = logging.getLogger(__name__)

CommandHandler = Callable[[telebot.types.Message, telebot.TeleBot], None]


@dataclass(frozen=True)
class CommandInfo:
    command: str
    description: str
    handler: CommandHandler


class CommandRegistry:
    """Lightweight slash-command router.

    Usage::

        registry = CommandRegistry()

        @registry.register("/clean", "Clear thread and start fresh")
        def clean(message, bot): ...

        # In message pipeline:
        if registry.dispatch(message, bot):
            return  # handled, skip telegram producer
    """

    def __init__(self) -> None:
        self._commands: dict[str, CommandInfo] = {}

    def register(
        self, command: str, description: str
    ) -> Callable[[CommandHandler], CommandHandler]:
        """Decorator factory — registers a command handler."""

        def decorator(fn: CommandHandler) -> CommandHandler:
            key = command.lstrip("/").lower()
            self._commands[key] = CommandInfo(command=command, description=description, handler=fn)
            logger.debug("Registered command: %s", command)
            return fn

        return decorator

    def dispatch(self, message: telebot.types.Message, bot: telebot.TeleBot) -> bool:
        """Route message to a handler if it matches a registered command.

        Returns True if handled, False otherwise.
        """
        text = (message.text or "").strip()
        if not text.startswith("/"):
            return False

        # Extract command, strip bot mention (e.g. /clean@mybot → clean)
        raw_command = text.split()[0].lstrip("/").lower().split("@")[0]

        info = self._commands.get(raw_command)
        if info is None:
            return False

        try:
            info.handler(message, bot)
        except Exception:
            logger.exception("Error executing command /%s (chat=%s).", raw_command, message.chat.id)
            bot.send_message(message.chat.id, f"Failed to execute `/{raw_command}`. Check logs.")
        return True

    def list_commands(self) -> list[CommandInfo]:
        return list(self._commands.values())
