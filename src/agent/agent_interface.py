"""Telegram producer — routes Telegram messages through the Deep Agent with streaming progress."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from langgraph.graph.state import CompiledStateGraph

from src.persistence import task_store
from src.persistence.models import TaskStatus, TaskStep

logger = logging.getLogger(__name__)

_THINKING_EMOJI = "\u23f3"  # ⏳


def stream_agent_updates(
    agent: CompiledStateGraph,
    task_id: str,
    thread_id: str,
    user_text: str,
    user_content: str | list | None = None,
    progress_update_callback: Callable[[str], None] = None,
) -> str:
    """Stream agent execution, edit status message on each step, return final reply."""
    steps: list[str] = []
    pending: dict[str, dict] = {}  # tool_call_id → buffered step data

    # Collect tool_call IDs already in the checkpoint so we don't re-label
    # historical tool calls that LangGraph may replay in the first stream chunk.
    prior_tc_ids: set[str] = _snapshot_tool_call_ids(agent, thread_id)

    content = user_content if user_content is not None else user_text
    for update in agent.stream(
        {"messages": [{"role": "user", "content": content}]},
        config={"configurable": {"thread_id": thread_id}},
        stream_mode="updates",
    ):
        if task_store.get_status(task_id) == TaskStatus.CANCELLED:
            raise InterruptedError("Task was cancelled.")

        tool_calls = [tc for tc in _extract_tool_calls(update) if tc["id"] not in prior_tc_ids]
        tool_results = _extract_tool_results(update)

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

        label = _get_progress_label(tool_calls, tool_results)
        if label:
            steps.append(label)
            update_text = "\n".join(steps[-5:])
            task_store.append_progress(task_id, label)
            progress_update_callback(update_text)

    return _extract_final_reply(agent, thread_id)


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


def _get_progress_label(tool_calls: list[dict], tool_results: list[dict]) -> str | None:
    """Derive a short progress label from extracted call/result data."""
    if tool_calls:
        names = ", ".join(tc["name"] for tc in tool_calls)
        return f"{_THINKING_EMOJI} Using: `{names}`"
    if tool_results:
        return f"{_THINKING_EMOJI} Processing results..."
    return None


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
