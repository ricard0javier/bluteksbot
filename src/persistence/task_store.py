"""Task store — MongoDB-backed CRUD for async bot task tracking."""

import logging
from datetime import UTC, datetime

from src import config
from src.persistence.client import get_db
from src.persistence.models import BotTask, TaskStatus, TaskStep

logger = logging.getLogger(__name__)


def _col():
    return get_db()[config.MONGO_COLLECTION_TASKS]


def create(task: BotTask) -> str:
    doc = task.model_dump(by_alias=True)
    _col().insert_one(doc)
    logger.debug("Task created: %s (chat=%s).", task.id, task.chat_id, task.status.value)
    return task.id


def update_status(
    task_id: str,
    status: TaskStatus,
    result: str | None = None,
    error: str | None = None,
) -> None:
    fields: dict = {"status": status.value, "updated_at": datetime.now(UTC)}
    if result is not None:
        fields["result"] = result
    if error is not None:
        fields["error"] = error
    _col().update_one({"_id": task_id}, {"$set": fields})
    logger.debug("Task %s → %s.", task_id, status.value)


def get_status(task_id: str) -> TaskStatus | None:
    doc = _col().find_one({"_id": task_id}, {"status": 1})
    if not doc:
        return None
    return TaskStatus(doc["status"])


def append_progress(task_id: str, step: str) -> None:
    _col().update_one(
        {"_id": task_id},
        {
            "$push": {"progress": step},
            "$set": {"updated_at": datetime.now(UTC)},
        },
    )


def append_step(task_id: str, step: TaskStep) -> None:
    _col().update_one(
        {"_id": task_id},
        {
            "$push": {"steps": step.model_dump()},
            "$set": {"updated_at": datetime.now(UTC)},
        },
    )


def list_running(chat_id: int) -> list[dict]:
    """Return running/pending tasks for a chat as lightweight dicts: {id, input, status}."""
    docs = (
        _col()
        .find(
            {
                "chat_id": chat_id,
                "status": {"$in": [TaskStatus.RUNNING.value, TaskStatus.PENDING.value]},
            },
            {"_id": 1, "input": 1, "status": 1, "created_at": 1},
        )
        .sort("created_at", -1)
        .limit(10)
    )
    return [
        {"id": doc["_id"], "input": doc.get("input", ""), "status": doc.get("status", "")}
        for doc in docs
    ]
