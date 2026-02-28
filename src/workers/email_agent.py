"""Email worker — drafts and sends emails via SMTP after LLM confirmation."""
import logging
from typing import Any

import telebot

from src import config
from src.agent.models import AgentResult
from src.llms import client as llm
from src.llms.prompts import EMAIL_AGENT_SYSTEM
from src.tools.email_sender import send_email

logger = logging.getLogger(__name__)


def run(task: str, message: telebot.types.Message, raw: dict[str, Any]) -> AgentResult:
    try:
        messages = [
            {"role": "system", "content": EMAIL_AGENT_SYSTEM},
            {"role": "user", "content": task},
        ]
        reply = llm.chat(messages, model=config.LITELLM_WORKER_MODEL)
        return AgentResult(agent="email_agent", success=True, reply=reply)
    except Exception:
        logger.error("email_agent failed.", exc_info=True)
        return AgentResult(agent="email_agent", success=False, reply="Email operation failed.")
