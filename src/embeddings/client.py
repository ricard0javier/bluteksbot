"""Embedding facade — delegates to the LiteLLM proxy via the OpenAI-compatible client."""
import logging

from src.llms import client as llm

logger = logging.getLogger(__name__)


def embed(text: str) -> list[float]:
    """Returns normalised embedding vector for the given text."""
    vector = llm.embed(text)
    logger.debug("Embedding generated (%d dims).", len(vector))
    return vector


def embed_batch(texts: list[str]) -> list[list[float]]:
    return [embed(t) for t in texts]
