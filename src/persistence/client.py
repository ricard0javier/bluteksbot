"""MongoDB singleton client — lazy initialisation via get_client()."""
import logging
from pymongo import MongoClient
from pymongo.database import Database

from src import config

_client: MongoClient | None = None
logger = logging.getLogger(__name__)


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


