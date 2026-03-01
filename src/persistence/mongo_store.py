"""MongoDB-backed LangGraph BaseStore for LangMem long-term memory.

Stores namespaced key-value documents with optional vector-similarity search
using the same cosine-similarity pipeline as memory_store.py.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from pymongo.collection import Collection

from src import config
from src.embeddings.client import embed

logger = logging.getLogger(__name__)

try:
    from langgraph.store.base import BaseStore, GetOp, Item, ListNamespacesOp, Op, PutOp, Result, SearchItem, SearchOp
except ImportError as _e:  # pragma: no cover
    raise ImportError("langgraph>=1.0.10 is required: pip install -U langgraph") from _e


class MongoDBStore(BaseStore):
    """LangGraph BaseStore implementation backed by MongoDB.

    Each item is stored as a document with the schema:
        { namespace: [...], key: str, value: dict, embedding: [float], created_at, updated_at }

    Vector search uses in-pipeline cosine similarity — compatible with any
    MongoDB deployment (no Atlas Vector Search required).
    """

    def __init__(self, collection: Collection) -> None:
        self._col = collection
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        self._col.create_index([("namespace", 1), ("key", 1)], unique=True)

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _ns_key(namespace: tuple[str, ...]) -> list[str]:
        return list(namespace)

    def _to_item(self, doc: dict) -> Item:
        return Item(
            namespace=tuple(doc["namespace"]),
            key=doc["key"],
            value=doc.get("value", {}),
            created_at=doc.get("created_at", datetime.now(timezone.utc)),
            updated_at=doc.get("updated_at", datetime.now(timezone.utc)),
        )

    def _to_search_item(self, doc: dict, score: float = 1.0) -> SearchItem:
        return SearchItem(
            namespace=tuple(doc["namespace"]),
            key=doc["key"],
            value=doc.get("value", {}),
            created_at=doc.get("created_at", datetime.now(timezone.utc)),
            updated_at=doc.get("updated_at", datetime.now(timezone.utc)),
            score=score,
        )

    # ── Sync implementation ───────────────────────────────────────────────────

    def put(
        self,
        namespace: tuple[str, ...],
        key: str,
        value: dict[str, Any],
        index: Optional[list[str]] = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        embedding: list[float] = []
        if index:
            text_parts = [str(value.get(f, "")) for f in index if value.get(f)]
            if text_parts:
                try:
                    embedding = embed(" ".join(text_parts))
                except Exception:
                    logger.warning("Embedding generation failed for store put.", exc_info=True)

        self._col.update_one(
            {"namespace": self._ns_key(namespace), "key": key},
            {
                "$set": {
                    "value": value,
                    "embedding": embedding,
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )

    def get(self, namespace: tuple[str, ...], key: str) -> Optional[Item]:
        doc = self._col.find_one({"namespace": self._ns_key(namespace), "key": key})
        return self._to_item(doc) if doc else None

    @staticmethod
    def _namespace_prefix_match(namespace_prefix: tuple[str, ...]) -> dict[str, Any]:
        """Build a match filter that enforces ordered prefix on the namespace array."""
        return {f"namespace.{i}": part for i, part in enumerate(namespace_prefix)}

    def search(
        self,
        namespace_prefix: tuple[str, ...],
        *,
        query: Optional[str] = None,
        limit: int = 10,
        filter: Optional[dict[str, Any]] = None,
        offset: int = 0,
    ) -> list[SearchItem]:
        match: dict[str, Any] = self._namespace_prefix_match(namespace_prefix) if namespace_prefix else {}
        if filter:
            for k, v in filter.items():
                match[f"value.{k}"] = v

        if query:
            try:
                query_vec = embed(query)
                pipeline: list[dict] = [
                    {"$match": match},
                    {
                        "$addFields": {
                            "score": {
                                "$let": {
                                    "vars": {
                                        "dot": {
                                            "$reduce": {
                                                "input": {"$zip": {"inputs": ["$embedding", query_vec]}},
                                                "initialValue": 0.0,
                                                "in": {
                                                    "$add": [
                                                        "$$value",
                                                        {
                                                            "$multiply": [
                                                                {"$arrayElemAt": ["$$this", 0]},
                                                                {"$arrayElemAt": ["$$this", 1]},
                                                            ]
                                                        },
                                                    ]
                                                },
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
                    {"$skip": offset},
                    {"$limit": limit},
                ]
                docs = list(self._col.aggregate(pipeline))
                return [self._to_search_item(d, d.get("score", 1.0)) for d in docs]
            except Exception:
                logger.warning("Vector search failed; falling back to prefix match.", exc_info=True)

        docs = list(self._col.find(match).skip(offset).limit(limit))
        return [self._to_search_item(d) for d in docs]

    def delete(self, namespace: tuple[str, ...], key: str) -> None:
        self._col.delete_one({"namespace": self._ns_key(namespace), "key": key})

    def list_namespaces(
        self,
        *,
        prefix: Optional[tuple[str, ...]] = None,
        suffix: Optional[tuple[str, ...]] = None,
        max_depth: Optional[int] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[tuple[str, ...]]:
        match: dict[str, Any] = self._namespace_prefix_match(prefix) if prefix else {}
        pipeline: list[dict] = [
            {"$match": match},
            {"$group": {"_id": "$namespace"}},
            {"$skip": offset},
            {"$limit": limit},
        ]
        results = list(self._col.aggregate(pipeline))
        namespaces = [tuple(r["_id"]) for r in results]
        if suffix:
            namespaces = [ns for ns in namespaces if ns[-len(suffix):] == suffix]
        if max_depth is not None:
            namespaces = [ns[:max_depth] for ns in namespaces]
            namespaces = list(dict.fromkeys(namespaces))
        return namespaces

    # ── Async wrappers ────────────────────────────────────────────────────────

    async def aput(
        self,
        namespace: tuple[str, ...],
        key: str,
        value: dict[str, Any],
        index: Optional[list[str]] = None,
    ) -> None:
        await asyncio.to_thread(self.put, namespace, key, value, index)

    async def aget(self, namespace: tuple[str, ...], key: str) -> Optional[Item]:
        return await asyncio.to_thread(self.get, namespace, key)

    async def asearch(
        self,
        namespace_prefix: tuple[str, ...],
        *,
        query: Optional[str] = None,
        limit: int = 10,
        filter: Optional[dict[str, Any]] = None,
        offset: int = 0,
    ) -> list[SearchItem]:
        return await asyncio.to_thread(
            self.search, namespace_prefix, query=query, limit=limit, filter=filter, offset=offset
        )

    async def adelete(self, namespace: tuple[str, ...], key: str) -> None:
        await asyncio.to_thread(self.delete, namespace, key)

    async def alist_namespaces(
        self,
        *,
        prefix: Optional[tuple[str, ...]] = None,
        suffix: Optional[tuple[str, ...]] = None,
        max_depth: Optional[int] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[tuple[str, ...]]:
        return await asyncio.to_thread(
            self.list_namespaces,
            prefix=prefix,
            suffix=suffix,
            max_depth=max_depth,
            limit=limit,
            offset=offset,
        )

    # ── Batch API (required by langgraph BaseStore) ───────────────────────────

    def batch(self, ops: Iterable[Op]) -> list[Result]:
        results: list[Result] = []
        for op in ops:
            if isinstance(op, GetOp):
                results.append(self.get(op.namespace, op.key))
            elif isinstance(op, PutOp):
                self.put(op.namespace, op.key, op.value, op.index)
                results.append(None)
            elif isinstance(op, SearchOp):
                results.append(
                    self.search(
                        op.namespace_prefix,
                        query=op.query,
                        limit=op.limit,
                        filter=op.filter,
                        offset=op.offset,
                    )
                )
            elif isinstance(op, ListNamespacesOp):
                prefix = getattr(op, "prefix", None) or getattr(op, "match_conditions", [None])[0]
                results.append(
                    self.list_namespaces(
                        prefix=prefix,
                        max_depth=getattr(op, "max_depth", None),
                        limit=getattr(op, "limit", 100),
                        offset=getattr(op, "offset", 0),
                    )
                )
            else:
                results.append(None)
        return results

    async def abatch(self, ops: Iterable[Op]) -> list[Result]:
        return await asyncio.to_thread(self.batch, list(ops))
