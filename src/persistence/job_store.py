"""Job store — MongoDB CRUD for scheduled_jobs and job_executions collections."""
import logging
from datetime import datetime, timezone
from typing import Optional

from pymongo import ASCENDING
from pymongo.errors import DuplicateKeyError

from src import config
from src.persistence.client import get_db
from src.persistence.models import JobExecution, JobStatus, ScheduledJob

logger = logging.getLogger(__name__)


def _jobs_col():
    return get_db()[config.MONGO_COLLECTION_SCHEDULED_JOBS]


def _exec_col():
    return get_db()[config.MONGO_COLLECTION_JOB_EXECUTIONS]


def ensure_indexes() -> None:
    """Create required indexes — idempotent, safe to call on every startup."""
    _exec_col().create_index(
        [("job_id", ASCENDING), ("scheduled_fire_time", ASCENDING)],
        unique=True,
        name="job_fire_time_unique",
    )
    _jobs_col().create_index([("enabled", ASCENDING)], name="enabled_idx")
    _jobs_col().create_index([("chat_id", ASCENDING)], name="chat_id_idx")
    logger.debug("Job store indexes ensured.")


# ── Scheduled Jobs ────────────────────────────────────────────────────────────


def create_job(job: ScheduledJob) -> str:
    _jobs_col().insert_one(job.model_dump(by_alias=True))
    logger.info("Created scheduled job '%s' (%s).", job.name, job.id)
    return job.id


def upsert_job(job: ScheduledJob) -> None:
    """Insert or update a job by its ID — used for config-file-sourced jobs."""
    doc = job.model_dump(by_alias=True)
    updatable = {k: v for k, v in doc.items() if k not in ("_id", "created_at")}
    _jobs_col().update_one(
        {"_id": job.id},
        {"$set": updatable, "$setOnInsert": {"created_at": doc["created_at"]}},
        upsert=True,
    )
    logger.debug("Upserted config job '%s' (%s).", job.name, job.id)


def get_job(job_id: str) -> Optional[ScheduledJob]:
    doc = _jobs_col().find_one({"_id": job_id})
    return ScheduledJob(**doc) if doc else None


def list_jobs(chat_id: Optional[int] = None, enabled_only: bool = True) -> list[ScheduledJob]:
    query: dict = {}
    if enabled_only:
        query["enabled"] = True
    if chat_id is not None:
        query["chat_id"] = chat_id
    return [ScheduledJob(**doc) for doc in _jobs_col().find(query)]


def disable_job(job_id: str) -> bool:
    result = _jobs_col().update_one(
        {"_id": job_id},
        {"$set": {"enabled": False, "updated_at": datetime.now(timezone.utc)}},
    )
    return result.modified_count > 0


def update_last_run(
    job_id: str, run_at: datetime, next_run_at: Optional[datetime] = None
) -> None:
    fields: dict = {"last_run_at": run_at, "updated_at": datetime.now(timezone.utc)}
    if next_run_at is not None:
        fields["next_run_at"] = next_run_at
    _jobs_col().update_one({"_id": job_id}, {"$set": fields})


# ── Job Executions ────────────────────────────────────────────────────────────


def try_claim(
    job_id: str,
    job_name: str,
    chat_id: int,
    fire_time: datetime,
    instance_id: str,
) -> Optional[JobExecution]:
    """Atomically claim a job execution slot via unique index.

    Returns the new JobExecution on success, or None if another instance already
    claimed this (job_id, fire_time) pair.
    """
    execution = JobExecution(
        job_id=job_id,
        job_name=job_name,
        chat_id=chat_id,
        scheduled_fire_time=fire_time,
        claimed_by=instance_id,
    )
    try:
        _exec_col().insert_one(execution.model_dump(by_alias=True))
        logger.info(
            "Claimed execution for job '%s' (exec=%s, instance=%s).",
            job_name,
            execution.id,
            instance_id,
        )
        return execution
    except DuplicateKeyError:
        logger.debug("Job '%s' at %s already claimed by another instance.", job_name, fire_time)
        return None


def update_execution(
    execution_id: str,
    status: JobStatus,
    task_id: Optional[str] = None,
    result: Optional[str] = None,
    error: Optional[str] = None,
    started_at: Optional[datetime] = None,
    completed_at: Optional[datetime] = None,
) -> None:
    fields: dict = {"status": status.value}
    if task_id is not None:
        fields["task_id"] = task_id
    if result is not None:
        fields["result"] = result
    if error is not None:
        fields["error"] = error
    if started_at is not None:
        fields["started_at"] = started_at
    if completed_at is not None:
        fields["completed_at"] = completed_at
    _exec_col().update_one({"_id": execution_id}, {"$set": fields})
