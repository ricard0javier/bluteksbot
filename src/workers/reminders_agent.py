"""Reminders worker — sets and lists timed reminders stored in MongoDB."""
import logging
from typing import Any

import telebot

from src import config
from src.agent.models import AgentResult
from src.llms import client as llm
from src.llms.prompts import REMINDERS_AGENT_SYSTEM

logger = logging.getLogger(__name__)


def run(task: str, message: telebot.types.Message, raw: dict[str, Any]) -> AgentResult:
    try:
        messages = [
            {"role": "system", "content": REMINDERS_AGENT_SYSTEM},
            {"role": "user", "content": task},
        ]
        reply = llm.chat(messages, model=config.LITELLM_WORKER_MODEL)
        return AgentResult(agent="reminders_agent", success=True, reply=reply)
    except Exception:
        logger.error("reminders_agent failed.", exc_info=True)
        return AgentResult(agent="reminders_agent", success=False, reply="Reminder operation failed.")
