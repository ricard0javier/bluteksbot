"""MongoDB singleton client — lazy initialisation via get_client()."""
import logging
from pymongo import MongoClient
from pymongo.database import Database
from pymongo import ASCENDING

from src import config

_client: MongoClient | None = None
logger = logging.getLogger(__name__)

def setup_indexes() -> None:
    logger.info("Setting up indexes for MongoDB client.")
    indexes = [
        {
            "collection": config.MONGO_COLLECTION_IDEMPOTENCY,
            "key": [("causationId", ASCENDING)],
            "unique": True,
            "name": "causationId_1",
        },
        {
            "collection": config.MONGO_COLLECTION_TASKS,
            "key": [("chat_id", 1), ("status", 1), ("created_at", -1)],
            "name": "list_running_idx",
        },
        {   "collection": config.MONGO_COLLECTION_SCHEDULED_JOBS,
            "key": [("job_id", ASCENDING), ("scheduled_fire_time", ASCENDING)],
            "name": "job_fire_time_unique",
        },
        {
            "collection": config.MONGO_COLLECTION_SCHEDULED_JOBS,
            "key": [("enabled", ASCENDING)],
            "name": "enabled_idx",
        },
        {
            "collection": config.MONGO_COLLECTION_SCHEDULED_JOBS,
            "key": [("chat_id", ASCENDING)],
            "name": "chat_id_idx",
        }
    ]
    for index_definition in indexes:
        get_db()[index_definition["collection"]].create_index(
            index_definition["key"],
            unique=index_definition.get("unique", False),
            name=index_definition["name"],
        )
        logger.info("Index %s created for collection %s.", index_definition["name"], index_definition["collection"])

def get_client() -> MongoClient:
    global _client
    if _client is None:
        logger.info("Initialising MongoDB client at %s.", config.MONGO_URI)
        _client = MongoClient(config.MONGO_URI)
    return _client


def get_db() -> Database:
    return get_client()[config.MONGO_DB]


def close_client() -> None:
    global _client
    if _client:
        _client.close()
        _client = None
        logger.info("MongoDB client closed.")


