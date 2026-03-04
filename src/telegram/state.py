"""Bot singleton registry — allows tools to access the shared TeleBot instance."""
from __future__ import annotations

from telebot import TeleBot

_bot: TeleBot | None = None


def set_bot(bot: TeleBot) -> None:
    global _bot
    _bot = bot


def get_bot() -> TeleBot:
    if _bot is None:
        raise RuntimeError("Bot not initialised — call set_bot() before using tools.")
    return _bot
