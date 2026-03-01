"""MongoDB-backed BackendProtocol for conversation history offloading.

Implements the subset of BackendProtocol used by SummarizationMiddleware
(download_files, write, edit) plus glob_info/ls_info so CompositeBackend
can enumerate virtual files without raising NotImplementedError.
"""

import asyncio
import fnmatch
import logging
from datetime import UTC, datetime

from deepagents.backends.protocol import (
    BackendProtocol,
    EditResult,
    FileDownloadResponse,
    FileInfo,
    WriteResult,
)
from pymongo.collection import Collection

logger = logging.getLogger(__name__)


class MongoDBBackend(BackendProtocol):
    """Stores conversation history documents in a MongoDB collection.

    Document schema:
        { "_id": "<path>", "content": "<markdown>", "created_at": "<iso>", "updated_at": "<iso>" }
    """

    def __init__(self, collection: Collection) -> None:
        self._col = collection

    # ── download ──────────────────────────────────────────────────────────────

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        results: list[FileDownloadResponse] = []
        for path in paths:
            doc = self._col.find_one({"_id": path})
            if doc and doc.get("content") is not None:
                results.append(FileDownloadResponse(path=path, content=doc["content"].encode("utf-8")))
            else:
                results.append(FileDownloadResponse(path=path, content=None, error="file_not_found"))
        return results

    async def adownload_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        return await asyncio.to_thread(self.download_files, paths)

    # ── write (new document) ──────────────────────────────────────────────────

    def write(self, file_path: str, content: str) -> WriteResult:
        now = datetime.now(UTC).isoformat()
        try:
            self._col.insert_one({"_id": file_path, "content": content, "created_at": now, "updated_at": now})
            logger.debug("MongoDBBackend: wrote %s (%d chars)", file_path, len(content))
            return WriteResult(path=file_path, files_update=None)
        except Exception as exc:  # noqa: BLE001
            return WriteResult(error=str(exc))

    async def awrite(self, file_path: str, content: str) -> WriteResult:
        return await asyncio.to_thread(self.write, file_path, content)

    # ── edit (replace entire content) ─────────────────────────────────────────

    def edit(
        self,
        file_path: str,
        old_string: str,  # noqa: ARG002  – full content replacement, old value unused
        new_string: str,
        replace_all: bool = False,  # noqa: FBT001, FBT002
    ) -> EditResult:
        now = datetime.now(UTC).isoformat()
        try:
            result = self._col.update_one({"_id": file_path}, {"$set": {"content": new_string, "updated_at": now}})
            if result.matched_count == 0:
                return EditResult(error="file_not_found")
            logger.debug("MongoDBBackend: updated %s (%d chars)", file_path, len(new_string))
            return EditResult(path=file_path, files_update=None, occurrences=1)
        except Exception as exc:  # noqa: BLE001
            return EditResult(error=str(exc))

    async def aedit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,  # noqa: FBT001, FBT002
    ) -> EditResult:
        return await asyncio.to_thread(self.edit, file_path, old_string, new_string, replace_all)

    # ── listing ───────────────────────────────────────────────────────────────

    def ls_info(self, path: str) -> list[FileInfo]:
        """Return all stored paths that are direct children of *path*."""
        prefix = path.rstrip("/") + "/"
        docs = self._col.find({"_id": {"$regex": f"^{prefix}[^/]+$"}}, {"updated_at": 1, "content": 1})
        return [
            FileInfo(
                path=doc["_id"],
                is_dir=False,
                size=len((doc.get("content") or "").encode()),
                modified_at=doc.get("updated_at", ""),
            )
            for doc in docs
        ]

    async def als_info(self, path: str) -> list[FileInfo]:
        return await asyncio.to_thread(self.ls_info, path)

    def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        """Return all stored paths matching *pattern* (fnmatch-style)."""
        docs = self._col.find({}, {"updated_at": 1, "content": 1})
        return [
            FileInfo(
                path=doc["_id"],
                is_dir=False,
                size=len((doc.get("content") or "").encode()),
                modified_at=doc.get("updated_at", ""),
            )
            for doc in docs
            if fnmatch.fnmatch(doc["_id"], pattern)
        ]

    async def aglob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        return await asyncio.to_thread(self.glob_info, pattern, path)
