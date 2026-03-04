"""Slash command handlers — registered onto the shared registry instance."""

from __future__ import annotations

import logging

import telebot

from src import config
from src.persistence.client import get_db
from src.persistence.preferences_store import get_model, set_model
from src.persistence.task_store import list_running, update_status
from src.persistence.models import TaskStatus

from .registry import CommandRegistry

logger = logging.getLogger(__name__)


def register_all(registry: CommandRegistry) -> None:
    """Register all command handlers onto *registry*."""

    @registry.register("/clean", "Clear conversation thread and start fresh")
    def clean_thread(message: telebot.types.Message, bot: telebot.TeleBot) -> None:
        chat_id = message.chat.id
        thread_id = str(chat_id)
        db = get_db()

        # LangGraph checkpoint state
        cp = db["checkpoints"].delete_many({"thread_id": thread_id}).deleted_count
        cw = db["checkpoint_writes"].delete_many({"thread_id": thread_id}).deleted_count

        # Summarization history stored under /conversation_history/<thread_id>/
        prefix = f"^/conversation_history/{thread_id}/"
        ch = db[config.MONGO_COLLECTION_CONV_HISTORY].delete_many(
            {"_id": {"$regex": prefix}}
        ).deleted_count

        logger.info(
            "Thread cleaned (chat=%s): checkpoints=%d, writes=%d, history=%d.",
            chat_id, cp, cw, ch,
        )
        bot.send_message(chat_id, "Thread cleared. Starting fresh! \U0001f9f9")

    @registry.register("/model", "View or switch the active LLM model")
    def switch_model(message: telebot.types.Message, bot: telebot.TeleBot) -> None:
        chat_id = message.chat.id
        parts = (message.text or "").strip().split(maxsplit=1)
        arg = parts[1].strip() if len(parts) > 1 else ""
        models = config.AVAILABLE_MODELS
        current = get_model(chat_id)

        if not arg:
            keyboard = telebot.types.InlineKeyboardMarkup()
            for m in models:
                label = f"{m} ✓" if m == current else m
                keyboard.add(telebot.types.InlineKeyboardButton(label, callback_data=f"model:{m}"))
            bot.send_message(
                chat_id,
                f"*Active model:* `{current}`\n\nSelect a model:",
                reply_markup=keyboard,
                parse_mode="Markdown",
            )
            return

        # Resolve by index or exact/partial name
        chosen: str | None = None
        if arg.isdigit():
            idx = int(arg) - 1
            if 0 <= idx < len(models):
                chosen = models[idx]
        else:
            matches = [m for m in models if arg.lower() in m.lower()]
            if len(matches) == 1:
                chosen = matches[0]
            elif len(matches) > 1:
                bot.send_message(chat_id, f"Ambiguous: {', '.join(f'`{m}`' for m in matches)}. Be more specific.", parse_mode="Markdown")
                return

        if chosen is None:
            bot.send_message(chat_id, f"Model `{arg}` not found. Use `/model` to list options.", parse_mode="Markdown")
            return

        set_model(chat_id, chosen)
        logger.info("Model switched (chat=%s): %s → %s.", chat_id, current, chosen)
        bot.send_message(chat_id, f"Model switched to `{chosen}`. ✓", parse_mode="Markdown")

    @registry.register("/cancel", "Cancel a running task")
    def cancel_task(message: telebot.types.Message, bot: telebot.TeleBot) -> None:
        chat_id = message.chat.id
        tasks = list_running(chat_id)

        if not tasks:
            bot.send_message(chat_id, "No running tasks to cancel.")
            return

        keyboard = telebot.types.InlineKeyboardMarkup()
        for t in tasks:
            label = (t["input"][:40] + "…") if len(t["input"]) > 40 else t["input"]
            keyboard.add(
                telebot.types.InlineKeyboardButton(
                    f"❌ {label}", callback_data=f"cancel:{t['id']}"
                )
            )
        bot.send_message(
            chat_id,
            "*Select a task to cancel:*",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )

    @registry.register("/commands", "List all available commands")
    def list_commands(message: telebot.types.Message, bot: telebot.TeleBot) -> None:
        lines = ["*Available commands:*", ""]
        for info in registry.list_commands():
            lines.append(f"`{info.command}` — {info.description}")
        bot.send_message(message.chat.id, "\n".join(lines), parse_mode="Markdown")
