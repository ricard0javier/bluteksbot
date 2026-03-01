# BluteksBot

> Multi-agent Telegram assistant. Slim, fast, and cheap. If a bot can do it, why would you do it yourself?

## Stack

| Layer | Tech |
|---|---|
| Transport | Telegram Bot API (pyTelegramBotAPI) |
| Agent | LangGraph Deep Agents (`deepagents`) — planning, tool calling, subagents |
| LLM | LiteLLM proxy → OpenAI-compatible (self-hosted, swap models without code changes) |
| Persistence | MongoDB 8 (replica set — checkpoints + long-term memory + events) |
| Short-term memory | `MongoDBSaver` (LangGraph checkpointer) — per-chat conversation history |
| Long-term memory | `MongoDBStore` + LangMem — cross-session user memory with vector search |

## Quickstart

```bash
# 1. Copy and fill secrets
cp .env.example .env

# 2. Create conda environment
make install

# 3. Start infrastructure
make up

# 4. Run bot locally (hot-reload friendly)
make dev
```

## Required secrets (`.env`)

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | From [@BotFather](https://t.me/botfather) |
| `OPENAI_API_KEY` | Forwarded to LiteLLM proxy (GPT-5.x models) |
| `ANTHROPIC_API_KEY` | Forwarded to LiteLLM proxy (Claude models) |
| `MINIMAX_API_KEY` | Forwarded to LiteLLM proxy (MiniMax M2 models) |
| `TAVILY_API_KEY` | For web search ([tavily.com](https://tavily.com)) |
| `LITELLM_API_KEY` | Master key for the self-hosted LiteLLM gateway |

## Optional config (`.env`)

| Variable | Default | Description |
|---|---|---|
| `LITELLM_WORKER_MODEL` | `minimax-m2` | Model used by the Deep Agent for all tasks |
| `LITELLM_EMBEDDING_MODEL` | `text-embedding-3-small` | Embedding model for long-term memory search |
| `LANGMEM_NAMESPACE` | `bluteksbot,memories` | Comma-separated namespace for LangMem long-term store |
| `LANGSMITH_TRACING` | `false` | Set to `true` to enable LangSmith tracing |
| `LANGSMITH_API_KEY` | _(empty)_ | Required when `LANGSMITH_TRACING=true` |
| `LANGSMITH_PROJECT` | `bluteksbot` | LangSmith project name |
| `CODE_EXECUTOR_WORKSPACE` | `/workspace` | Sandbox working directory for code execution |

## Agent routing

```
User message
    ↓
Orchestrator (thin wrapper)
    ↓
Deep Agent (LangGraph)  ←── MongoDBSaver (thread memory per chat_id)
    │                   ←── MongoDBStore + LangMem (long-term user memory)
    │
    ├── Custom tools (domain integrations)
    │   ├── web_search_tool      real-time web search (Tavily)
    │   ├── execute_python_tool  run Python code
    │   ├── execute_shell_tool   run bash commands
    │   ├── send_email_tool      SMTP email
    │   ├── manage_memory        save facts to long-term memory (LangMem)
    │   └── search_memory        recall facts from long-term memory (LangMem)
    │
    └── Built-in Deep Agent capabilities (no custom code needed)
        ├── write_todos          plan and track multi-step tasks
        ├── ls / read_file / write_file / edit_file / glob / grep  filesystem
        └── task                 delegate to specialized subagents
```

## Development

```bash
make test    # pytest
make lint    # ruff + mypy
make clean   # remove caches + volumes
```

## Adding a new tool

1. Create (or add to) `src/tools/agent_tools.py` with a `@tool` decorated function
2. Add it to the `ALL_TOOLS` list at the bottom of that file
3. Update `ORCHESTRATOR_SYSTEM` in `src/llms/prompts.py` to describe the new tool
