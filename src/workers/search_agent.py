"""Web search worker — Tavily search + LLM synthesis."""
import logging
from typing import Any

import telebot

from src import config
from src.agent.models import AgentResult
from src.llms import client as llm
from src.llms.prompts import SEARCH_AGENT_SYSTEM
from src.tools.web_search import web_search

logger = logging.getLogger(__name__)


def run(task: str, message: telebot.types.Message, raw: dict[str, Any]) -> AgentResult:
    try:
        results = web_search(query=task, max_results=config.WEB_SEARCH_MAX_RESULTS)
        context = "\n\n".join(
            f"[{r['title']}]({r['url']})\n{r['content']}" for r in results
        )
        messages = [
            {"role": "system", "content": SEARCH_AGENT_SYSTEM},
            {"role": "user", "content": f"Query: {task}\n\nSearch results:\n{context}"},
        ]
        reply = llm.chat(messages, model=config.LITELLM_WORKER_MODEL)
        return AgentResult(agent="search_agent", success=True, reply=reply)
    except Exception:
        logger.error("search_agent failed.", exc_info=True)
        return AgentResult(agent="search_agent", success=False, reply="Search failed. Please try again.")
