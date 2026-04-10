"""Deep Agent factory — builds the LangGraph Deep Agent with MongoDB persistence and LangMem."""

import logging
import os
from functools import lru_cache

from src import config

logger = logging.getLogger(__name__)


def _configure_langsmith() -> None:
    """Set LangSmith env vars from config so the SDK picks them up automatically."""
    if config.LANGSMITH_TRACING.lower() == "true" and config.LANGSMITH_API_KEY:
        os.environ.setdefault("LANGSMITH_TRACING", "true")
        os.environ.setdefault("LANGSMITH_API_KEY", config.LANGSMITH_API_KEY)
        os.environ.setdefault("LANGSMITH_PROJECT", config.LANGSMITH_PROJECT)
        logger.info("LangSmith tracing enabled (project=%s).", config.LANGSMITH_PROJECT)


@lru_cache(maxsize=None)
def build_agent(
    model_name: str = "",
    include_telegram_tools: bool = True,
    include_schedule_tools: bool = True,
):
    """Build and cache a compiled Deep Agent graph per model.

    Args:
        model_name: LiteLLM model identifier. Defaults to ``config.LITELLM_WORKER_MODEL``.

    Returns a CompiledStateGraph that accepts:
        agent.invoke(
            {"messages": [{"role": "user", "content": "..."}]},
            config={"configurable": {"thread_id": "<chat_id>"}},
        )
    """
    model_name = model_name or config.LITELLM_WORKER_MODEL
    _configure_langsmith()

    from deepagents import create_deep_agent
    from deepagents.backends import CompositeBackend, FilesystemBackend
    from langchain.chat_models import init_chat_model
    from langchain_openai import OpenAIEmbeddings
    from langgraph.checkpoint.mongodb import MongoDBSaver
    from langgraph.store.mongodb import MongoDBStore, create_vector_index_config
    from langmem import create_manage_memory_tool, create_search_memory_tool

    from src.llms.prompts import ORCHESTRATOR_SYSTEM
    from src.persistence.client import get_client, get_db
    from src.persistence.mongodb_backend import MongoDBBackend
    from src.tools.agent_tools import AGENT_TOOLS
    from src.tools.schedule_tool import SCHEDULE_TOOLS
    from src.tools.telegram_tools import TELEGRAM_TOOLS
    from src.agent.LoggingMiddleware import LoggingMiddleware

    checkpointer = MongoDBSaver(
        client=get_client(),
        db_name=config.MONGO_DB,
    )

    embeddings = OpenAIEmbeddings(
        model=config.LITELLM_EMBEDDING_MODEL,
        base_url=config.LITELLM_BASE_URL,
        api_key=config.LITELLM_API_KEY,
    )

    index_config = create_vector_index_config(
        embed=embeddings,
        dims=config.EMBEDDING_DIMENSION,
        fields=["content"],
    )

    store = MongoDBStore(
        collection=get_db()[config.MONGO_COLLECTION_MEMORY],
        index_config=index_config,
    )

    # The built-in SummarizationMiddleware triggers at fraction(0.85) of max_input_tokens.
    # Setting max_input_tokens = SUMMARIZATION_TRIGGER_TOKENS / 0.85 makes the trigger exact.
    # When SUMMARIZATION_TRIGGER_TOKENS=0 the profile is omitted → trigger falls back to
    # 170 000 tokens, effectively disabling summarization.
    summarization_profile = (
        {"max_input_tokens": int(config.SUMMARIZATION_TRIGGER_TOKENS / 0.85)}
        if config.SUMMARIZATION_TRIGGER_TOKENS > 0
        else None
    )
    model = init_chat_model(
        model=model_name,
        model_provider="openai",
        base_url=config.LITELLM_BASE_URL,
        api_key=config.LITELLM_API_KEY,
        temperature=config.LITELLM_TEMPERATURE,
        max_tokens=config.LITELLM_MAX_TOKENS,
        profile=summarization_profile,
    )

    memory_namespace = tuple(p.strip() for p in config.LANGMEM_NAMESPACE.split(","))
    manage_memory = create_manage_memory_tool(namespace=memory_namespace)
    search_memory = create_search_memory_tool(namespace=memory_namespace)

    # CompositeBackend routes /conversation_history/ to MongoDB so the built-in
    # SummarizationMiddleware persists summaries there instead of the filesystem.
    fs_backend = FilesystemBackend(root_dir=config.DEEP_AGENT_WORKSPACE)
    conv_history_backend = MongoDBBackend(
        collection=get_db()[config.MONGO_COLLECTION_CONV_HISTORY],
    )
    backend = CompositeBackend(
        default=fs_backend,
        routes={"/conversation_history/": conv_history_backend},
    )

    if config.SUMMARIZATION_TRIGGER_TOKENS > 0:
        logger.info(
            "Summarization enabled: trigger≈%d tokens, store=%s.",
            config.SUMMARIZATION_TRIGGER_TOKENS,
            config.MONGO_COLLECTION_CONV_HISTORY,
        )
    else:
        logger.info("Summarization disabled (SUMMARIZATION_TRIGGER_TOKENS=0).")

    tools = [*AGENT_TOOLS]
    if include_schedule_tools:
        tools.extend(SCHEDULE_TOOLS)
    if include_telegram_tools:
        tools.extend(TELEGRAM_TOOLS)
    tools.extend([manage_memory, search_memory])

    agent = create_deep_agent(
        model=model,
        # TODO: implement dynamic tool loading
        # https://www.anthropic.com/engineering/advanced-tool-use
        # https://forum.langchain.com/t/are-dynamic-tool-lists-allowed-when-using-create-agent/1920/16
        # https://docs.langchain.com/oss/python/langchain/agents#runtime-tool-registration
        tools=tools,
        system_prompt=ORCHESTRATOR_SYSTEM,
        checkpointer=checkpointer,
        store=store,
        backend=backend,
        middleware=[LoggingMiddleware()],
    )

    logger.info("Deep Agent built (model=%s).", model_name)
    return agent
