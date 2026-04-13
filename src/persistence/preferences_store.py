"""Per-chat preference store — lightweight key/value backed by MongoDB."""

from src import config
from src.persistence.client import get_db


def _col():
    return get_db()[config.MONGO_COLLECTION_PREFERENCES]


def get_model(chat_id: str) -> str:
    doc = _col().find_one({"_id": chat_id}, {"model": 1})
    return doc["model"] if doc and "model" in doc else config.WORKER_MODEL


def set_model(chat_id: str, model: str) -> None:
    _col().update_one({"_id": chat_id}, {"$set": {"model": model}}, upsert=True)
