"""Telegram polling consumer — exponential backoff reconnect, idempotency gate, DLQ on error."""

import base64
import io
import logging
import os
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
from src.telegram.producer import TelegramProducer
from src.telegram.state import set_bot

logger = logging.getLogger(__name__)

_ALL_CONTENT_TYPES = [
    "text",
    "photo",
    "document",
    "voice",
    "audio",
    "video",
    "video_note",
    "animation",
    "sticker",
    "location",
    "contact",
]


def _backoff_sleep(attempt: int) -> None:
    delay = min(
        config.BACKOFF_BASE_SECONDS * (config.BACKOFF_MULTIPLIER**attempt),
        config.BACKOFF_MAX_SECONDS,
    )
    logger.info("Backoff: retrying in %.1fs (attempt %d).", delay, attempt)
    time.sleep(delay)


def _download_file(bot: telebot.TeleBot, file_id: str) -> bytes | None:
    """Download a Telegram file by file_id; returns None if too large or on error."""
    try:
        file_info = bot.get_file(file_id)
        size_bytes = getattr(file_info, "file_size", 0) or 0
        max_bytes = config.TELEGRAM_MAX_FILE_SIZE_MB * 1024 * 1024
        if size_bytes > max_bytes:
            logger.warning(
                "File %s is %.1f MB — skipping download.",
                file_id,
                size_bytes / 1024 / 1024,
            )
            return None
        return bot.download_file(file_info.file_path)
    except Exception:
        logger.warning("Failed to download file_id=%s.", file_id, exc_info=True)
        return None


def _save_to_workspace(file_bytes: bytes, filename: str, chat_id: int) -> str | None:
    """Persist uploaded bytes into the agent workspace; return the workspace-relative path."""
    try:
        upload_dir = os.path.join(config.DEEP_AGENT_WORKSPACE, "workspace", "uploads", str(chat_id))
        os.makedirs(upload_dir, exist_ok=True)
        filepath = os.path.join(upload_dir, filename)
        with open(filepath, "wb") as fh:
            fh.write(file_bytes)
        # Return the virtual path the agent's filesystem tools understand
        return f"{config.DEEP_AGENT_WORKSPACE}/uploads/{chat_id}/{filename}"
    except Exception:
        logger.warning("Failed to save uploaded file to workspace.", exc_info=True)
        return None


def _transcribe_audio(audio_bytes: bytes, filename: str = "voice.ogg") -> str | None:
    """Transcribe audio via the Whisper API (routed through LiteLLM)."""
    try:
        from openai import OpenAI

        client = OpenAI(
            base_url=config.OPENAI_BASE_URL,
            api_key=config.OPENAI_API_BEARER_TOKEN,
        )
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = filename
        resp = client.audio.transcriptions.create(
            model=config.WHISPER_MODEL,
            file=audio_file,
        )
        return resp.text or None
    except Exception:
        logger.warning("Voice transcription failed.", exc_info=True)
        return None


def _build_agent_input(message: telebot.types.Message, bot: telebot.TeleBot) -> dict:
    """Extract structured content from any Telegram message type.

    Returns a dict with:
        text          — human-readable text for the agent
        media_content — list of media attachments [{type, bytes_b64, mime_type, name}]
        has_document  — legacy flag
        has_photo     — legacy flag
    """
    text: str = message.text or message.caption or ""
    media_content: list[dict] = []

    # ── Voice / Audio → transcribe ────────────────────────────────────────────
    voice_obj = message.voice or message.audio
    if voice_obj:
        audio_bytes = _download_file(bot, voice_obj.file_id)
        if audio_bytes:
            transcript = _transcribe_audio(audio_bytes, filename="audio.ogg")
            if transcript:
                text = f"[Voice message transcribed]: {transcript}"
            else:
                duration = getattr(voice_obj, "duration", 0)
                text = f"[Voice message: {duration}s — transcription unavailable]"
        else:
            text = "[Voice message — could not download]"

    # ── Photo → base64 image block ────────────────────────────────────────────
    elif message.photo:
        largest = max(message.photo, key=lambda p: p.file_size or 0)
        img_bytes = _download_file(bot, largest.file_id)
        if img_bytes:
            media_content.append({
                "type": "image",
                "mime_type": "image/jpeg",
                "bytes_b64": base64.b64encode(img_bytes).decode(),
                "name": "photo.jpg",
            })
        if not text:
            text = "[Photo]"

    # ── Document ──────────────────────────────────────────────────────────────
    elif message.document:
        doc = message.document
        doc_bytes = _download_file(bot, doc.file_id)
        if doc_bytes:
            filename = doc.file_name or "document"
            workspace_path = _save_to_workspace(doc_bytes, filename, message.chat.id)
            if workspace_path:
                file_note = f"[File uploaded to workspace: {workspace_path}]"
            else:
                # Fallback: inline content for text files only
                mime = doc.mime_type or "application/octet-stream"
                try:
                    inline = doc_bytes.decode("utf-8")
                    file_note = f"[File: {filename}]\n{inline}"
                except Exception:
                    file_note = f"[File: {filename} ({mime}) — could not save or decode]"
            text = f"{text}\n{file_note}".strip() if text else file_note
        elif not text:
            text = f"[Document: {doc.file_name or 'file'} — download failed]"

    # ── Video / Video note ────────────────────────────────────────────────────
    elif message.video or message.video_note:
        vid = message.video or message.video_note
        duration = getattr(vid, "duration", 0)
        text = text or f"[Video: {duration}s]"

    # ── Animation (GIF) ───────────────────────────────────────────────────────
    elif message.animation:
        text = text or "[Animation/GIF]"

    # ── Sticker ───────────────────────────────────────────────────────────────
    elif message.sticker:
        sticker = message.sticker
        emoji = sticker.emoji or ""
        pack = getattr(sticker, "set_name", "") or ""
        text = f"[Sticker {emoji} from pack '{pack}']" if pack else f"[Sticker {emoji}]"

    # ── Location ──────────────────────────────────────────────────────────────
    elif message.location:
        loc = message.location
        text = f"[Location: latitude={loc.latitude}, longitude={loc.longitude}]"

    # ── Contact ───────────────────────────────────────────────────────────────
    elif message.contact:
        c = message.contact
        name = " ".join(filter(None, [c.first_name, c.last_name]))
        text = f"[Contact: {name}, phone={c.phone_number}]"

    return {
        "text": text,
        "media_content": media_content,
        "has_document": message.document is not None,
        "has_photo": message.photo is not None,
    }


class TelegramConsumer:
    def __init__(
        self,
        stop_event: threading.Event,
        bot: telebot.TeleBot | None = None,
        telegram_producer: TelegramProducer | None = None,
    ) -> None:
        self._stop = stop_event
        self._bot = bot or telebot.TeleBot(config.TELEGRAM_BOT_TOKEN, threaded=False)
        set_bot(self._bot)
        self._executor = ThreadPoolExecutor(
            max_workers=config.MAX_CONCURRENT_TASKS,
            thread_name_prefix="bot-task",
        )
        self._register_handlers()
        self._sync_command_menu()
        self._telegram_producer = telegram_producer
        if not config.TELEGRAM_ALLOWED_USER_IDS:
            logger.warning("No allowed user IDs configured — allowing all users.")

    def _sync_command_menu(self) -> None:
        """Register commands with Telegram so the native menu and autocomplete work."""
        from src.telegram.commands import registry

        commands = [
            telebot.types.BotCommand(info.command.lstrip("/"), info.description)
            for info in registry.list_commands()
        ]
        self._bot.set_my_commands(commands)
        logger.info("Telegram command menu synced (%d commands).", len(commands))

    def _register_handlers(self) -> None:
        @self._bot.message_handler(func=lambda m: True, content_types=_ALL_CONTENT_TYPES)
        def handle_message(message: telebot.types.Message) -> None:
            self._process(message)

        @self._bot.callback_query_handler(func=lambda call: call.data.startswith("cancel:"))
        def handle_cancel_callback(call: telebot.types.CallbackQuery) -> None:
            from src.persistence.models import TaskStatus
            from src.persistence.task_store import get_status, update_status

            task_id = call.data.split(":", 1)[1]
            current = get_status(task_id)

            if current not in (TaskStatus.RUNNING, TaskStatus.PENDING):
                self._bot.answer_callback_query(call.id, "Task is no longer active.")
                self._bot.edit_message_reply_markup(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    reply_markup=None,
                )
                return

            update_status(task_id, TaskStatus.CANCELLED)
            logger.info("Task %s cancelled by user (chat=%s).", task_id, call.message.chat.id)
            self._bot.answer_callback_query(call.id, "Task cancelled.")
            self._bot.edit_message_text(
                "Task cancelled. ✓",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
            )

        @self._bot.callback_query_handler(func=lambda call: call.data.startswith("model:"))
        def handle_model_callback(call: telebot.types.CallbackQuery) -> None:
            from src.persistence.preferences_store import get_model, set_model

            chat_id = call.message.chat.id
            chosen = call.data.split(":", 1)[1]
            current = get_model(chat_id)

            if chosen == current:
                self._bot.answer_callback_query(call.id, f"{chosen} is already active.")
                return

            set_model(chat_id, chosen)
            logger.info(
                "Model switched via button (chat=%s): %s → %s.",
                chat_id,
                current,
                chosen,
            )
            self._bot.answer_callback_query(call.id, f"Switched to {chosen} ✓")
            self._bot.edit_message_text(
                f"*Active model:* `{chosen}` ✓",
                chat_id=chat_id,
                message_id=call.message.message_id,
                parse_mode="Markdown",
            )

    def _is_allowed(self, user_id: int) -> bool:
        if not config.TELEGRAM_ALLOWED_USER_IDS:
            return True
        return user_id in config.TELEGRAM_ALLOWED_USER_IDS

    def _process(self, message: telebot.types.Message) -> None:
        from src.telegram.commands import registry

        user_id = message.from_user.id if message.from_user else 0
        causation_id = f"tg-{message.chat.id}-{message.message_id}"

        if not self._is_allowed(user_id):
            logger.warning("Unauthorised user_id=%s — ignoring.", user_id)
            return

        if message.text and message.text.startswith("/"):
            if registry.dispatch(message, self._bot):
                return

        if is_already_processed(causation_id):
            return

        media_input = _build_agent_input(message, self._bot)

        raw = {
            "update_id": str(uuid4()),
            "chat_id": message.chat.id,
            "user_id": user_id,
            "message_id": message.message_id,
            "text": media_input["text"],
            "media_content": media_input["media_content"],
            "has_document": media_input["has_document"],
            "has_photo": media_input["has_photo"],
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

            self._executor.submit(
                _run_task_safe, self._telegram_producer, task_id, status_msg_id, raw
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


def _run_task_safe(
    telegram_producer: TelegramProducer, task_id: str, status_msg_id: int, raw: dict
) -> None:
    """Top-level wrapper so ThreadPoolExecutor exceptions are logged (not silently swallowed)."""
    try:
        telegram_producer.run_task(task_id=task_id, status_msg_id=status_msg_id, raw=raw)
    except Exception:
        logger.error("Unhandled error in background task %s.", task_id, exc_info=True)
