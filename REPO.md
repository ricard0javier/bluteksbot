You are a Principal Software Engineer. Generate a production-ready Python service repository
following these professional conventions exactly.

## Project Structure

```
src/
  <module>/        # one folder per bounded concern (e.g. consumers, persistence, llms, agent, files, embeddings)
  examples/        # standalone runnable demos of core domain functionality
  config.py        # single config module; all values via os.getenv() with sensible defaults
  main.py          # thin entrypoint: Application class, thread management, signal handlers only
tests/             # mirrors src/ structure
.env.example       # documents every required env var with description and default
docker-compose.yml # all external dependencies (DBs, brokers, UIs) as named services with dedicated networks
Dockerfile         # multi-stage or single-stage container build
Makefile           # targets: install, dev, build, test, clean
environment.yml    # conda env with Python version pinned
requirements.txt   # pip dependencies complementing conda
```

## Application Lifecycle

- Implement an `Application` class with: `stop_event: threading.Event`, worker threads started
  as `daemon=True`, SIGTERM/SIGINT signal handlers, and a main loop that monitors thread liveness.
- Shutdown must be graceful: signal sets `stop_event`, threads detect it and exit cleanly.

## Integration Patterns

- **Inbound transport consumer loop**: exponential-backoff reconnect on startup, manual offset commit,
  configurable via env vars (topic, group, DLQ topic, bootstrap servers).
- **Idempotency**: before processing any event, check the persistence store using `causationId`;
  skip if already handled.
- **Dead Letter Queue**: on unrecoverable processing error, forward the original message to a DLQ
  with error metadata appended; always commit offset to prevent blocking.
- **Event envelope**: every produced event carries:
  `_id`, `eventType`, `metadata` (traceId, correlationId, causationId, occurredAt, source, schema_version),
  `aggregate` (type, id, subType, sequenceNr), `payload`.
- **Event Store**: persist all produced events as immutable documents in a dedicated collection/table.

## Code Quality Standards

- Structured logging via Python stdlib `logging`; level configurable via `LOG_LEVEL` env var;
  output to stdout and file.
- All configuration centralised in `config.py` — zero hardcoded values in business logic.
- Type hints throughout; Pydantic models for all schemas and external contracts.
- Singleton persistence client with lazy initialisation (`get_client()` pattern).
- Error handling: catch specific exceptions, log with `exc_info=True`, re-raise or route to DLQ.
- No business logic in `main.py` or `config.py`.

## What to Generate

Based on the above conventions, generate a [DESCRIBE YOUR SPECIFIC SERVICE HERE].
Replace all placeholder names, topics, collections, and domain terms with ones appropriate
for the new service. Keep all structural and engineering conventions intact.
