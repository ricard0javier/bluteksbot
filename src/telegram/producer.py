"""Telegram producer — routes Telegram messages through the Deep Agent with streaming progress."""

import contextlib
import logging
from typing import Any

import telebot
from langgraph.graph.state import CompiledStateGraph

from src.agent.agent_interface import stream_agent_updates
from src.persistence import event_store, task_store
from src.persistence.models import Event, EventAggregate, TaskStatus

_CANCELLED_MSG = "Task was cancelled."

logger = logging.getLogger(__name__)

_THINKING_EMOJI = "\u23f3"  # ⏳


class TelegramProducer:
    def __init__(self, bot: telebot.TeleBot, agent: CompiledStateGraph) -> None:
        self._bot = bot
        self._agent = agent

    def send_message(self, chat_id: str, text: str) -> None:
        self._bot.send_message(chat_id, text)

    def respond(
        self,
        task_id: str,
        chat_id: str,
        raw: dict[str, Any],
        status_message_text: str,
        thread_id: str | None = None,
    ) -> str:
        """Respond to a Telegram message with a streaming agent response."""
        user_text = raw.get("text", "") or "[non-text message]"
        user_content = _build_message_content(raw)

        # Update the task status to running
        task_store.update_status(task_id, TaskStatus.RUNNING)

        # Create a callback to update the status message
        status_msg = self._bot.send_message(chat_id, status_message_text)
        status_msg_id = status_msg.message_id

        def progress_update_callback(update_text: str):
            text = f"{status_message_text}\n{update_text}"
            try:
                return self._bot.edit_message_text(text, chat_id, status_msg_id)
            except Exception as exc:
                if not "message is not modified" in str(exc):
                    logger.warning(
                        "Failed to edit status message to chat=%s: %s.", chat_id, exc
                    )
                raise

        if thread_id is None:
            thread_id = chat_id

        # Stream the agent updates and send progress updates
        try:
            reply = stream_agent_updates(
                agent=self._agent,
                task_id=task_id,
                thread_id=thread_id,
                user_text=user_text,
                user_content=user_content,
                progress_update_callback=progress_update_callback,
            )
            # Send the final reply with Markdown; fall back to plain text if Telegram rejects the entities.
            try:
                self._bot.send_message(chat_id, reply, parse_mode="Markdown")
            except Exception:
                self._bot.send_message(chat_id, reply)

            # Update the task status to done and store the result and event
            task_store.update_status(task_id, TaskStatus.DONE, result=reply[:500])
            self._store_event(chat_id, reply)

            return reply
        except InterruptedError:
            # Update the task status to cancelled and send a cancelled message
            logger.info("Task %s cancelled (chat=%s).", task_id, chat_id)
            with contextlib.suppress(Exception):
                self._bot.send_message(chat_id, "Task was cancelled.")
        except Exception as exc:
            # Update the task status to failed and send an error message
            logger.error("Task %s failed (chat=%s).", task_id, chat_id, exc_info=True)
            task_store.update_status(task_id, TaskStatus.FAILED, error=str(exc))
            try:
                self._bot.send_message(
                    chat_id, "Sorry, something went wrong. Please try again."
                )
            except Exception:
                logger.warning("Failed to send error message to chat=%s.", chat_id)
        finally:
            # Delete the status message
            with contextlib.suppress(Exception):
                self._bot.delete_message(chat_id, status_msg_id)

    def _store_event(self, chat_id: str, reply: str) -> None:
        try:
            event = Event(
                eventType="message.processed",
                aggregate=EventAggregate(type="conversation", id=chat_id),
                payload={"reply_preview": reply[:200]},
            )
            event_store.append(event)
        except Exception:
            logger.warning("Event store write failed.", exc_info=True)


def _build_message_content(raw: dict) -> str | list:
    """Build LangChain message content from raw input.

    Returns a multimodal list when images are present, plain string otherwise.
    Documents are saved to the workspace by the consumer; text already contains
    the workspace path note.
    """
    text = raw.get("text", "") or "[non-text message]"
    media_content: list[dict] = raw.get("media_content", [])

    images = [m for m in media_content if m.get("type") == "image"]
    if not images:
        return text

    blocks: list[dict] = [{"type": "text", "text": text}]
    for img in images:
        data_url = f"data:{img['mime_type']};base64,{img['bytes_b64']}"
        blocks.append({"type": "image_url", "image_url": {"url": data_url}})
    return blocks
