# BluteksBot

> Multi-agent Telegram assistant. Slim, fast, and cheap to run.

> **Work in progress** — functional and running in production, but actively evolving.

---

## Philosophy

BluteksBot is built on one principle: **deliver real value at minimum cost, with room to grow**.

- **Lightweight by design** — a single `docker compose up` spins up the entire stack; no Kubernetes, no managed cloud services required
- **Industry-proven stack** — every layer is a well-maintained, widely adopted framework (LangGraph, LangChain, MongoDB, LiteLLM, APScheduler), not reinvented wheels
- **Cost-controlled** — LiteLLM proxy decouples your code from any specific model; swap providers without touching a line of application code. Running on MiniMax M2.5 by default costs **less than $0.20/day**
- **Simple but scalable** — single-process today, horizontally scalable tomorrow; the persistence layer (MongoDB replica set) and stateless bot service are ready for it

---

## Stack

| Layer | Tech |
|---|---|
| Transport | Telegram Bot API (`pyTelegramBotAPI`) |
| Agent | LangGraph Deep Agents (`deepagents`) — planning, tool calling, subagents |
| LLM | LiteLLM proxy → OpenAI-compatible (self-hosted; default model: **MiniMax M2.5**) |
| Persistence | MongoDB Atlas Local (replica set — checkpoints + long-term memory + events) |
| LiteLLM state | Postgres 16 (LiteLLM internal DB) |
| Conversation state | `MongoDBSaver` (LangGraph checkpointer) — per-chat message history |
| Agent filesystem | `FilesystemBackend` — all paths written to `DEEP_AGENT_WORKSPACE` (Docker volume, mountable to S3/NFS) |
| Semantic memory | `MongoDBStore` + LangMem — cross-session vector-searchable user facts |
| Scheduling | APScheduler + MongoDB job store — declarative cron jobs via YAML |

---

## Cost & Resources

| Scenario | Approximate daily cost |
|---|---|
| MiniMax M2.5 (default) | **< $0.20 / day** |
| GPT-4o-mini | ~$0.50–1.00 / day (typical personal use) |
| Claude Sonnet | ~$1–3 / day (higher quality tasks) |

All models are configured in `litellm_config.yaml` and selected via `.env` — no code changes required to switch.

Infrastructure runs entirely in Docker on modest hardware (2 vCPU / 2 GB RAM is sufficient for personal use).

---

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

---

## Required secrets (`.env`)

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | From [@BotFather](https://t.me/botfather) |
| `OPENAI_API_KEY` | Forwarded to LiteLLM proxy (GPT models) |
| `ANTHROPIC_API_KEY` | Forwarded to LiteLLM proxy (Claude models) |
| `MINIMAX_API_KEY` | Forwarded to LiteLLM proxy (MiniMax M2 models) — **default model** |
| `TAVILY_API_KEY` | For web search ([tavily.com](https://tavily.com)) |
| `LITELLM_API_KEY` | Master key for the self-hosted LiteLLM gateway |

## Optional config (`.env`)

| Variable | Default | Description |
|---|---|---|
| `TELEGRAM_ALLOWED_USER_IDS` | _(empty = allow all)_ | Comma-separated Telegram user IDs to whitelist |
| `LITELLM_ORCHESTRATOR_MODEL` | `claude-sonnet-4-5` | Model for the orchestrator layer (routing/planning) |
| `LITELLM_WORKER_MODEL` | `minimax/minimax-m2` | Model used by the Deep Agent for all tasks |
| `LITELLM_MAX_TOKENS` | `4096` | Max tokens per LLM call |
| `LITELLM_TEMPERATURE` | `0.2` | Sampling temperature |
| `LITELLM_EMBEDDING_MODEL` | `text-embedding-3-small` | Embedding model for long-term memory search |
| `EMBEDDING_DIMENSION` | `1536` | Vector dimensions (must match model) |
| `MEMORY_TOP_K` | `5` | Top-k results for semantic memory recall |
| `LANGMEM_NAMESPACE` | `bluteksbot,memories` | Comma-separated namespace for LangMem long-term store |
| `SMTP_HOST` | `smtp.gmail.com` | SMTP server for `send_email_tool` |
| `SMTP_PORT` | `587` | SMTP port |
| `SMTP_USER` | _(empty)_ | SMTP username |
| `SMTP_PASSWORD` | _(empty)_ | SMTP password |
| `EMAIL_FROM` | _(empty)_ | Sender address for outgoing emails |
| `CALENDAR_TIMEZONE` | `UTC` | Timezone for calendar-related operations |
| `CODE_EXECUTOR_TIMEOUT` | `60` | Hard kill timeout (seconds) for code execution |
| `CODE_EXECUTOR_MAX_OUTPUT_CHARS` | `5000` | Truncate stdout/stderr beyond this length |
| `LOG_LEVEL` | `INFO` | `DEBUG \| INFO \| WARNING \| ERROR` |
| `ENVIRONMENT` | `development` | `development \| production` |
| `LANGSMITH_TRACING` | `false` | Set to `true` to enable LangSmith tracing |
| `LANGSMITH_API_KEY` | _(empty)_ | Required when `LANGSMITH_TRACING=true` |
| `LANGSMITH_PROJECT` | `bluteksbot` | LangSmith project name |

---

## Telegram commands

Slash commands are intercepted **before** the LLM — instant, no token cost.

| Command | Description |
|---|---|
| `/clean` | Clear conversation thread, checkpoints, and summarization history |
| `/model` | Show active model and available options |
| `/model <n or name>` | Switch to a different LLM model (persisted per chat) |
| `/commands` | List all available commands |

Available models are controlled by `AVAILABLE_MODELS` in `.env` (comma-separated). The selection is persisted per chat in MongoDB and survives restarts.

### Adding a new command

1. Open `src/telegram/commands/handlers.py`
2. Add a `@registry.register("/mycommand", "Description")` decorated function inside `register_all`

No other wiring needed.

---

## Agent routing

```
User message
    ↓
Deep Agent (LangGraph)  ←── MongoDBSaver        conversation state, per chat_id
    │                   ←── MongoDBStore/LangMem semantic memory, cross-thread
    │                   ←── CompositeBackend     agent filesystem (see below)
    │
    ├── Custom tools (domain integrations)
    │   ├── web_search_tool      real-time web search (Tavily)
    │   ├── execute_python_tool  run Python code
    │   ├── execute_shell_tool   run bash commands
    │   ├── send_email_tool      SMTP email
    │   ├── schedule_tool        create / list / delete cron jobs at runtime
    │   ├── manage_memory        save facts to long-term memory (LangMem)
    │   └── search_memory        recall facts from long-term memory (LangMem)
    │
    └── Built-in Deep Agent capabilities (no custom code needed)
        ├── write_todos          plan and track multi-step tasks
        ├── ls / read_file / write_file / edit_file / glob / grep  filesystem
        └── task                 delegate to specialized subagents
```

---

## Persistence layers

LiteLLM uses its own Postgres instance (managed by Docker Compose).

| Layer | Scope | Backend |
|---|---|---|
| Conversation state | Per thread (chat) | `MongoDBSaver` checkpointer |
| Agent filesystem | All paths (`/memories/`, `/workspace/`, etc.) | `FilesystemBackend` → `DEEP_AGENT_WORKSPACE` Docker volume |
| Semantic memory | All threads + restarts | `MongoDBStore` + vector index (LangMem) |
| Scheduled jobs | Persistent cron definitions | MongoDB job store (APScheduler) |

The agent is instructed to save anything that should survive across conversations under `/memories/` (e.g. `/memories/preferences.txt`, `/memories/context/`). Temporary work goes to `/workspace/`.

### Swapping the agent filesystem storage

The `agent_files` Docker volume can be replaced with any storage backend without code changes:

```yaml
# docker-compose.override.yml — example: S3 via mountpoint-s3 or s3fs
services:
  bot:
    volumes:
      - /mnt/s3-bucket/agent_files:/workspace/agent_files
```

Set `DEEP_AGENT_WORKSPACE` in `.env` if you change the container path.

---

## Development

```bash
make test    # pytest
make lint    # ruff + mypy
make clean   # remove caches + volumes
```

> This project was scaffolded and built in a single day using [Cursor IDE](https://cursor.sh) — a good example of what AI-assisted development can achieve when paired with the right frameworks.

## Adding a new agent tool

1. Create (or add to) `src/tools/agent_tools.py` with a `@tool` decorated function
2. Add it to the `ALL_TOOLS` list at the bottom of that file
3. Update `ORCHESTRATOR_SYSTEM` in `src/llms/prompts.py` to describe the new tool
