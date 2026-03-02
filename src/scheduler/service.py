"""Scheduler service — APScheduler backed by MongoDB, with distributed atomic-claim execution."""
import logging
import os
import socket
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import telebot
from apscheduler.jobstores.mongodb import MongoDBJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from src import config
from src.persistence import job_store
from src.persistence.client import get_client
from src.persistence.models import JobStatus, ScheduledJob
from src.scheduler.config_loader import load_from_file

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Unique identity for this process instance — used in the atomic claim field.
INSTANCE_ID = f"{socket.gethostname()}:{os.getpid()}"

# Module-level singleton — accessed by the APScheduler callback and by tools.
_instance: "SchedulerService | None" = None


def get_scheduler() -> "SchedulerService | None":
    return _instance


class SchedulerService:
    """Manages APScheduler lifecycle and job execution with distributed deduplication."""

    def __init__(self, bot: telebot.TeleBot) -> None:
        self._bot = bot
        mongo_store = MongoDBJobStore(
            database=config.MONGO_DB,
            collection=config.MONGO_COLLECTION_APSCHEDULER,
            client=get_client(),
        )
        self._scheduler = BackgroundScheduler(
            jobstores={"default": mongo_store},
            timezone=config.SCHEDULER_TIMEZONE,
            job_defaults={
                "coalesce": True,        # fire once on restart for all missed windows
                "misfire_grace_time": 300,  # 5-min grace period after missed fire
                "max_instances": 1,
            },
        )

    def start(self) -> None:
        global _instance
        _instance = self
        job_store.ensure_indexes()
        config_jobs = load_from_file()
        self._scheduler.start()
        self._load_all_jobs(extra_jobs=config_jobs)
        logger.info("SchedulerService started (instance=%s).", INSTANCE_ID)

    def stop(self) -> None:
        self._scheduler.shutdown(wait=False)
        logger.info("SchedulerService stopped.")

    def register_job(self, job: ScheduledJob) -> None:
        """Register or update a job in APScheduler. Safe to call after start()."""
        trigger = CronTrigger.from_crontab(job.cron_expr, timezone=config.SCHEDULER_TIMEZONE)
        self._scheduler.add_job(
            func=_execute_job,
            trigger=trigger,
            id=job.id,
            name=job.name,
            args=[job.id],
            replace_existing=True,
        )
        logger.info("Registered job '%s' (%s) → cron '%s'.", job.name, job.id, job.cron_expr)

    def unregister_job(self, job_id: str) -> None:
        """Remove a job from APScheduler (does not delete from MongoDB)."""
        try:
            self._scheduler.remove_job(job_id)
            logger.info("Unregistered job %s.", job_id)
        except Exception:
            pass  # already absent — fine

    def _load_all_jobs(self, extra_jobs: list[ScheduledJob] | None = None) -> None:
        """Load all enabled MongoDB jobs and register with APScheduler.

        Also removes any APScheduler entries for jobs that are now disabled or
        deleted — prevents stale firings from a prior run.
        """
        enabled_jobs = job_store.list_jobs(enabled_only=True)
        disabled_jobs = job_store.list_jobs(enabled_only=False)

        # IDs that should be active
        enabled_ids = {j.id for j in enabled_jobs}
        # IDs that exist in MongoDB but are disabled
        disabled_ids = {j.id for j in disabled_jobs if not j.enabled}

        # Remove stale APScheduler entries for disabled/deleted jobs
        for aps_job in self._scheduler.get_jobs():
            if aps_job.id not in enabled_ids:
                self._scheduler.remove_job(aps_job.id)
                if aps_job.id in disabled_ids:
                    logger.info("Removed stale APScheduler entry for disabled job '%s'.", aps_job.name)

        # Merge config-sourced jobs with DB jobs (config already upserted, avoid duplicates)
        registered_ids = {j.id for j in (extra_jobs or [])}
        all_jobs = list(extra_jobs or [])
        for job in enabled_jobs:
            if job.id not in registered_ids:
                all_jobs.append(job)
                registered_ids.add(job.id)

        for job in all_jobs:
            try:
                self.register_job(job)
            except Exception:
                logger.warning("Failed to register job '%s'.", job.name, exc_info=True)

        logger.info("SchedulerService loaded %d job(s).", len(all_jobs))

    def _run_job(self, job_id: str) -> None:
        """Claim and execute one scheduled job firing. Called from APScheduler thread."""
        from src.agent.orchestrator import Orchestrator

        job = job_store.get_job(job_id)
        if not job or not job.enabled:
            logger.info("Job %s not found or disabled — skipping.", job_id)
            return

        fire_time = datetime.now(timezone.utc)
        execution = job_store.try_claim(
            job_id=job.id,
            job_name=job.name,
            chat_id=job.chat_id,
            fire_time=fire_time,
            instance_id=INSTANCE_ID,
        )
        if execution is None:
            return  # another instance already claimed this firing

        orchestrator = Orchestrator(bot=self._bot)
        orchestrator.run_autonomous(
            task_prompt=job.task_prompt,
            chat_id=job.chat_id,
            job_id=job.id,
            job_name=job.name,
            execution_id=execution.id,
        )
        job_store.update_last_run(job.id, fire_time)


def _execute_job(job_id: str) -> None:
    """APScheduler callback — must be module-level so APScheduler can serialize it by path."""
    service = _instance
    if service is None:
        logger.error("SchedulerService not initialized — cannot execute job %s.", job_id)
        return
    service._run_job(job_id)
