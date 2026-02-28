# BluteksBot

> Multi-agent Telegram assistant. Slim, fast, and cheap. If a bot can do it, why would you do it yourself?

## Stack

| Layer | Tech |
|---|---|
| Transport | Telegram Bot API (pyTelegramBotAPI) |
| Agents | Orchestrator + 7 specialist workers |
| LLM | LiteLLM proxy → OpenAI (self-hosted, swap models without code changes) |
| Persistence | MongoDB 8 (replica set — change streams + transactions enabled) |
| Memory | Vector similarity search over conversation history |

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
| `CODE_EXECUTOR_WORKSPACE` | `/workspace` | Sandbox working directory for code execution |

## Agent routing

```
User message → Orchestrator (LLM classification)
                    ├── search_agent     web search (Tavily)
                    ├── files_agent      PDF / DOCX / image OCR
                    ├── code_agent       write + execute Python
                    ├── calendar_agent   scheduling
                    ├── email_agent      SMTP
                    ├── reminders_agent  timed reminders
                    └── chat_agent       general conversation
```

## Development

```bash
make test    # pytest
make lint    # ruff + mypy
make clean   # remove caches + volumes
```

## Adding a new agent

1. Create `src/workers/my_agent.py` with `def run(task, message, raw) -> AgentResult`
2. Add its system prompt to `src/llms/prompts.py`
3. Register it in `_AGENT_REGISTRY` in `src/agent/orchestrator.py`
