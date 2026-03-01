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


@lru_cache(maxsize=1)
def build_agent():
    """Build and cache the compiled Deep Agent graph.

    Returns a CompiledStateGraph that accepts:
        agent.invoke(
            {"messages": [{"role": "user", "content": "..."}]},
            config={"configurable": {"thread_id": "<chat_id>"}},
        )
    """
    _configure_langsmith()

    from deepagents import create_deep_agent
    from deepagents.backends import FilesystemBackend
    from langchain.chat_models import init_chat_model
    from langchain_openai import OpenAIEmbeddings
    from langgraph.checkpoint.mongodb import MongoDBSaver
    from langgraph.store.mongodb import MongoDBStore, create_vector_index_config
    from langmem import create_manage_memory_tool, create_search_memory_tool

    from src.llms.prompts import ORCHESTRATOR_SYSTEM
    from src.persistence.client import get_client, get_db
    from src.tools.agent_tools import ALL_TOOLS

    checkpointer = MongoDBSaver(
        client=get_client(),
        db_name=config.MONGO_DB,
    )

    embeddings = OpenAIEmbeddings(
        model=config.LITELLM_EMBEDDING_MODEL,
        base_url=f"{config.LITELLM_BASE_URL}/v1",
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

    model = init_chat_model(
        model=config.LITELLM_WORKER_MODEL,
        model_provider="openai",
        base_url=f"{config.LITELLM_BASE_URL}/v1",
        api_key=config.LITELLM_API_KEY,
        temperature=config.LITELLM_TEMPERATURE,
        max_tokens=config.LITELLM_MAX_TOKENS,
    )

    memory_namespace = tuple(p.strip() for p in config.LANGMEM_NAMESPACE.split(","))
    manage_memory = create_manage_memory_tool(namespace=memory_namespace)
    search_memory = create_search_memory_tool(namespace=memory_namespace)

    agent = create_deep_agent(
        model=model,
        tools=[*ALL_TOOLS, manage_memory, search_memory],
        system_prompt=ORCHESTRATOR_SYSTEM,
        checkpointer=checkpointer,
        store=store,
        backend=FilesystemBackend(
            root_dir=config.DEEP_AGENT_WORKSPACE,
            virtual_mode=config.ENVIRONMENT == "development",
        ),
    )

    logger.info("Deep Agent built (model=%s).", config.LITELLM_WORKER_MODEL)
    return agent
