"""Telegram producer — routes Telegram messages through the Deep Agent with streaming progress."""

import logging
from datetime import UTC, datetime
from typing import Any

import telebot
from langgraph.graph.state import CompiledStateGraph

from src.persistence import event_store, job_store, task_store
from src.persistence.models import BotTask, Event, EventAggregate, JobStatus, TaskStatus, TaskStep

_CANCELLED_MSG = "Task was cancelled."

logger = logging.getLogger(__name__)

_THINKING_EMOJI = "\u23f3"  # ⏳
_DONE_EMOJI = "\u2705"  # ✅


def _send_safe(bot, chat_id: int, text: str) -> None:
    """Send with Markdown; fall back to plain text if Telegram rejects the entities."""
    try:
        bot.send_message(chat_id, text, parse_mode="Markdown")
    except Exception:
        bot.send_message(chat_id, text)


class TelegramProducer:
    def __init__(self, bot: telebot.TeleBot, agent: CompiledStateGraph) -> None:
        self._bot = bot
        self._agent = agent

    def run_task(self, task_id: str, status_msg_id: int, raw: dict[str, Any]) -> None:
        """Execute in a background thread: streams agent output, sends progress updates."""
        chat_id = raw["chat_id"]
        user_text = raw.get("text", "") or "[non-text message]"
        user_content = _build_message_content(raw)

        task_store.update_status(task_id, TaskStatus.RUNNING)

        try:
            reply = self._stream_with_progress(
                task_id=task_id,
                status_msg_id=status_msg_id,
                chat_id=chat_id,
                user_text=user_text,
                user_content=user_content,
            )
            _send_safe(self._bot, chat_id, reply)
            task_store.update_status(task_id, TaskStatus.DONE, result=reply[:500])
            self._store_event(raw, reply)
        except InterruptedError:
            logger.info("Task %s cancelled (chat=%s).", task_id, chat_id)
            try:
                self._bot.send_message(chat_id, "Task was cancelled.")
            except Exception:
                pass
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
        now = datetime.now(UTC)
        task = BotTask(
            causation_id=f"cron-{job_id}-{now.isoformat()}",
            chat_id=chat_id,
            input=task_prompt,
        )
        task_id = task_store.create(task)
        task_store.update_status(task_id, TaskStatus.RUNNING)
        job_store.update_execution(execution_id, JobStatus.RUNNING, task_id=task_id, started_at=now)

        thread_id = f"cron-{job_id}"  # isolated LangGraph context per job
        try:
            pending: dict[str, dict] = {}
            for chunk in self._agent.stream(
                {"messages": [{"role": "user", "content": task_prompt}]},
                config={"configurable": {"thread_id": thread_id}},
                stream_mode="updates",
            ):
                if task_store.get_status(task_id) == TaskStatus.CANCELLED:
                    raise InterruptedError(_CANCELLED_MSG)

                for tc in _extract_tool_calls(chunk):
                    pending[tc["id"]] = {
                        "tool": tc["name"],
                        "node": tc["node"],
                        "args_preview": tc["args_preview"],
                        "started_at": datetime.now(UTC),
                    }
                for tr in _extract_tool_results(chunk):
                    buffered = pending.pop(tr["tool_call_id"], None)
                    if buffered:
                        duration_ms = int(
                            (datetime.now(UTC) - buffered["started_at"]).total_seconds() * 1000
                        )
                        task_store.append_step(
                            task_id,
                            TaskStep(
                                tool=buffered["tool"],
                                node=buffered["node"],
                                args_preview=buffered["args_preview"],
                                output_preview=tr["output_preview"],
                                started_at=buffered["started_at"],
                                duration_ms=duration_ms,
                            ),
                        )

            reply = _extract_final_reply(self._agent, thread_id)
            self._bot.send_message(
                chat_id,
                f"[Scheduled job '{job_name}' completed]",
                parse_mode=None,  # Plain text
            )
            self._bot.send_message(chat_id, reply, parse_mode=None)
            task_store.update_status(task_id, TaskStatus.DONE, result=reply[:500])
            job_store.update_execution(
                execution_id,
                JobStatus.DONE,
                result=reply[:500],
                completed_at=datetime.now(UTC),
            )
            logger.info("Autonomous job '%s' (%s) completed.", job_name, job_id)
        except InterruptedError:
            logger.info("Autonomous job '%s' (%s) cancelled.", job_name, job_id)
            job_store.update_execution(
                execution_id,
                JobStatus.FAILED,
                error=_CANCELLED_MSG,
                completed_at=datetime.now(UTC),
            )
        except Exception as exc:
            logger.error(
                "Autonomous job '%s' (%s) failed: %s", job_name, job_id, exc, exc_info=True
            )
            err_preview = str(exc)[:300]
            try:
                self._bot.send_message(
                    chat_id,
                    f"\u26a0\ufe0f *Scheduled job '{job_name}' failed*",
                    parse_mode=None,  # Plain text
                )
                self._bot.send_message(chat_id, err_preview)
            except Exception:
                logger.warning("Could not send error notification to chat=%s.", chat_id)
            task_store.update_status(task_id, TaskStatus.FAILED, error=str(exc))
            job_store.update_execution(
                execution_id,
                JobStatus.FAILED,
                error=str(exc)[:500],
                completed_at=datetime.now(UTC),
            )

    def _stream_with_progress(
        self,
        task_id: str,
        status_msg_id: int,
        chat_id: int,
        user_text: str,
        user_content: str | list | None = None,
    ) -> str:
        """Stream agent execution, edit status message on each step, return final reply."""
        tg_steps: list[str] = []
        pending: dict[str, dict] = {}  # tool_call_id → buffered step data

        # Collect tool_call IDs already in the checkpoint so we don't re-label
        # historical tool calls that LangGraph may replay in the first stream chunk.
        prior_tc_ids: set[str] = _snapshot_tool_call_ids(self._agent, str(chat_id))

        def _edit_status(text: str) -> None:
            try:
                self._bot.edit_message_text(text, chat_id, status_msg_id)
            except Exception:
                pass  # ignore "message not modified" races

        content = user_content if user_content is not None else user_text
        for chunk in self._agent.stream(
            {"messages": [{"role": "user", "content": content}]},
            config={"configurable": {"thread_id": str(chat_id)}},
            stream_mode="updates",
        ):
            if task_store.get_status(task_id) == TaskStatus.CANCELLED:
                raise InterruptedError(_CANCELLED_MSG)

            tool_calls = [tc for tc in _extract_tool_calls(chunk) if tc["id"] not in prior_tc_ids]
            tool_results = _extract_tool_results(chunk)

            for tc in tool_calls:
                prior_tc_ids.add(tc["id"])  # deduplicate within the same stream
                pending[tc["id"]] = {
                    "tool": tc["name"],
                    "node": tc["node"],
                    "args_preview": tc["args_preview"],
                    "started_at": datetime.now(UTC),
                }

            for tr in tool_results:
                buffered = pending.pop(tr["tool_call_id"], None)
                if buffered:
                    duration_ms = int(
                        (datetime.now(UTC) - buffered["started_at"]).total_seconds() * 1000
                    )
                    task_store.append_step(
                        task_id,
                        TaskStep(
                            tool=buffered["tool"],
                            node=buffered["node"],
                            args_preview=buffered["args_preview"],
                            output_preview=tr["output_preview"],
                            started_at=buffered["started_at"],
                            duration_ms=duration_ms,
                        ),
                    )

            label = _telegram_label(tool_calls, tool_results)
            if label:
                tg_steps.append(label)
                task_store.append_progress(task_id, label)
                _edit_status(_format_progress(tg_steps))

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


def _iter_messages(chunk: dict):
    """Yield (node_name, message) pairs from a LangGraph stream chunk."""
    for node_name, update in chunk.items():
        if node_name in ("__start__", "__end__"):
            continue
        raw = update.get("messages", []) if isinstance(update, dict) else []
        if not isinstance(raw, (list, tuple)):
            raw = getattr(raw, "value", []) or []
        for msg in raw:
            yield node_name, msg


def _extract_tool_calls(chunk: dict) -> list[dict]:
    """Return one entry per tool call invoked in this chunk: {id, name, args_preview, node}."""
    results = []
    for node_name, msg in _iter_messages(chunk):
        for tc in getattr(msg, "tool_calls", None) or []:
            args = tc.get("args", {})
            args_str = ", ".join(f"{k}={repr(v)[:80]}" for k, v in args.items()) if args else ""
            results.append({
                "id": tc.get("id", ""),
                "name": tc.get("name", "tool"),
                "args_preview": args_str[:300] or None,
                "node": node_name,
            })
    return results


def _extract_tool_results(chunk: dict) -> list[dict]:
    """Return one entry per tool result in this chunk: {tool_call_id, output_preview}."""
    results = []
    for _node, msg in _iter_messages(chunk):
        msg_type = getattr(msg, "type", None) or (
            msg.get("type") if isinstance(msg, dict) else None
        )
        if msg_type == "tool":
            call_id = getattr(msg, "tool_call_id", None) or (
                msg.get("tool_call_id") if isinstance(msg, dict) else None
            )
            content = getattr(msg, "content", None) or (
                msg.get("content") if isinstance(msg, dict) else None
            )
            results.append({
                "tool_call_id": call_id or "",
                "output_preview": str(content)[:400] if content else None,
            })
    return results


def _telegram_label(tool_calls: list[dict], tool_results: list[dict]) -> str | None:
    """Derive a short Telegram progress string from extracted call/result data."""
    if tool_calls:
        names = ", ".join(tc["name"] for tc in tool_calls)
        return f"{_THINKING_EMOJI} Using: `{names}`"
    if tool_results:
        return f"{_THINKING_EMOJI} Processing results..."
    return None


def _format_progress(steps: list[str]) -> str:
    recent = steps[-5:]  # show last 5 steps to stay within Telegram's message length
    return "\n".join(recent)


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


def _snapshot_tool_call_ids(agent, thread_id: str) -> set[str]:
    """Return all tool_call IDs already present in the checkpoint for this thread."""
    try:
        state = agent.get_state(config={"configurable": {"thread_id": thread_id}})
        ids: set[str] = set()
        for msg in state.values.get("messages", []):
            for tc in getattr(msg, "tool_calls", None) or []:
                ids.add(tc.get("id", ""))
        return ids
    except Exception:
        return set()


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
