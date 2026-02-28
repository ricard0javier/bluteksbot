"""Code worker — generates and optionally executes code in a sandboxed subprocess."""
import logging
from typing import Any

import telebot

from src import config
from src.agent.models import AgentResult
from src.llms import client as llm
from src.llms.prompts import CODE_AGENT_SYSTEM
from src.tools.code_executor import execute_python

logger = logging.getLogger(__name__)

_EXEC_TRIGGER_WORDS = ("run", "execute", "output", "result")


def run(task: str, message: telebot.types.Message, raw: dict[str, Any]) -> AgentResult:
    try:
        messages = [
            {"role": "system", "content": CODE_AGENT_SYSTEM},
            {"role": "user", "content": task},
        ]
        llm_reply = llm.chat(messages, model=config.LITELLM_WORKER_MODEL)

        if any(w in task.lower() for w in _EXEC_TRIGGER_WORDS):
            code_block = _extract_code_block(llm_reply)
            if code_block:
                output = execute_python(code_block)
                llm_reply += f"\n\n**Output:**\n```\n{output}\n```"

        return AgentResult(agent="code_agent", success=True, reply=llm_reply)
    except Exception:
        logger.error("code_agent failed.", exc_info=True)
        return AgentResult(agent="code_agent", success=False, reply="Code execution failed.")


def _extract_code_block(text: str) -> str | None:
    """Naive extraction of the first ```python ... ``` block."""
    import re
    match = re.search(r"```python\n(.*?)```", text, re.DOTALL)
    return match.group(1).strip() if match else None
