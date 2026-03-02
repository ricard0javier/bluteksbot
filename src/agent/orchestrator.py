"""Orchestrator — routes Telegram messages through the Deep Agent with streaming progress."""

import logging
from datetime import datetime, timezone
from typing import Any

import telebot

from src.agent.deep_agent import build_agent
from src.persistence import event_store, job_store, task_store
from src.persistence.models import BotTask, Event, EventAggregate, JobStatus, TaskStatus

logger = logging.getLogger(__name__)

_THINKING_EMOJI = "\u23f3"  # ⏳
_DONE_EMOJI = "\u2705"      # ✅


def _send_safe(bot, chat_id: int, text: str) -> None:
    """Send with Markdown; fall back to plain text if Telegram rejects the entities."""
    try:
        bot.send_message(chat_id, text, parse_mode="Markdown")
    except Exception:
        bot.send_message(chat_id, text)


class Orchestrator:
    def __init__(self, bot: telebot.TeleBot) -> None:
        self._bot = bot
        self._agent = build_agent()

    def run_task(self, task_id: str, status_msg_id: int, raw: dict[str, Any]) -> None:
        """Execute in a background thread: streams agent output, sends progress updates."""
        chat_id = raw["chat_id"]
        user_text = raw.get("text", "") or "[non-text message]"

        task_store.update_status(task_id, TaskStatus.RUNNING)

        try:
            reply = self._stream_with_progress(
                task_id=task_id,
                status_msg_id=status_msg_id,
                chat_id=chat_id,
                user_text=user_text,
            )
            _send_safe(self._bot, chat_id, reply)
            task_store.update_status(task_id, TaskStatus.DONE, result=reply[:500])
            self._store_event(raw, reply)
        except Exception as exc:
            logger.error("Task %s failed (chat=%s).", task_id, chat_id, exc_info=True)
            task_store.update_status(task_id, TaskStatus.FAILED, error=str(exc))
            try:
                self._bot.send_message(chat_id, "Sorry, something went wrong. Please try again.")
            except Exception:
                logger.warning("Failed to send error message to chat=%s.", chat_id)
        finally:
            try:
                self._bot.delete_message(chat_id, status_msg_id)
            except Exception:
                pass

    def run_autonomous(
        self,
        task_prompt: str,
        chat_id: int,
        job_id: str,
        job_name: str,
        execution_id: str,
    ) -> None:
        """Execute a scheduled job autonomously: no streaming, single result notification.

        Sends one Telegram message on completion (success or unrecoverable error).
        All state is persisted to MongoDB via task_store and job_store.
        """
        now = datetime.now(timezone.utc)
        task = BotTask(
            causation_id=f"cron-{job_id}-{now.isoformat()}",
            chat_id=chat_id,
            input=task_prompt,
        )
        task_id = task_store.create(task)
        task_store.update_status(task_id, TaskStatus.RUNNING)
        job_store.update_execution(
            execution_id, JobStatus.RUNNING, task_id=task_id, started_at=now
        )

        thread_id = f"cron-{job_id}"  # isolated LangGraph context per job
        try:
            for _ in self._agent.stream(
                {"messages": [{"role": "user", "content": task_prompt}]},
                config={"configurable": {"thread_id": thread_id}},
                stream_mode="updates",
            ):
                pass  # consume stream without streaming progress to Telegram

            reply = _extract_final_reply(self._agent, thread_id)
            self._bot.send_message(
                chat_id,
                f"\u2705 *Scheduled job '{job_name}' completed*",
                parse_mode="Markdown",
            )
            self._bot.send_message(chat_id, reply)
            task_store.update_status(task_id, TaskStatus.DONE, result=reply[:500])
            job_store.update_execution(
                execution_id,
                JobStatus.DONE,
                result=reply[:500],
                completed_at=datetime.now(timezone.utc),
            )
            logger.info("Autonomous job '%s' (%s) completed.", job_name, job_id)
        except Exception as exc:
            logger.error(
                "Autonomous job '%s' (%s) failed: %s", job_name, job_id, exc, exc_info=True
            )
            err_preview = str(exc)[:300]
            try:
                self._bot.send_message(
                    chat_id,
                    f"\u26a0\ufe0f *Scheduled job '{job_name}' failed*",
                    parse_mode="Markdown",
                )
                self._bot.send_message(chat_id, err_preview)
            except Exception:
                logger.warning("Could not send error notification to chat=%s.", chat_id)
            task_store.update_status(task_id, TaskStatus.FAILED, error=str(exc))
            job_store.update_execution(
                execution_id,
                JobStatus.FAILED,
                error=str(exc)[:500],
                completed_at=datetime.now(timezone.utc),
            )

    def _stream_with_progress(
        self,
        task_id: str,
        status_msg_id: int,
        chat_id: int,
        user_text: str,
    ) -> str:
        """Stream agent execution, edit status message on each step, return final reply."""
        steps: list[str] = []

        def _edit_status(text: str) -> None:
            try:
                self._bot.edit_message_text(text, chat_id, status_msg_id)
            except Exception:
                pass  # ignore "message not modified" races

        for chunk in self._agent.stream(
            {"messages": [{"role": "user", "content": user_text}]},
            config={"configurable": {"thread_id": str(chat_id)}},
            stream_mode="updates",
        ):
            step_label = _extract_step_label(chunk)
            if step_label:
                steps.append(step_label)
                task_store.append_progress(task_id, step_label)
                progress_text = _format_progress(steps)
                _edit_status(progress_text)

        return _extract_final_reply(self._agent, str(chat_id))

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


def _extract_step_label(chunk: dict) -> str | None:
    """Return a human-readable label for a stream chunk, or None to skip.

    Only inspects the LAST message in each node update to avoid re-labelling
    historical messages that reappear when the messages channel uses Overwrite.
    """
    for node_name, update in chunk.items():
        if node_name in ("__start__", "__end__"):
            continue
        raw = update.get("messages", []) if isinstance(update, dict) else []
        # LangGraph wraps overwrite-channel values in an Overwrite object; unwrap it.
        if not isinstance(raw, (list, tuple)):
            raw = getattr(raw, "value", []) or []
        if not raw:
            continue
        msg = raw[-1]  # only the newest message in this update
        tool_calls = getattr(msg, "tool_calls", None)
        if tool_calls:
            names = ", ".join(tc.get("name", "tool") for tc in tool_calls)
            return f"{_THINKING_EMOJI} Using: `{names}`"
        msg_type = getattr(msg, "type", None) or (msg.get("type") if isinstance(msg, dict) else None)
        if msg_type == "tool":
            return f"{_THINKING_EMOJI} Processing results..."
    return None


def _format_progress(steps: list[str]) -> str:
    recent = steps[-5:]  # show last 5 steps to stay within Telegram's message length
    return "\n".join(recent)


def _extract_final_reply(agent, thread_id: str) -> str:
    """Get the last assistant message from checkpoint state."""
    try:
        state = agent.get_state(config={"configurable": {"thread_id": thread_id}})
        messages = state.values.get("messages", [])
        for msg in reversed(messages):
            content = getattr(msg, "content", None)
            msg_type = getattr(msg, "type", None)
            if msg_type == "ai" and content:
                return str(content)
        return "Done — but no reply was generated."
    except Exception:
        logger.error("Failed to extract final reply.", exc_info=True)
        return "Sorry, I couldn't retrieve the response."
