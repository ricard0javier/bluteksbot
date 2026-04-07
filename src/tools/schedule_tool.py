"""LangChain tools for scheduling, listing, and cancelling cron jobs via the agent."""

import logging

from langchain.tools import tool
from langchain_core.runnables import RunnableConfig

from src.persistence import job_store
from src.persistence.models import ScheduledJob

logger = logging.getLogger(__name__)


def _chat_id(config: RunnableConfig) -> int:
    """Extract the Telegram chat_id from the LangGraph thread_id injected via configurable."""
    return int(config["configurable"]["thread_id"])


@tool
def schedule_cron_job(
    name: str,
    cron_expr: str,
    task_prompt: str,
    config: RunnableConfig,
) -> str:
    """
    Create a recurring job: on each cron tick an agent runs task_prompt autonomously and reports back to this chat.
    Use when the user wants repeated, time-based automation (e.g. daily/weekly reports, periodic checks). Pass a standard 5-field cron_expr (minute hour day-of-month month day-of-week) and a self-contained task_prompt—the scheduled run only sees that prompt. Do not use for one-shot work in this thread, or to list/cancel/enable jobs—use list_cron_jobs, cancel_cron_job, or enable_cron_job.
    """
    from src.scheduler.service import get_scheduler

    chat_id = _chat_id(config)
    job = ScheduledJob(
        name=name,
        cron_expr=cron_expr,
        task_prompt=task_prompt,
        chat_id=chat_id,
        enabled=True,
        created_by=f"user:{chat_id}",
    )
    job_store.create_job(job)

    scheduler = get_scheduler()
    if scheduler:
        scheduler.register_job(job)
        status = "active immediately"
    else:
        status = "will activate on next restart"

    logger.info("User scheduled job '%s' (id=%s, cron=%s).", name, job.id, cron_expr)
    return (
        f"Scheduled job *'{name}'* created ({status}).\n"
        f"ID: `{job.id}`\n"
        f"Schedule: `{cron_expr}`\n"
        f"I will run autonomously and notify you here when each run completes."
    )


@tool
def list_cron_jobs(config: RunnableConfig) -> str:
    """
    List all cron jobs for this chat (enabled and disabled) with short IDs, schedules, and last run.
    Use when the user asks what is scheduled, needs a job_id for cancel/enable, or wants status. Do not use to create, stop, or resume jobs—use schedule_cron_job, cancel_cron_job, or enable_cron_job.
    """
    chat_id = _chat_id(config)
    jobs = job_store.list_jobs(chat_id=chat_id, enabled_only=False)
    if not jobs:
        return "No scheduled jobs found for this chat."

    lines = ["*Scheduled jobs:*"]
    for j in jobs:
        state = "enabled" if j.enabled else "disabled"
        last = (
            j.last_run_at.strftime("%Y-%m-%d %H:%M UTC") if j.last_run_at else "never"
        )
        lines.append(
            f"• `{j.id[:8]}` *{j.name}* — `{j.cron_expr}` | {state} | last run: {last}"
        )
    return "\n".join(lines)


def _resolve_job(job_id: str, chat_id: int):
    """Return a ScheduledJob by exact or prefix ID, scoped to chat_id. Returns (job, error_str)."""
    job = job_store.get_job(job_id)
    if job is None:
        jobs = job_store.list_jobs(chat_id=chat_id, enabled_only=False)
        matches = [j for j in jobs if j.id.startswith(job_id)]
        if len(matches) == 1:
            job = matches[0]
        elif len(matches) > 1:
            return (
                None,
                f"Ambiguous ID prefix '{job_id}' matches multiple jobs. Use the full ID.",
            )
    if job is None:
        return None, f"No job found with ID '{job_id}'."
    if job.chat_id != chat_id:
        return None, "You can only manage your own scheduled jobs."
    return job, None


@tool
def cancel_cron_job(job_id: str, config: RunnableConfig) -> str:
    """
    Disable a job by full UUID or the 8-character prefix from list_cron_jobs; it stops firing but stays listed.
    Use when the user wants to stop or turn off a recurring job. Prefer list_cron_jobs first if job_id is unknown. Do not use to create jobs or turn them back on—use schedule_cron_job or enable_cron_job.
    """
    from src.scheduler.service import get_scheduler

    chat_id = _chat_id(config)
    job, err = _resolve_job(job_id, chat_id)
    if err:
        return err

    scheduler = get_scheduler()
    ok = scheduler.disable_job(job.id) if scheduler else job_store.disable_job(job.id)
    if not ok:
        return (
            f"Job '{job.name}' could not be disabled (already disabled or not found)."
        )

    logger.info("User disabled job '%s' (%s, chat=%s).", job.name, job.id, chat_id)
    return f"Scheduled job *'{job.name}'* (`{job.id[:8]}`) has been disabled."


@tool
def enable_cron_job(job_id: str, config: RunnableConfig) -> str:
    """
    Re-enable a disabled job by full UUID or 8-character prefix from list_cron_jobs; it resumes on the same schedule.
    Use when the user wants a paused job to run again. Prefer list_cron_jobs first if job_id is unknown. Do not use to create new schedules or to stop jobs—use schedule_cron_job or cancel_cron_job.
    """
    from src.scheduler.service import get_scheduler

    chat_id = _chat_id(config)
    job, err = _resolve_job(job_id, chat_id)
    if err:
        return err

    scheduler = get_scheduler()
    ok = scheduler.enable_job(job.id) if scheduler else job_store.enable_job(job.id)
    if not ok:
        return f"Job '{job.name}' could not be enabled (not found)."

    logger.info("User enabled job '%s' (%s, chat=%s).", job.name, job.id, chat_id)
    return f"Scheduled job *'{job.name}'* (`{job.id[:8]}`) is now enabled and active."


SCHEDULE_TOOLS = [schedule_cron_job, list_cron_jobs, cancel_cron_job, enable_cron_job]
