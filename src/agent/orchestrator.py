"""Orchestrator — thin wrapper that routes Telegram messages through the Deep Agent."""

import logging
from typing import Any

import telebot

from src.agent.deep_agent import build_agent
from src.persistence import event_store
from src.persistence.models import Event, EventAggregate

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, bot: telebot.TeleBot) -> None:
        self._bot = bot
        self._agent = build_agent()

    def handle(self, message: telebot.types.Message, raw: dict[str, Any]) -> None:
        chat_id = raw["chat_id"]
        user_text = raw.get("text", "") or "[non-text message]"

        reply = self._invoke(user_text=user_text, chat_id=chat_id)
        self._reply(chat_id, reply)
        self._store_event(raw, reply)

    def _invoke(self, user_text: str, chat_id: int) -> str:
        """Run the deep agent for this chat thread and return the assistant reply."""
        try:
            result = self._agent.invoke(
                {"messages": [{"role": "user", "content": user_text}]},
                config={"configurable": {"thread_id": str(chat_id)}},
            )
            messages = result.get("messages", [])
            if messages:
                last = messages[-1]
                content = getattr(last, "content", None) or (
                    last.get("content") if isinstance(last, dict) else ""
                )
                if content:
                    return str(content)
            return "Sorry, I couldn't generate a response."
        except Exception:
            logger.error(
                "Deep agent invocation failed (chat_id=%s).", chat_id, exc_info=True
            )
            return "Sorry, something went wrong. Please try again."

    def _reply(self, chat_id: int, text: str) -> None:
        self._bot.send_message(chat_id, text, parse_mode="Markdown")

    def _store_event(self, raw: dict[str, Any], reply: str) -> None:
        try:
            event = Event(
                eventType="message.processed",
                aggregate=EventAggregate(type="conversation", id=str(raw["chat_id"])),
                payload={"reply_preview": reply[:200]},
            )
            event_store.append(event)
        except Exception:
            logger.warning("Event store write failed.", exc_info=True)
