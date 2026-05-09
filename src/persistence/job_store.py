"""Job store — MongoDB CRUD for scheduled_jobs and job_executions collections."""

import logging
from datetime import UTC, datetime

from pymongo.errors import DuplicateKeyError

from src import config
from src.persistence.client import get_db
from src.persistence.models import JobExecution, JobStatus, ScheduledJob

logger = logging.getLogger(__name__)


def _jobs_col():
    return get_db()[config.MONGO_COLLECTION_SCHEDULED_JOBS]


def _exec_col():
    return get_db()[config.MONGO_COLLECTION_JOB_EXECUTIONS]


# ── Scheduled Jobs ────────────────────────────────────────────────────────────


def create_job(job: ScheduledJob) -> str:
    _jobs_col().insert_one(job.model_dump(by_alias=True))
    logger.info("Created scheduled job '%s' (%s).", job.name, job.id)
    return job.id


def upsert_job(job: ScheduledJob) -> None:
    """Insert job if missing, preserving existing records — used for config-file seeding."""
    doc = job.model_dump(by_alias=True)
    result = _jobs_col().update_one(
        {"_id": job.id},
        {"$setOnInsert": doc},
        upsert=True,
    )
    if result.upserted_id:
        logger.info("Inserted config job '%s' (%s).", job.name, job.id)
    else:
        logger.debug("Config job '%s' (%s) already exists, preserving.", job.name, job.id)


def get_job(job_id: str) -> ScheduledJob | None:
    doc = _jobs_col().find_one({"_id": job_id})
    return ScheduledJob(**doc) if doc else None


def list_jobs(chat_id: str | None = None, enabled_only: bool = True) -> list[ScheduledJob]:
    query: dict = {}
    if enabled_only:
        query["enabled"] = True
    if chat_id is not None:
        query["chat_id"] = chat_id
    return [ScheduledJob(**doc) for doc in _jobs_col().find(query)]


def disable_job(job_id: str) -> bool:
    result = _jobs_col().update_one(
        {"_id": job_id},
        {"$set": {"enabled": False, "updated_at": datetime.now(UTC)}},
    )
    return result.modified_count > 0


def enable_job(job_id: str) -> bool:
    result = _jobs_col().update_one(
        {"_id": job_id},
        {"$set": {"enabled": True, "updated_at": datetime.now(UTC)}},
    )
    return result.modified_count > 0


def update_job_config(
    job_id: str,
    name: str | None = None,
    cron_expr: str | None = None,
    task_prompt: str | None = None,
    chat_id: str | None = None,
    enabled: bool | None = None,
) -> bool:
    """Update job configuration fields. Returns True if job was found and updated."""
    fields: dict = {"updated_at": datetime.now(UTC)}
    if name is not None:
        fields["name"] = name
    if cron_expr is not None:
        fields["cron_expr"] = cron_expr
    if task_prompt is not None:
        fields["task_prompt"] = task_prompt
    if chat_id is not None:
        fields["chat_id"] = chat_id
    if enabled is not None:
        fields["enabled"] = enabled
    result = _jobs_col().update_one({"_id": job_id}, {"$set": fields})
    if result.matched_count > 0:
        logger.info("Updated job config '%s'.", job_id)
    return result.matched_count > 0


def update_last_run(job_id: str, run_at: datetime, next_run_at: datetime | None = None) -> None:
    fields: dict = {"last_run_at": run_at, "updated_at": datetime.now(UTC)}
    if next_run_at is not None:
        fields["next_run_at"] = next_run_at
    _jobs_col().update_one({"_id": job_id}, {"$set": fields})


# ── Job Executions ────────────────────────────────────────────────────────────


def try_claim(
    job_id: str,
    job_name: str,
    chat_id: str,
    fire_time: datetime,
    instance_id: str,
) -> JobExecution | None:
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
    task_id: str | None = None,
    result: str | None = None,
    error: str | None = None,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
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
