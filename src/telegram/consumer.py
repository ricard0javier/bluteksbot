"""Telegram polling consumer — exponential backoff reconnect, idempotency gate, DLQ on error."""
import logging
import threading
import time
from uuid import uuid4

import telebot

from src import config
from src.persistence.dlq import send_to_dlq
from src.persistence.idempotency import is_already_processed

logger = logging.getLogger(__name__)


def _backoff_sleep(attempt: int) -> None:
    delay = min(
        config.BACKOFF_BASE_SECONDS * (config.BACKOFF_MULTIPLIER**attempt),
        config.BACKOFF_MAX_SECONDS,
    )
    logger.info("Backoff: retrying in %.1fs (attempt %d).", delay, attempt)
    time.sleep(delay)


class TelegramConsumer:
    def __init__(self, stop_event: threading.Event) -> None:
        self._stop = stop_event
        self._bot = telebot.TeleBot(
            config.TELEGRAM_BOT_TOKEN,
            threaded=False,
        )
        self._register_handlers()

    def _register_handlers(self) -> None:
        @self._bot.message_handler(func=lambda m: True, content_types=["text", "document", "photo"])
        def handle_message(message: telebot.types.Message) -> None:
            self._process(message)

    def _is_allowed(self, user_id: int) -> bool:
        if not config.TELEGRAM_ALLOWED_USER_IDS:
            return True
        return user_id in config.TELEGRAM_ALLOWED_USER_IDS

    def _process(self, message: telebot.types.Message) -> None:
        from src.agent.orchestrator import Orchestrator

        user_id = message.from_user.id if message.from_user else 0
        causation_id = f"tg-{message.chat.id}-{message.message_id}"

        if not self._is_allowed(user_id):
            logger.warning("Unauthorised user_id=%s — ignoring.", user_id)
            return

        if is_already_processed(causation_id):
            return

        raw = {
            "update_id": str(uuid4()),
            "chat_id": message.chat.id,
            "user_id": user_id,
            "message_id": message.message_id,
            "text": message.text or message.caption or "",
            "has_document": message.document is not None,
            "has_photo": message.photo is not None,
        }

        try:
            orchestrator = Orchestrator(bot=self._bot)
            orchestrator.handle(message=message, raw=raw)
        except Exception as exc:
            logger.error("Unrecoverable error processing message.", exc_info=True)
            send_to_dlq(original_message=raw, error=exc)

    def run(self) -> None:
        attempt = 0
        while not self._stop.is_set():
            try:
                logger.info("Starting Telegram polling.")
                self._bot.infinity_polling(
                    interval=config.TELEGRAM_POLLING_INTERVAL,
                    timeout=config.TELEGRAM_TIMEOUT,
                    long_polling_timeout=config.TELEGRAM_TIMEOUT,
                    skip_pending=True,
                    restart_on_change=False,
                )
            except Exception:
                logger.error("Telegram polling error.", exc_info=True)
                _backoff_sleep(attempt)
                attempt += 1
            else:
                attempt = 0
