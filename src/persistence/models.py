"""Pydantic models for the event envelope and aggregate contracts."""
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


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
