"""Long-term memory store — vector similarity search over conversation history."""
import logging
from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING
from pymongo.collection import Collection

from src import config
from src.persistence.client import get_db

logger = logging.getLogger(__name__)

_INDEX_CREATED = False


def _collection() -> Collection:
    return get_db()[config.MONGO_COLLECTION_MEMORY]


def _ensure_index() -> None:
    global _INDEX_CREATED
    if not _INDEX_CREATED:
        _collection().create_index([("user_id", ASCENDING), ("created_at", ASCENDING)])
        _INDEX_CREATED = True


def save_memory(
    user_id: int,
    content: str,
    embedding: list[float],
    metadata: dict[str, Any] | None = None,
) -> None:
    _ensure_index()
    _collection().insert_one(
        {
            "user_id": user_id,
            "content": content,
            "embedding": embedding,
            "metadata": metadata or {},
            "created_at": datetime.now(timezone.utc),
        }
    )
    logger.debug("Memory saved for user_id=%s.", user_id)


def search_memory(
    user_id: int,
    query_embedding: list[float],
    top_k: int = config.MEMORY_TOP_K,
) -> list[dict[str, Any]]:
    """Cosine similarity search using MongoDB vector search (Atlas) or fallback linear scan."""
    pipeline = [
        {"$match": {"user_id": user_id}},
        {
            "$addFields": {
                "score": {
                    "$let": {
                        "vars": {
                            "dot": {
                                "$reduce": {
                                    "input": {"$zip": {"inputs": ["$embedding", query_embedding]}},
                                    "initialValue": 0.0,
                                    "in": {"$add": ["$$value", {"$multiply": [{"$arrayElemAt": ["$$this", 0]}, {"$arrayElemAt": ["$$this", 1]}]}]},
                                }
                            }
                        },
                        "in": "$$dot",
                    }
                }
            }
        },
        {"$match": {"score": {"$gte": config.MEMORY_SCORE_THRESHOLD}}},
        {"$sort": {"score": -1}},
        {"$limit": top_k},
        {"$project": {"embedding": 0}},
    ]
    results = list(_collection().aggregate(pipeline))
    logger.debug("Memory search returned %d results for user_id=%s.", len(results), user_id)
    return results
