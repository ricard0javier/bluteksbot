"""Pydantic models for the event envelope, aggregate contracts, and task tracking."""

from datetime import UTC, datetime
from enum import Enum, StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStep(BaseModel):
    tool: str
    node: str = ""
    args_preview: str | None = None
    output_preview: str | None = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    duration_ms: int | None = None


class BotTask(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()), alias="_id")
    causation_id: str
    chat_id: str
    message_id: int = 0
    status: TaskStatus = TaskStatus.PENDING
    input: str
    progress: list[str] = []
    steps: list[TaskStep] = []
    result: str | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    model_config = {"populate_by_name": True}


class JobStatus(str, Enum):
    CLAIMED = "claimed"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class ScheduledJob(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()), alias="_id")
    name: str
    cron_expr: str
    task_prompt: str
    chat_id: str
    enabled: bool = True
    created_by: str  # "config" or "user:{chat_id}"
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    model_config = {"populate_by_name": True}


class JobExecution(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()), alias="_id")
    job_id: str
    job_name: str
    chat_id: str
    scheduled_fire_time: datetime
    claimed_by: str  # "hostname:pid" — the atomic lock field
    claimed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: JobStatus = JobStatus.CLAIMED
    task_id: str | None = None
    result: str | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {"populate_by_name": True}


class EventMetadata(BaseModel):
    traceId: str = Field(default_factory=lambda: str(uuid4()))
    correlationId: str = Field(default_factory=lambda: str(uuid4()))
    causationId: str = Field(default_factory=lambda: str(uuid4()))
    occurredAt: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source: str = "bluteksbot"
    schema_version: str = "1.0"


class EventAggregate(BaseModel):
    type: str
    id: str
    subType: str | None = None
    sequenceNr: int = 0


class Event(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()), alias="_id")
    eventType: str
    metadata: EventMetadata = Field(default_factory=EventMetadata)
    aggregate: EventAggregate
    payload: dict[str, Any]

    model_config = {"populate_by_name": True}
