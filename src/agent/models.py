"""Agent-level Pydantic contracts."""
from typing import Any, Optional
from pydantic import BaseModel


class OrchestratorDecision(BaseModel):
    agent: str
    task: str


class AgentResult(BaseModel):
    agent: str
    success: bool
    reply: str
    metadata: Optional[dict[str, Any]] = None
