"""Web search tool — Tavily v0.7+ SDK with advanced search depth."""
import logging
from functools import lru_cache
from typing import Any

from tavily import TavilyClient

from src import config

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _client() -> TavilyClient:
    return TavilyClient(config.TAVILY_API_KEY)


def web_search(query: str, max_results: int = config.WEB_SEARCH_MAX_RESULTS) -> list[dict[str, Any]]:
    """Returns list of {title, url, content} dicts; uses 'advanced' depth for quality results."""
    try:
        response = _client().search(
            query=query,
            search_depth="advanced",
            max_results=max_results,
        )
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("content", ""),
            }
            for r in response.get("results", [])
        ]
    except Exception:
        logger.error("Web search failed for query='%s'.", query, exc_info=True)
        return []
