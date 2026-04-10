"""LiteLLM proxy client — uses OpenAI SDK against the OpenAI-compatible LiteLLM gateway.

The LiteLLM proxy exposes the standard /v1/chat/completions and /v1/embeddings endpoints,
so the OpenAI Python SDK is the canonical, lightweight way to call it.
"""

import logging
from functools import lru_cache

from openai import OpenAI
from openai.types.chat import ChatCompletion

from src import config

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _client() -> OpenAI:
    """Singleton OpenAI client pointed at the self-hosted LiteLLM proxy."""
    return OpenAI(
        api_key=config.OPENAI_API_BEARER_TOKEN,
        base_url=config.OPENAI_BASE_URL,
    )


def chat(
    messages: list[dict[str, str]],
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> str:
    """Returns the assistant message content as a string."""
    response: ChatCompletion = _client().chat.completions.create(
        model=model or config.ORCHESTRATOR_MODEL,
        messages=messages,  # type: ignore[arg-type]
        temperature=(temperature if temperature is not None else config.MODEL_TEMPERATURE),
        max_tokens=max_tokens or config.MODEL_MAX_TOKENS,
    )
    content: str = response.choices[0].message.content or ""
    logger.debug("LLM response (%d chars).", len(content))
    return content


def embed(text: str) -> list[float]:
    """Returns an embedding vector for a single text input."""
    response = _client().embeddings.create(
        model=config.EMBEDDING_MODEL,
        input=text,
    )
    return response.data[0].embedding
