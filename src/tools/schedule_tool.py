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
    """Schedule a recurring autonomous cron job that runs without user interaction.

    The job will execute on the given cron schedule, complete the task independently,
    and send the result (or any unrecoverable error) here via Telegram.

    Args:
        name: Short human-readable job name (e.g. "daily-report").
        cron_expr: Standard 5-field cron expression, e.g. "0 8 * * *" for 8 AM daily,
                   "*/30 * * * *" for every 30 minutes, "0 9 * * 1" for Mondays at 9 AM.
        task_prompt: Full description of the task the agent will execute on each run.
                     Be specific — this prompt is the entire context the agent receives.
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
    """List all scheduled cron jobs for this chat (both enabled and disabled)."""
    chat_id = _chat_id(config)
    jobs = job_store.list_jobs(chat_id=chat_id, enabled_only=False)
    if not jobs:
        return "No scheduled jobs found for this chat."

    lines = ["*Scheduled jobs:*"]
    for j in jobs:
        state = "enabled" if j.enabled else "disabled"
        last = j.last_run_at.strftime("%Y-%m-%d %H:%M UTC") if j.last_run_at else "never"
        lines.append(
            f"• `{j.id[:8]}` *{j.name}* — `{j.cron_expr}` | {state} | last run: {last}"
        )
    return "\n".join(lines)


@tool
def cancel_cron_job(job_id: str, config: RunnableConfig) -> str:
    """Cancel (disable) a scheduled cron job by its ID.

    The job record is kept in MongoDB for history but will no longer fire.
    Use list_cron_jobs to find the job ID.

    Args:
        job_id: The full job ID or the first 8 characters shown by list_cron_jobs.
    """
    from src.scheduler.service import get_scheduler

    chat_id = _chat_id(config)

    # Support short IDs: look up by prefix if not an exact match
    job = job_store.get_job(job_id)
    if job is None:
        jobs = job_store.list_jobs(chat_id=chat_id, enabled_only=False)
        matches = [j for j in jobs if j.id.startswith(job_id)]
        if len(matches) == 1:
            job = matches[0]
        elif len(matches) > 1:
            return f"Ambiguous ID prefix '{job_id}' matches multiple jobs. Please use the full ID."

    if job is None:
        return f"No job found with ID '{job_id}'."
    if job.chat_id != chat_id:
        return "You can only cancel your own scheduled jobs."

    job_store.disable_job(job.id)

    scheduler = get_scheduler()
    if scheduler:
        scheduler.unregister_job(job.id)

    logger.info("User cancelled job '%s' (%s, chat=%s).", job.name, job.id, chat_id)
    return f"Scheduled job *'{job.name}'* (`{job.id[:8]}`) has been cancelled."


SCHEDULE_TOOLS = [schedule_cron_job, list_cron_jobs, cancel_cron_job]
