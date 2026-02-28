"""Calendar worker — manages events via LLM + APScheduler persistence."""
import logging
from typing import Any

import telebot

from src import config
from src.agent.models import AgentResult
from src.llms import client as llm
from src.llms.prompts import CALENDAR_AGENT_SYSTEM

logger = logging.getLogger(__name__)


def run(task: str, message: telebot.types.Message, raw: dict[str, Any]) -> AgentResult:
    try:
        messages = [
            {"role": "system", "content": CALENDAR_AGENT_SYSTEM},
            {"role": "user", "content": task},
        ]
        reply = llm.chat(messages, model=config.LITELLM_WORKER_MODEL)
        return AgentResult(agent="calendar_agent", success=True, reply=reply)
    except Exception:
        logger.error("calendar_agent failed.", exc_info=True)
        return AgentResult(agent="calendar_agent", success=False, reply="Calendar operation failed.")
