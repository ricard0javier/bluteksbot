# Exposes a cached dictionary of models to be reused by the agent at runtime
from functools import lru_cache

import requests
from langchain.chat_models import BaseChatModel, init_chat_model

from src import config


@lru_cache(typed=True)
def get_chat_model(model_name: str) -> BaseChatModel:

    # The built-in SummarizationMiddleware triggers at fraction(0.85) of max_input_tokens.
    # Setting max_input_tokens = SUMMARIZATION_TRIGGER_TOKENS / 0.85 makes the trigger exact.
    # When SUMMARIZATION_TRIGGER_TOKENS=0 the profile is omitted → trigger falls back to
    # 170 000 tokens, effectively disabling summarization.
    summarization_profile = (
        {"max_input_tokens": int(config.SUMMARIZATION_TRIGGER_TOKENS / 0.85)}
        if config.SUMMARIZATION_TRIGGER_TOKENS > 0
        else None
    )
    return init_chat_model(
        model=model_name,
        model_provider="openai",
        base_url=config.OPENAI_BASE_URL,
        api_key=config.OPENAI_API_BEARER_TOKEN,
        temperature=config.MODEL_TEMPERATURE,
        max_tokens=config.MODEL_MAX_TOKENS,
        profile=summarization_profile,
    )


def get_available_models() -> list[str]:
    # returns a list of models that are available to the agent exposed by the OPENAI_BASE_URL
    response = requests.get(
        f"{config.OPENAI_BASE_URL}/models",
        headers={"Authorization": f"Bearer {config.OPENAI_API_BEARER_TOKEN}"},
    )
    return [model["id"] for model in response.json()["data"]]
