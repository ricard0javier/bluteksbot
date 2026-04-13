"""Observability dashboard + OpenAI-compatible API endpoints."""

import json
import logging
import secrets
import time
from collections.abc import Iterator
from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, Field

from src import config
from src.agent.agent_interface import (
    extract_final_reply,
    iter_agent_stream_progress,
    run_agent_stream,
)
from src.agent.deep_agent import build_agent
from src.persistence import job_store, task_store
from src.persistence.client import get_db
from src.persistence.models import BotTask, TaskStatus

app = FastAPI(title="Bluteksbot Dashboard", docs_url=None, redoc_url=None)
logger = logging.getLogger(__name__)


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | list[dict[str, Any]]
    name: str | None = None


class ChatCompletionsRequest(BaseModel):
    model: str = Field(default_factory=lambda: config.WORKER_MODEL)
    messages: list[ChatMessage]
    stream: bool = False
    user: str | None = None
    conversation_id: str | None = None


class _ChoiceMessage(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str


class _Choice(BaseModel):
    index: int = 0
    message: _ChoiceMessage
    finish_reason: Literal["stop"] = "stop"


class ChatCompletionsResponse(BaseModel):
    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int
    model: str
    choices: list[_Choice]
    conversation_id: str
    usage: dict[str, int]


def _extract_text_content(content: str | list[dict[str, Any]]) -> str:
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        if block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text)
    return "\n".join(parts).strip()


def _last_user_message(messages: list[ChatMessage]) -> str:
    for msg in reversed(messages):
        if msg.role == "user":
            text = _extract_text_content(msg.content)
            if text:
                return text
    raise HTTPException(status_code=400, detail="No non-empty user message found")


def _to_agent_messages(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    agent_messages: list[dict[str, Any]] = []
    for msg in messages:
        text = _extract_text_content(msg.content)
        if not text:
            continue
        agent_messages.append({"role": msg.role, "content": text})
    if not agent_messages:
        raise HTTPException(status_code=400, detail="No non-empty messages found")
    return agent_messages


def _estimate_usage(prompt: str, completion: str) -> dict[str, int]:
    # Lightweight estimate to keep OpenAI shape without tokenizer dependency.
    prompt_tokens = max(1, len(prompt) // 4)
    completion_tokens = max(1, len(completion) // 4)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


def _require_bearer_token(authorization: str | None = Header(default=None)) -> None:
    expected = config.OPENAI_API_BEARER_TOKEN.strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="OpenAI API auth is not configured",
        )

    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid Authorization header")

    provided = parts[1].strip()
    if not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid bearer token")


def _validate_chat_request(req: ChatCompletionsRequest) -> None:
    if not req.messages:
        raise HTTPException(status_code=400, detail="messages must not be empty")

    if req.model not in config.AVAILABLE_MODELS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported model '{req.model}'. Available: {config.AVAILABLE_MODELS}",
        )


def _resolve_conversation_id(req: ChatCompletionsRequest, request: Request) -> str:
    explicit = (req.conversation_id or "").strip()
    if explicit:
        return explicit

    header_candidates = (
        request.headers.get("x-conversation-id", ""),
        request.headers.get("x-thread-id", ""),
        request.headers.get("x-chat-id", ""),
        request.headers.get("openai-conversation-id", ""),
        request.headers.get("x-openwebui-conversation-id", ""),
    )
    for candidate in header_candidates:
        value = candidate.strip()
        if value:
            return value

    if req.user and req.user.strip():
        return f"user:{req.user.strip()}"

    return str(uuid4())


def _sse_line(payload: dict[str, Any] | str) -> str:
    if isinstance(payload, str):
        return f"data: {payload}\n\n"
    return f"data: {json.dumps(payload, ensure_ascii=True)}\n\n"


def _chunk_text(text: str, size: int = 120) -> Iterator[str]:
    for idx in range(0, len(text), size):
        yield text[idx : idx + size]


def _stream_chat_completion_live(
    *,
    completion_id: str,
    created: int,
    model: str,
    conversation_id: str,
    task_id: str,
    api_agent: CompiledStateGraph,
    input_messages: list[dict[str, Any]],
) -> Iterator[str]:
    """SSE stream: role chunk, tool progress deltas, answer chunks, finish (graph runs via stream)."""
    try:
        yield _sse_line({
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "conversation_id": conversation_id,
            "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
        })
        for label in iter_agent_stream_progress(
            api_agent, conversation_id, input_messages, task_id
        ):
            yield _sse_line({
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "conversation_id": conversation_id,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": f"{label}\n"},
                        "finish_reason": None,
                    }
                ],
            })
        completion = extract_final_reply(api_agent, conversation_id)
        for piece in _chunk_text(completion):
            yield _sse_line({
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "conversation_id": conversation_id,
                "choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}],
            })
        yield _sse_line({
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "conversation_id": conversation_id,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        })
        yield _sse_line("[DONE]")
        task_store.update_status(task_id, TaskStatus.DONE, result=completion[:500])
    except InterruptedError:
        task_store.update_status(task_id, TaskStatus.CANCELLED)
    except Exception as exc:
        task_store.update_status(task_id, TaskStatus.FAILED, error=str(exc))
        raise


# ── Data helpers ──────────────────────────────────────────────────────────────


def _serialize(doc: dict) -> dict:
    """Convert MongoDB doc to JSON-safe dict (ObjectId → str, datetime → ISO)."""
    out: dict[str, Any] = {}
    for k, v in doc.items():
        key = "id" if k == "_id" else k
        if isinstance(v, datetime):
            out[key] = v.isoformat()
        elif isinstance(v, list):
            out[key] = [_serialize(i) if isinstance(i, dict) else i for i in v]
        else:
            out[key] = str(v) if not isinstance(v, (str, int, float, bool, type(None))) else v
    return out


# ── API endpoints ─────────────────────────────────────────────────────────────


@app.get("/v1/models", dependencies=[Depends(_require_bearer_token)])
def list_models() -> dict[str, Any]:
    data = [
        {
            "id": model_id,
            "object": "model",
            "created": 0,
            "owned_by": "bluteksbot",
        }
        for model_id in config.AVAILABLE_MODELS
    ]
    return {"object": "list", "data": data}


@app.post("/v1/chat/completions", dependencies=[Depends(_require_bearer_token)])
def chat_completions(req: ChatCompletionsRequest, request: Request) -> Any:
    logger.debug(
        "OpenAI chat request received: headers=%s body=%s", dict(request.headers), req.model_dump()
    )
    _validate_chat_request(req)
    conversation_id = _resolve_conversation_id(req, request)
    completion_id = f"chatcmpl-{uuid4().hex}"
    created = int(time.time())

    prompt = _last_user_message(req.messages)
    input_messages = _to_agent_messages(req.messages)
    api_agent = build_agent(
        model_name=req.model, include_telegram_tools=False, include_schedule_tools=False
    )
    task = BotTask(
        causation_id=f"api-{completion_id}",
        chat_id="",
        message_id=0,
        input=prompt[:500] if prompt else "chat",
    )
    task_id = task_store.create(task)
    task_store.update_status(task_id, TaskStatus.RUNNING)

    common_headers = {"X-Task-Id": task_id}

    if req.stream:
        return StreamingResponse(
            _stream_chat_completion_live(
                completion_id=completion_id,
                created=created,
                model=req.model,
                conversation_id=conversation_id,
                task_id=task_id,
                api_agent=api_agent,
                input_messages=input_messages,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                **common_headers,
            },
        )

    try:
        completion = run_agent_stream(
            api_agent,
            conversation_id,
            input_messages,
            task_id=task_id,
            progress_update_callback=None,
        )
    except HTTPException:
        raise
    except InterruptedError as exc:
        task_store.update_status(task_id, TaskStatus.CANCELLED)
        raise HTTPException(status_code=409, detail="Task was cancelled") from exc
    except Exception as exc:
        task_store.update_status(task_id, TaskStatus.FAILED, error=str(exc))
        raise HTTPException(status_code=500, detail=f"Agent invocation failed: {exc}") from exc

    task_store.update_status(task_id, TaskStatus.DONE, result=completion[:500])
    usage = _estimate_usage(prompt, completion)
    payload = ChatCompletionsResponse(
        id=completion_id,
        created=created,
        model=req.model,
        conversation_id=conversation_id,
        choices=[_Choice(message=_ChoiceMessage(content=completion))],
        usage=usage,
    ).model_dump()
    return JSONResponse(content=payload, headers=common_headers)


@app.get("/api/status")
def get_status() -> dict:
    db = get_db()

    tasks = [
        _serialize(doc)
        for doc in db[config.MONGO_COLLECTION_TASKS].find({}, sort=[("created_at", -1)], limit=30)
    ]

    executions = [
        _serialize(doc)
        for doc in db[config.MONGO_COLLECTION_JOB_EXECUTIONS].find(
            {}, sort=[("claimed_at", -1)], limit=20
        )
    ]

    jobs = [_serialize(doc) for doc in db[config.MONGO_COLLECTION_SCHEDULED_JOBS].find({})]

    active_tasks = sum(1 for t in tasks if t.get("status") in ("pending", "running"))

    return {
        "app": config.APP_NAME,
        "environment": config.ENVIRONMENT,
        "active_tasks": active_tasks,
        "tasks": tasks,
        "executions": executions,
        "jobs": jobs,
    }


@app.post("/api/tasks/{task_id}/cancel")
def cancel_task(task_id: str) -> dict:
    status = task_store.get_status(task_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if status not in (TaskStatus.PENDING, TaskStatus.RUNNING):
        raise HTTPException(status_code=409, detail=f"Task is already {status.value}")
    task_store.update_status(task_id, TaskStatus.CANCELLED, error="Cancelled via dashboard")
    return {"ok": True, "task_id": task_id}


@app.post("/api/jobs/{job_id}/disable")
def disable_job(job_id: str) -> dict:
    from src.scheduler.service import get_scheduler

    scheduler = get_scheduler()
    ok = scheduler.disable_job(job_id) if scheduler else job_store.disable_job(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"ok": True, "job_id": job_id, "enabled": False}


@app.post("/api/jobs/{job_id}/enable")
def enable_job(job_id: str) -> dict:
    from src.scheduler.service import get_scheduler

    scheduler = get_scheduler()
    ok = scheduler.enable_job(job_id) if scheduler else job_store.enable_job(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"ok": True, "job_id": job_id, "enabled": True}


# ── Dashboard HTML ────────────────────────────────────────────────────────────

_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Bluteksbot — Dashboard</title>
<style>
  :root {
    --bg: #0f1117; --surface: #1a1d27; --border: #2a2d3a;
    --text: #e2e8f0; --muted: #6b7280; --accent: #6366f1;
    --green: #22c55e; --yellow: #f59e0b; --red: #ef4444; --blue: #3b82f6;
    --radius: 8px; --font: 'Inter', system-ui, sans-serif;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: var(--font); font-size: 14px; }
  header { padding: 16px 24px; border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 12px; }
  header h1 { font-size: 18px; font-weight: 600; }
  .badge { font-size: 11px; padding: 2px 8px; border-radius: 99px; background: var(--accent); color: #fff; }
  .refresh { margin-left: auto; font-size: 12px; color: var(--muted); }
  .pulse { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: var(--green); margin-right: 6px; animation: pulse 1.5s infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.3} }
  main { padding: 24px; display: grid; gap: 24px; }
  .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; }
  .stat { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 16px; }
  .stat-label { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .5px; margin-bottom: 6px; }
  .stat-value { font-size: 28px; font-weight: 700; }
  section h2 { font-size: 14px; font-weight: 600; margin-bottom: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: .5px; }
  table { width: 100%; border-collapse: collapse; background: var(--surface); border-radius: var(--radius); overflow: hidden; border: 1px solid var(--border); }
  th { text-align: left; padding: 10px 14px; font-size: 11px; text-transform: uppercase; letter-spacing: .5px; color: var(--muted); border-bottom: 1px solid var(--border); }
  td { padding: 10px 14px; border-bottom: 1px solid var(--border); vertical-align: top; max-width: 320px; word-break: break-word; }
  tr:last-child td { border-bottom: none; }
  tr:hover td { background: rgba(255,255,255,.02); }
  .status { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; font-weight: 500; padding: 2px 8px; border-radius: 99px; }
  .status.pending  { background: rgba(107,114,128,.2); color: #9ca3af; }
  .status.running  { background: rgba(99,102,241,.2);  color: #818cf8; }
  .status.done     { background: rgba(34,197,94,.15);  color: #4ade80; }
  .status.failed   { background: rgba(239,68,68,.15);  color: #f87171; }
  .status.claimed    { background: rgba(245,158,11,.15); color: #fbbf24; }
  .status.cancelled  { background: rgba(107,114,128,.2); color: #9ca3af; text-decoration: line-through; }
  .progress { list-style: none; }
  .progress li { font-size: 12px; color: var(--muted); padding: 1px 0; }
  .progress li::before { content: '→ '; color: var(--accent); }
  .input-text { font-size: 12px; color: var(--text); }
  .ts { font-size: 11px; color: var(--muted); white-space: nowrap; }
  .empty { text-align: center; color: var(--muted); padding: 32px; }
  .btn { font-size: 11px; font-weight: 500; padding: 3px 10px; border-radius: 6px; border: none; cursor: pointer; transition: opacity .15s; }
  .btn:hover { opacity: .8; }
  .btn-disable { background: rgba(239,68,68,.15); color: #f87171; }
  .btn-enable  { background: rgba(34,197,94,.15);  color: #4ade80; }
  .header-actions { margin-left: auto; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .btn-refresh-now { background: rgba(255,255,255,.08); color: var(--text); }
  .btn-auto.on { background: rgba(99,102,241,.25); color: #a5b4fc; }
  .btn-auto.off { background: rgba(107,114,128,.15); color: var(--muted); }
  .steps { display: flex; flex-direction: column; gap: 4px; min-width: 260px; }
  .step { background: rgba(255,255,255,.03); border: 1px solid var(--border); border-radius: 6px; overflow: hidden; }
  .step-header { display: flex; align-items: center; gap: 6px; padding: 5px 8px; cursor: pointer; user-select: none; }
  .step-header:hover { background: rgba(255,255,255,.04); }
  .tool-badge { font-size: 10px; font-weight: 600; padding: 1px 7px; border-radius: 99px; white-space: nowrap; }
  .step-dur { font-size: 10px; color: var(--muted); margin-left: auto; white-space: nowrap; }
  .step-chevron { font-size: 10px; color: var(--muted); transition: transform .15s; }
  .step-chevron.open { transform: rotate(90deg); }
  .step-body { display: none; border-top: 1px solid var(--border); }
  .step-body.open { display: block; }
  .step-section { padding: 6px 8px; }
  .step-section + .step-section { border-top: 1px solid var(--border); }
  .step-section-label { font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: .4px; margin-bottom: 3px; }
  .step-section pre { font-size: 11px; color: var(--text); white-space: pre-wrap; word-break: break-all; margin: 0; line-height: 1.5; }
</style>
</head>
<body>
<header>
  <span class="pulse"></span>
  <h1>Bluteksbot</h1>
  <span class="badge" id="env">—</span>
  <div class="header-actions">
    <button type="button" class="btn btn-auto on" id="btn-auto" onclick="toggleAutoRefresh()" title="Poll /api/status every 3s">Auto update: On</button>
    <button type="button" class="btn btn-refresh-now" id="btn-refresh-now" onclick="refresh()">Refresh now</button>
    <span class="refresh" id="refresh-ts">Refreshing…</span>
  </div>
</header>
<main>
  <div class="stats">
    <div class="stat"><div class="stat-label">Active Tasks</div><div class="stat-value" id="s-active">—</div></div>
    <div class="stat"><div class="stat-label">Tasks (30)</div><div class="stat-value" id="s-tasks">—</div></div>
    <div class="stat"><div class="stat-label">Scheduled Jobs</div><div class="stat-value" id="s-jobs">—</div></div>
    <div class="stat"><div class="stat-label">Recent Executions</div><div class="stat-value" id="s-execs">—</div></div>
  </div>

  <section>
    <h2>Tasks</h2>
    <table id="tasks-table">
      <thead><tr>
        <th>Status</th><th>Input</th><th>Steps</th><th>Result / Error</th><th>Created</th><th></th>
      </tr></thead>
      <tbody id="tasks-body"><tr><td colspan="6" class="empty">Loading…</td></tr></tbody>
    </table>
  </section>

  <section>
    <h2>Scheduled Jobs</h2>
    <table id="jobs-table">
      <thead><tr>
        <th>Name</th><th>Cron</th><th>Last Run</th><th>Next Run</th><th>Enabled</th><th>Action</th>
      </tr></thead>
      <tbody id="jobs-body"><tr><td colspan="6" class="empty">Loading…</td></tr></tbody>
    </table>
  </section>

  <section>
    <h2>Recent Job Executions</h2>
    <table id="exec-table">
      <thead><tr>
        <th>Job</th><th>Status</th><th>Claimed At</th><th>Duration</th><th>Result / Error</th>
      </tr></thead>
      <tbody id="exec-body"><tr><td colspan="5" class="empty">Loading…</td></tr></tbody>
    </table>
  </section>
</main>

<script>
function statusBadge(s) {
  return `<span class="status ${s}">${s}</span>`;
}
function fmt(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleString(undefined, {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'});
}
function trunc(s, n=120) {
  if (!s) return '—';
  return s.length > n ? s.slice(0, n) + '…' : s;
}
function duration(startIso, endIso) {
  if (!startIso) return '—';
  const start = new Date(startIso);
  const end = endIso ? new Date(endIso) : new Date();
  const s = Math.round((end - start) / 1000);
  if (s < 60) return s + 's';
  return Math.floor(s/60) + 'm ' + (s%60) + 's';
}

// Tool badge colours — deterministic hue from tool name
const TOOL_COLORS = {
  web_search_tool:    ['rgba(59,130,246,.2)',  '#93c5fd'],
  execute_python_tool:['rgba(234,179, 8,.2)',  '#fde047'],
  execute_shell_tool: ['rgba(239,68, 68,.2)',  '#fca5a5'],
  send_email_tool:    ['rgba(34,197, 94,.2)',  '#86efac'],
  manage_memory:      ['rgba(168,85,247,.2)',  '#d8b4fe'],
  search_memory:      ['rgba(168,85,247,.2)',  '#d8b4fe'],
  task:               ['rgba(251,146,60,.2)',  '#fdba74'],
};
function toolBadge(name) {
  const [bg, fg] = TOOL_COLORS[name] || ['rgba(107,114,128,.2)', '#9ca3af'];
  return `<span class="tool-badge" style="background:${bg};color:${fg}">${name}</span>`;
}
function stepDur(ms) {
  if (ms == null) return '';
  if (ms < 1000) return ms + 'ms';
  return (ms/1000).toFixed(1) + 's';
}

let _stepIdx = 0;
function renderSteps(steps) {
  if (!steps || !steps.length) return '<span style="color:var(--muted);font-size:12px">—</span>';
  return '<div class="steps">' + steps.map(s => {
    const id = 'step-' + (++_stepIdx);
    const hasBody = s.args_preview || s.output_preview;
    return `<div class="step">
      <div class="step-header" ${hasBody ? `onclick="toggleStep('${id}')"` : ''}>
        ${toolBadge(s.tool)}
        ${s.node ? `<span style="font-size:10px;color:var(--muted)">${s.node}</span>` : ''}
        <span class="step-dur">${stepDur(s.duration_ms)}</span>
        ${hasBody ? `<span class="step-chevron" id="${id}-ch">▶</span>` : ''}
      </div>
      ${hasBody ? `<div class="step-body" id="${id}">
        ${s.args_preview ? `<div class="step-section"><div class="step-section-label">Args</div><pre>${esc(s.args_preview)}</pre></div>` : ''}
        ${s.output_preview ? `<div class="step-section"><div class="step-section-label">Output</div><pre>${esc(s.output_preview)}</pre></div>` : ''}
      </div>` : ''}
    </div>`;
  }).join('') + '</div>';
}
function toggleStep(id) {
  const body = document.getElementById(id);
  const ch = document.getElementById(id + '-ch');
  if (!body) return;
  body.classList.toggle('open');
  ch && ch.classList.toggle('open');
}
function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

const POLL_MS = 3000;
const LS_AUTO = 'bluteksbot_dashboard_auto_refresh';
let autoIntervalId = null;

function isAutoRefreshEnabled() {
  const v = localStorage.getItem(LS_AUTO);
  if (v === null) return true;
  return v === '1';
}

function setAutoRefresh(enabled) {
  localStorage.setItem(LS_AUTO, enabled ? '1' : '0');
  const btn = document.getElementById('btn-auto');
  if (btn) {
    btn.textContent = enabled ? 'Auto update: On' : 'Auto update: Off';
    btn.classList.toggle('on', enabled);
    btn.classList.toggle('off', !enabled);
  }
  if (autoIntervalId) {
    clearInterval(autoIntervalId);
    autoIntervalId = null;
  }
  if (enabled) autoIntervalId = setInterval(refresh, POLL_MS);
}

function toggleAutoRefresh() {
  const next = !isAutoRefreshEnabled();
  setAutoRefresh(next);
  if (next) refresh();
}

async function cancelTask(taskId) {
  try {
    const res = await fetch(`/api/tasks/${taskId}/cancel`, {method: 'POST'});
    if (!res.ok) throw new Error((await res.json()).detail);
    await refresh();
  } catch(err) {
    alert('Failed to cancel task: ' + err.message);
  }
}

async function toggleJob(jobId, enable) {
  const action = enable ? 'enable' : 'disable';
  try {
    const res = await fetch(`/api/jobs/${jobId}/${action}`, {method: 'POST'});
    if (!res.ok) throw new Error(await res.text());
    await refresh();
  } catch(err) {
    alert('Failed to ' + action + ' job: ' + err.message);
  }
}

async function refresh() {
  try {
    const data = await fetch('/api/status').then(r => r.json());

    document.getElementById('env').textContent = data.environment || '—';
    document.getElementById('s-active').textContent = data.active_tasks ?? '—';
    document.getElementById('s-tasks').textContent = data.tasks.length;
    document.getElementById('s-jobs').textContent = data.jobs.length;
    document.getElementById('s-execs').textContent = data.executions.length;
    document.getElementById('refresh-ts').textContent = 'Updated ' + new Date().toLocaleTimeString();

    // Tasks
    const tbody = document.getElementById('tasks-body');
    if (!data.tasks.length) {
      tbody.innerHTML = '<tr><td colspan="6" class="empty">No tasks yet.</td></tr>';
    } else {
      _stepIdx = 0;
      tbody.innerHTML = data.tasks.map(t => {
        const outcome = t.error
          ? `<span style="color:var(--red);font-size:12px">${trunc(t.error,80)}</span>`
          : `<span style="font-size:12px">${trunc(t.result,100)}</span>`;
        const cancelBtn = (t.status === 'pending' || t.status === 'running')
          ? `<button class="btn btn-disable" onclick="cancelTask('${t.id}')">Cancel</button>`
          : '';
        return `<tr>
          <td>${statusBadge(t.status)}</td>
          <td><span class="input-text">${trunc(t.input, 80)}</span></td>
          <td>${renderSteps(t.steps)}</td>
          <td>${outcome}</td>
          <td><span class="ts">${fmt(t.created_at)}</span></td>
          <td>${cancelBtn}</td>
        </tr>`;
      }).join('');
    }

    // Scheduled Jobs
    const jbody = document.getElementById('jobs-body');
    if (!data.jobs.length) {
      jbody.innerHTML = '<tr><td colspan="6" class="empty">No jobs configured.</td></tr>';
    } else {
      jbody.innerHTML = data.jobs.map(j => {
        const btn = j.enabled
          ? `<button class="btn btn-disable" onclick="toggleJob('${j.id}', false)">Disable</button>`
          : `<button class="btn btn-enable"  onclick="toggleJob('${j.id}', true)">Enable</button>`;
        return `<tr>
          <td><strong>${j.name}</strong></td>
          <td><code style="font-size:12px">${j.cron_expr}</code></td>
          <td><span class="ts">${fmt(j.last_run_at)}</span></td>
          <td><span class="ts">${fmt(j.next_run_at)}</span></td>
          <td>${j.enabled ? '<span style="color:var(--green)">✓</span>' : '<span style="color:var(--muted)">✗</span>'}</td>
          <td>${btn}</td>
        </tr>`;
      }).join('');
    }

    // Executions
    const ebody = document.getElementById('exec-body');
    if (!data.executions.length) {
      ebody.innerHTML = '<tr><td colspan="5" class="empty">No executions yet.</td></tr>';
    } else {
      ebody.innerHTML = data.executions.map(e => {
        const outcome = e.error
          ? `<span style="color:var(--red);font-size:12px">${trunc(e.error,80)}</span>`
          : `<span style="font-size:12px">${trunc(e.result,80)}</span>`;
        return `<tr>
          <td><strong>${e.job_name}</strong></td>
          <td>${statusBadge(e.status)}</td>
          <td><span class="ts">${fmt(e.claimed_at)}</span></td>
          <td><span class="ts">${duration(e.started_at, e.completed_at)}</span></td>
          <td>${outcome}</td>
        </tr>`;
      }).join('');
    }

  } catch(err) {
    document.getElementById('refresh-ts').textContent = 'Error: ' + err.message;
  }
}

refresh();
setAutoRefresh(isAutoRefreshEnabled());
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def dashboard() -> HTMLResponse:
    return HTMLResponse(_DASHBOARD_HTML)
