"""Idempotency gate — skip already-processed events via causationId."""
import logging

from pymongo.errors import DuplicateKeyError

from src import config
from src.persistence.client import get_db

logger = logging.getLogger(__name__)

def _col():
    return get_db()[config.MONGO_COLLECTION_IDEMPOTENCY]

def is_already_processed(causation_id: str) -> bool:
    try:
        _col().insert_one({"causationId": causation_id})
        return False
    except DuplicateKeyError:
        logger.info("Duplicate causationId=%s — skipping.", causation_id)
        return True
