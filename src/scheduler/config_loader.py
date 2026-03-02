"""Scheduler config loader — parses scheduled_jobs.yaml and upserts jobs into MongoDB."""
import logging
import re
from pathlib import Path

import yaml

from src import config
from src.persistence import job_store
from src.persistence.models import ScheduledJob

logger = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _stable_id(name: str) -> str:
    """Deterministic job ID for config-sourced jobs so restarts are idempotent."""
    slug = _SLUG_RE.sub("-", name.lower()).strip("-")
    return f"config-{slug}"


def load_from_file(path: str | None = None) -> list[ScheduledJob]:
    """Parse scheduled_jobs.yaml and upsert all enabled jobs into MongoDB.

    Idempotent — safe to call on every startup. Jobs use a stable ID derived
    from their name so re-running never creates duplicates.
    """
    config_path = Path(path or config.SCHEDULER_CONFIG_FILE)
    if not config_path.exists():
        logger.info("No scheduler config file at '%s' — skipping.", config_path)
        return []

    with config_path.open() as f:
        data = yaml.safe_load(f) or {}

    loaded: list[ScheduledJob] = []
    for entry in data.get("jobs", []):
        try:
            job = ScheduledJob(
                id=_stable_id(entry["name"]),
                name=entry["name"],
                cron_expr=entry["cron"],
                task_prompt=entry["prompt"],
                chat_id=int(entry["chat_id"]),
                enabled=entry.get("enabled", True),
                created_by="config",
            )
            job_store.upsert_job(job)
            loaded.append(job)
            logger.info("Loaded config job '%s' (%s).", job.name, job.cron_expr)
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("Skipping invalid job entry %s: %s", entry, exc)

    logger.info("Config loader: %d job(s) upserted from '%s'.", len(loaded), config_path)
    return loaded
