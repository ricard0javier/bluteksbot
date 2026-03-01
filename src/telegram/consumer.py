"""Telegram polling consumer — exponential backoff reconnect, idempotency gate, DLQ on error."""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import telebot

from src import config
from src.persistence.dlq import send_to_dlq
from src.persistence.idempotency import is_already_processed
from src.persistence.models import BotTask
from src.persistence.task_store import create as create_task

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
        self._executor = ThreadPoolExecutor(
            max_workers=config.MAX_CONCURRENT_TASKS,
            thread_name_prefix="bot-task",
        )
        self._register_handlers()
        if not config.TELEGRAM_ALLOWED_USER_IDS:
            logger.warning("No allowed user IDs configured — allowing all users.")

    def _register_handlers(self) -> None:
        @self._bot.message_handler(
            func=lambda m: True, content_types=["text", "document", "photo"]
        )
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

        task = BotTask(
            causation_id=causation_id,
            chat_id=message.chat.id,
            message_id=message.message_id,
            input=raw["text"] or "[non-text message]",
        )

        try:
            task_id = create_task(task)
            status_msg = self._bot.send_message(message.chat.id, "\u23f3 Working on it\u2026")
            status_msg_id = status_msg.message_id

            orchestrator = Orchestrator(bot=self._bot)
            self._executor.submit(
                _run_task_safe, orchestrator, task_id, status_msg_id, raw
            )
        except Exception as exc:
            logger.error("Failed to dispatch task (chat=%s).", message.chat.id, exc_info=True)
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

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


def _run_task_safe(orchestrator, task_id: str, status_msg_id: int, raw: dict) -> None:
    """Top-level wrapper so ThreadPoolExecutor exceptions are logged (not silently swallowed)."""
    try:
        orchestrator.run_task(task_id=task_id, status_msg_id=status_msg_id, raw=raw)
    except Exception:
        logger.error("Unhandled error in background task %s.", task_id, exc_info=True)
