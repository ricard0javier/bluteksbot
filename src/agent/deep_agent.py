"""Deep Agent factory — builds the LangGraph Deep Agent with MongoDB persistence and LangMem."""

import logging
from functools import lru_cache

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, FilesystemBackend
from langchain_openai import OpenAIEmbeddings
from langgraph.checkpoint.mongodb import MongoDBSaver
from langgraph.store.mongodb import MongoDBStore, create_vector_index_config
from langmem import create_manage_memory_tool, create_search_memory_tool

from src import config
from src.agent.DynamicModelMiddleware import dynamic_model
from src.agent.DynamicSystemPromptMiddleware import dynamic_prompt
from src.agent.LoggingMiddleware import LoggingMiddleware
from src.persistence.client import get_client, get_db
from src.persistence.mongodb_backend import MongoDBBackend
from src.tools.agent_tools import AGENT_TOOLS
from src.tools.schedule_tool import SCHEDULE_TOOLS
from src.tools.telegram_tools import TELEGRAM_TOOLS

logger = logging.getLogger(__name__)


@lru_cache(typed=True)
def build_agent(
    model_name: str = config.WORKER_MODEL,
    include_telegram_tools: bool = True,
    include_schedule_tools: bool = True,
):
    """Build and cache a compiled Deep Agent graph per model.

    Args:
        model_name: the model to use for the agent
        include_telegram_tools: whether to include the telegram tools
        include_schedule_tools: whether to include the schedule tools

    Returns a CompiledStateGraph that accepts:
        agent.invoke(
            {"messages": [{"role": "user", "content": "..."}]},
            config={"configurable": {"thread_id": "<chat_id>"}},
        )
    """

    checkpointer = MongoDBSaver(
        client=get_client(),
        db_name=config.MONGO_DB,
    )

    embeddings = OpenAIEmbeddings(
        model=config.EMBEDDING_MODEL,
        base_url=config.OPENAI_BASE_URL,
        api_key=config.OPENAI_API_BEARER_TOKEN,
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
        # TODO: implement dynamic tool loading
        # https://www.anthropic.com/engineering/advanced-tool-use
        # https://forum.langchain.com/t/are-dynamic-tool-lists-allowed-when-using-create-agent/1920/16
        # https://docs.langchain.com/oss/python/langchain/agents#runtime-tool-registration
        tools=tools,
        checkpointer=checkpointer,
        store=store,
        backend=backend,
        middleware=[dynamic_model, dynamic_prompt, LoggingMiddleware()],
    )

    logger.info("Deep Agent built (model=%s).", model_name)

    return agent
