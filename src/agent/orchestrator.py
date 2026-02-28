"""Orchestrator — classifies user intent and delegates to the appropriate worker agent."""
import json
import logging
from typing import Any

import telebot

from src import config
from src.agent.models import AgentResult, OrchestratorDecision
from src.embeddings.client import embed
from src.llms import client as llm
from src.llms.prompts import ORCHESTRATOR_SYSTEM
from src.persistence import event_store
from src.persistence.memory_store import save_memory, search_memory
from src.persistence.models import Event, EventAggregate

logger = logging.getLogger(__name__)

_AGENT_REGISTRY: dict[str, str] = {
    "search_agent": "src.workers.search_agent",
    "files_agent": "src.workers.files_agent",
    "code_agent": "src.workers.code_agent",
    "calendar_agent": "src.workers.calendar_agent",
    "email_agent": "src.workers.email_agent",
    "reminders_agent": "src.workers.reminders_agent",
    "chat_agent": "src.workers.chat_agent",
}


class Orchestrator:
    def __init__(self, bot: telebot.TeleBot) -> None:
        self._bot = bot

    def handle(self, message: telebot.types.Message, raw: dict[str, Any]) -> None:
        user_id = raw["user_id"]
        chat_id = raw["chat_id"]
        user_text = raw.get("text", "")

        memory_context = self._recall(user_id, user_text)
        decision = self._classify(user_text, memory_context)

        result = self._dispatch(decision, message, raw)

        self._reply(chat_id, result.reply)
        self._remember(user_id, user_text, result.reply)
        self._store_event(raw, decision, result)

    def _recall(self, user_id: int, query: str) -> str:
        if not query:
            return ""
        try:
            query_vec = embed(query)
            memories = search_memory(user_id=user_id, query_embedding=query_vec)
            return "\n".join(m["content"] for m in memories)
        except Exception:
            logger.warning("Memory recall failed.", exc_info=True)
            return ""

    def _classify(self, user_text: str, memory_context: str) -> OrchestratorDecision:
        system = ORCHESTRATOR_SYSTEM
        if memory_context:
            system += f"\n\nRelevant memory:\n{memory_context}"

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_text or "[non-text message]"},
        ]
        raw_json = ""
        try:
            raw_json = llm.chat(messages, model=config.LITELLM_ORCHESTRATOR_MODEL)
            # Strip markdown code fences some models add around JSON
            cleaned = raw_json.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            data = json.loads(cleaned)
            return OrchestratorDecision(**data)
        except Exception:
            logger.warning("Orchestrator classification failed (raw=%r) — defaulting to chat_agent.", raw_json, exc_info=True)
            return OrchestratorDecision(agent="chat_agent", task=user_text)

    def _dispatch(
        self,
        decision: OrchestratorDecision,
        message: telebot.types.Message,
        raw: dict[str, Any],
    ) -> AgentResult:
        import importlib

        module_path = _AGENT_REGISTRY.get(decision.agent, _AGENT_REGISTRY["chat_agent"])
        try:
            module = importlib.import_module(module_path)
            return module.run(task=decision.task, message=message, raw=raw)
        except Exception as exc:
            logger.error("Worker agent '%s' failed.", decision.agent, exc_info=True)
            return AgentResult(agent=decision.agent, success=False, reply="Sorry, something went wrong. Please try again.")

    def _reply(self, chat_id: int, text: str) -> None:
        self._bot.send_message(chat_id, text, parse_mode="Markdown")

    def _remember(self, user_id: int, user_text: str, reply: str) -> None:
        try:
            combined = f"User: {user_text}\nBot: {reply}"
            vector = embed(combined)
            save_memory(user_id=user_id, content=combined, embedding=vector)
        except Exception:
            logger.warning("Memory save failed.", exc_info=True)

    def _store_event(
        self,
        raw: dict[str, Any],
        decision: OrchestratorDecision,
        result: AgentResult,
    ) -> None:
        try:
            event = Event(
                eventType="message.processed",
                aggregate=EventAggregate(type="conversation", id=str(raw["chat_id"])),
                payload={
                    "agent": decision.agent,
                    "task": decision.task,
                    "success": result.success,
                },
            )
            event_store.append(event)
        except Exception:
            logger.warning("Event store write failed.", exc_info=True)
