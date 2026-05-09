"""Scheduler service — APScheduler backed by MongoDB, with distributed atomic-claim execution."""

import logging
import os
import socket
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from apscheduler.jobstores.mongodb import MongoDBJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from src import config
from src.persistence import job_store, task_store
from src.persistence.client import get_client
from src.persistence.models import BotTask, JobStatus, ScheduledJob, TaskStatus
from src.scheduler.config_loader import load_from_file
from src.telegram.producer import TelegramProducer

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

    def __init__(self, telegram_producer: TelegramProducer) -> None:
        self._telegram_producer = telegram_producer
        mongo_store = MongoDBJobStore(
            database=config.MONGO_DB,
            collection=config.MONGO_COLLECTION_APSCHEDULER,
            client=get_client(),
        )
        self._scheduler = BackgroundScheduler(
            jobstores={"default": mongo_store},
            timezone=config.SCHEDULER_TIMEZONE,
            job_defaults={
                "coalesce": True,  # fire once on restart for all missed windows
                "misfire_grace_time": 300,  # 5-min grace period after missed fire
                "max_instances": 1,
            },
        )

    def start(self) -> None:
        global _instance
        _instance = self
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

    def enable_job(self, job_id: str) -> bool:
        """Enable a job in MongoDB and register it with APScheduler. Returns False if not found."""
        if not job_store.enable_job(job_id):
            return False
        job = job_store.get_job(job_id)
        if job:
            self.register_job(job)
        return True

    def disable_job(self, job_id: str) -> bool:
        """Disable a job in MongoDB and remove it from APScheduler. Returns False if not found."""
        if not job_store.disable_job(job_id):
            return False
        self.unregister_job(job_id)
        return True

    def update_job_config(
        self,
        job_id: str,
        name: str | None = None,
        cron_expr: str | None = None,
        task_prompt: str | None = None,
        chat_id: str | None = None,
        enabled: bool | None = None,
    ) -> bool:
        """Update job config, validate cron, and re-register if enabled. Returns False if not found."""
        if cron_expr is not None:
            try:
                CronTrigger.from_crontab(cron_expr, timezone=config.SCHEDULER_TIMEZONE)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"Invalid cron expression: {exc}") from exc

        if not job_store.update_job_config(job_id, name, cron_expr, task_prompt, chat_id, enabled):
            return False

        job = job_store.get_job(job_id)
        if job is None:
            return False

        if job.enabled:
            self.register_job(job)
        else:
            self.unregister_job(job_id)

        return True

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
                    logger.info(
                        "Removed stale APScheduler entry for disabled job '%s'.", aps_job.name
                    )

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

        job = job_store.get_job(job_id)
        if not job or not job.enabled:
            logger.info("Job %s not found or disabled — skipping.", job_id)
            return

        fire_time = datetime.now(UTC)
        chat_id = job.chat_id
        job_id = job.id
        job_name = job.name
        job_prompt = job.task_prompt
        execution = job_store.try_claim(
            job_id=job_id,
            job_name=job_name,
            chat_id=chat_id,
            fire_time=fire_time,
            instance_id=INSTANCE_ID,
        )
        if execution is None:
            return  # another instance already claimed this firing

        try:
            now = datetime.now(UTC)
            task = BotTask(
                causation_id=f"cron-{job_id}-{now.isoformat()}",
                chat_id=chat_id,
                input=job_prompt,
                status=TaskStatus.RUNNING,
            )
            task_id = task_store.create(task)
            job_store.update_execution(
                execution.id, JobStatus.RUNNING, task_id=task_id, started_at=now
            )

            self._telegram_producer.send_message(
                chat_id,
                f"\u23f3 *Scheduled job '{job_name}' started*",
            )

            thread_id = f"cron-{job_id}"  # isolated LangGraph context per job

            status_message_text = f"\u23f3 Working on scheduled task '{job_name}' \u2026"
            reply = self._telegram_producer.respond(
                task_id=execution.task_id,
                chat_id=job.chat_id,
                raw={
                    "text": job_prompt,
                },
                thread_id=thread_id,
                status_message_text=status_message_text,
            )

            job_store.update_execution(
                execution.id,
                JobStatus.DONE,
                result=reply[:500],
                completed_at=datetime.now(UTC),
            )
            task_store.update_status(task_id, TaskStatus.DONE, result=reply[:500])
            logger.info("Scheduled job '%s' (%s) completed.", job_name, job_id)
        except InterruptedError:
            logger.info("Scheduled job '%s' (%s) cancelled.", job_name, job_id)
            job_store.update_execution(
                execution.id,
                JobStatus.FAILED,
                error="Task was cancelled.",
                completed_at=datetime.now(UTC),
            )
        except Exception as exc:
            logger.error("Scheduled job '%s' (%s) failed: %s", job_name, job_id, exc, exc_info=True)
            err_preview = str(exc)[:300]
            try:
                self._telegram_producer.send_message(
                    chat_id,
                    f"\u26a0\ufe0f *Scheduled job '{job_name}' failed*",
                )
                self._telegram_producer.send_message(chat_id, err_preview)
            except Exception:
                logger.warning("Could not send error notification to chat=%s.", chat_id)
            task_store.update_status(task_id, TaskStatus.FAILED, error=str(exc))
            job_store.update_execution(
                execution.id,
                JobStatus.FAILED,
                error=str(exc)[:500],
                completed_at=datetime.now(UTC),
            )
        job_store.update_last_run(job.id, fire_time)


def _execute_job(job_id: str) -> None:
    """APScheduler callback — must be module-level so APScheduler can serialize it by path."""
    service = _instance
    if service is None:
        logger.error("SchedulerService not initialized — cannot execute job %s.", job_id)
        return
    service._run_job(job_id)
