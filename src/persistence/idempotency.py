"""Idempotency gate — skip already-processed events via causationId."""
import logging

from pymongo import ASCENDING
from pymongo.errors import DuplicateKeyError

from src import config
from src.persistence.client import get_db

logger = logging.getLogger(__name__)

_INDEX_CREATED = False


def _ensure_index() -> None:
    global _INDEX_CREATED
    if not _INDEX_CREATED:
        get_db()[config.MONGO_COLLECTION_IDEMPOTENCY].create_index(
            [("causationId", ASCENDING)], unique=True
        )
        _INDEX_CREATED = True


def is_already_processed(causation_id: str) -> bool:
    _ensure_index()
    try:
        get_db()[config.MONGO_COLLECTION_IDEMPOTENCY].insert_one({"causationId": causation_id})
        return False
    except DuplicateKeyError:
        logger.info("Duplicate causationId=%s — skipping.", causation_id)
        return True
