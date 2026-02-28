"""File processing worker — downloads Telegram file, extracts text, and answers via LLM."""
import logging
from typing import Any

import telebot

from src import config
from src.agent.models import AgentResult
from src.files.processor import extract_text_from_telegram_file
from src.llms import client as llm
from src.llms.prompts import FILES_AGENT_SYSTEM

logger = logging.getLogger(__name__)


def run(task: str, message: telebot.types.Message, raw: dict[str, Any]) -> AgentResult:
    try:
        file_content = extract_text_from_telegram_file(message)
        if not file_content:
            return AgentResult(agent="files_agent", success=False, reply="No readable file found in this message.")

        messages = [
            {"role": "system", "content": FILES_AGENT_SYSTEM},
            {"role": "user", "content": f"Task: {task}\n\nDocument content:\n{file_content[:8000]}"},
        ]
        reply = llm.chat(messages, model=config.LITELLM_WORKER_MODEL)
        return AgentResult(agent="files_agent", success=True, reply=reply)
    except Exception:
        logger.error("files_agent failed.", exc_info=True)
        return AgentResult(agent="files_agent", success=False, reply="File processing failed. Please try again.")
