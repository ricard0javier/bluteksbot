"""Pydantic models for the event envelope, aggregate contracts, and task tracking."""
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class BotTask(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()), alias="_id")
    causation_id: str
    chat_id: int
    message_id: int
    status: TaskStatus = TaskStatus.PENDING
    input: str
    progress: list[str] = []
    result: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = {"populate_by_name": True}


class EventMetadata(BaseModel):
    traceId: str = Field(default_factory=lambda: str(uuid4()))
    correlationId: str = Field(default_factory=lambda: str(uuid4()))
    causationId: str = Field(default_factory=lambda: str(uuid4()))
    occurredAt: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = "bluteksbot"
    schema_version: str = "1.0"


class EventAggregate(BaseModel):
    type: str
    id: str
    subType: Optional[str] = None
    sequenceNr: int = 0


class Event(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()), alias="_id")
    eventType: str
    metadata: EventMetadata = Field(default_factory=EventMetadata)
    aggregate: EventAggregate
    payload: dict[str, Any]

    model_config = {"populate_by_name": True}
