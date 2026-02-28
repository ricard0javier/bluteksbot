"""LiteLLM proxy client — uses OpenAI SDK against the OpenAI-compatible LiteLLM gateway.

The LiteLLM proxy exposes the standard /v1/chat/completions and /v1/embeddings endpoints,
so the OpenAI Python SDK is the canonical, lightweight way to call it.
"""
import logging
from functools import lru_cache
from typing import Any

from openai import OpenAI
from openai.types.chat import ChatCompletion

from src import config

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _client() -> OpenAI:
    """Singleton OpenAI client pointed at the self-hosted LiteLLM proxy."""
    return OpenAI(
        api_key=config.LITELLM_API_KEY,
        base_url=f"{config.LITELLM_BASE_URL}/v1",
    )


def chat(
    messages: list[dict[str, str]],
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> str:
    """Returns the assistant message content as a string."""
    response: ChatCompletion = _client().chat.completions.create(
        model=model or config.LITELLM_ORCHESTRATOR_MODEL,
        messages=messages,  # type: ignore[arg-type]
        temperature=temperature if temperature is not None else config.LITELLM_TEMPERATURE,
        max_tokens=max_tokens or config.LITELLM_MAX_TOKENS,
    )
    content: str = response.choices[0].message.content or ""
    logger.debug("LLM response (%d chars).", len(content))
    return content


def embed(text: str) -> list[float]:
    """Returns an embedding vector for a single text input."""
    response = _client().embeddings.create(
        model=config.LITELLM_EMBEDDING_MODEL,
        input=text,
    )
    return response.data[0].embedding


def chat_with_tools(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    model: str | None = None,
) -> dict[str, Any]:
    """Tool-calling completion; returns the full message dict for the caller to dispatch."""
    response: ChatCompletion = _client().chat.completions.create(
        model=model or config.LITELLM_ORCHESTRATOR_MODEL,
        messages=messages,  # type: ignore[arg-type]
        tools=tools,  # type: ignore[arg-type]
        tool_choice="auto",
    )
    msg = response.choices[0].message
    return {
        "role": msg.role,
        "content": msg.content,
        "tool_calls": [tc.model_dump() for tc in (msg.tool_calls or [])],
    }
