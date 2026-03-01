"""Task store — MongoDB-backed CRUD for async bot task tracking."""
import logging
from datetime import datetime, timezone
from typing import Optional

from src import config
from src.persistence.client import get_db
from src.persistence.models import BotTask, TaskStatus

logger = logging.getLogger(__name__)


def _col():
    return get_db()[config.MONGO_COLLECTION_TASKS]


def create(task: BotTask) -> str:
    doc = task.model_dump(by_alias=True)
    _col().insert_one(doc)
    logger.debug("Task created: %s (chat=%s).", task.id, task.chat_id)
    return task.id


def update_status(
    task_id: str,
    status: TaskStatus,
    result: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    fields: dict = {"status": status.value, "updated_at": datetime.now(timezone.utc)}
    if result is not None:
        fields["result"] = result
    if error is not None:
        fields["error"] = error
    _col().update_one({"_id": task_id}, {"$set": fields})
    logger.debug("Task %s → %s.", task_id, status.value)


def append_progress(task_id: str, step: str) -> None:
    _col().update_one(
        {"_id": task_id},
        {
            "$push": {"progress": step},
            "$set": {"updated_at": datetime.now(timezone.utc)},
        },
    )
