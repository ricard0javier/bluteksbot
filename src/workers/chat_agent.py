"""General chat worker — handles open-ended conversation via LLM."""
import logging
from typing import Any

import telebot

from src import config
from src.agent.models import AgentResult
from src.llms import client as llm
from src.llms.prompts import CHAT_AGENT_SYSTEM

logger = logging.getLogger(__name__)


def run(task: str, message: telebot.types.Message, raw: dict[str, Any]) -> AgentResult:
    messages = [
        {"role": "system", "content": CHAT_AGENT_SYSTEM},
        {"role": "user", "content": task},
    ]
    try:
        reply = llm.chat(messages, model=config.LITELLM_WORKER_MODEL)
        return AgentResult(agent="chat_agent", success=True, reply=reply)
    except Exception as exc:
        logger.error("chat_agent failed.", exc_info=True)
        return AgentResult(agent="chat_agent", success=False, reply="I couldn't process that. Please try again.")
