"""Immutable event store — append-only writes to MongoDB."""
import logging

from src import config
from src.persistence.client import get_db
from src.persistence.models import Event

logger = logging.getLogger(__name__)


def append(event: Event) -> None:
    """Persist an event; raises on failure (caller decides DLQ routing)."""
    db = get_db()
    doc = event.model_dump(by_alias=True)
    db[config.MONGO_COLLECTION_EVENTS].insert_one(doc)
    logger.debug("Event stored: %s / %s", event.eventType, event.id)
