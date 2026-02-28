"""Dead Letter Queue — routes unrecoverable messages with error metadata."""
import logging
from datetime import datetime, timezone
from typing import Any

from src import config
from src.persistence.client import get_db

logger = logging.getLogger(__name__)


def send_to_dlq(original_message: dict[str, Any], error: Exception) -> None:
    doc = {
        "original_message": original_message,
        "error_type": type(error).__name__,
        "error_message": str(error),
        "failed_at": datetime.now(timezone.utc),
    }
    get_db()[config.MONGO_COLLECTION_DLQ].insert_one(doc)
    logger.warning("Message routed to DLQ: %s", type(error).__name__, exc_info=True)
