from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass
class WebSearchResult:
    source_statuses: list[dict[str, Any]] = field(default_factory=list)
    candidates: list[dict[str, Any]] = field(default_factory=list)


def tavily_search(query: str, *, field: str = "general_web", max_results: int | None = None) -> WebSearchResult:
    api_key = os.environ.get("TAVILY_API_KEY", "").strip()
    url = "https://api.tavily.com/search"
    if not api_key:
        return WebSearchResult(
            source_statuses=[
                {
                    "source": "Tavily",
                    "status": "needs_key",
                    "queried_url": url,
                    "message": "TAVILY_API_KEY is required for advanced web search.",
                    "result_count": 0,
                }
            ]
        )

    payload = {
        "query": query,
        "search_depth": os.environ.get("AI_SCIENTIST_TAVILY_SEARCH_DEPTH", "basic"),
        "max_results": max_results or _max_results(),
        "include_raw_content": _include_raw_content(),
    }
    try:
        with httpx.Client(timeout=_timeout_seconds(), follow_redirects=True) as client:
            response = client.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
    except Exception as exc:  # pragma: no cover - network defensive path
        return WebSearchResult(
            source_statuses=[
                {
                    "source": "Tavily",
                    "status": "error",
                    "queried_url": url,
                    "message": f"Tavily search failed: {exc}",
                    "result_count": 0,
                }
            ]
        )

    if response.status_code != 200:
        return WebSearchResult(
            source_statuses=[
                {
                    "source": "Tavily",
                    "status": "error",
                    "queried_url": url,
                    "message": f"HTTP {response.status_code}",
                    "result_count": 0,
                }
            ]
        )

    data = response.json()
    candidates = [_candidate_from_tavily(item, field) for item in data.get("results", [])]
    return WebSearchResult(
        source_statuses=[
            {
                "source": "Tavily",
                "status": "queried",
                "queried_url": url,
                "message": f"Tavily web search queried for {field}: {query[:180]}",
                "result_count": len(candidates),
            }
        ],
        candidates=candidates,
    )


def _candidate_from_tavily(item: dict[str, Any], field: str) -> dict[str, Any]:
    url = item.get("url") or "https://tavily.com/"
    title = item.get("title") or "Untitled Tavily result"
    snippet = item.get("content") or ""
    raw_content = item.get("raw_content") or ""
    return {
        "candidate_id": _candidate_id(url, title),
        "source": "Tavily",
        "source_type": "web",
        "title": title,
        "url": url,
        "doi": None,
        "authors": [],
        "year": None,
        "abstract_or_snippet": snippet,
        "raw_content": _clip(raw_content, 5000),
        "web_score": _safe_float(item.get("score")),
        "field": field,
        "matched_fields": [],
        "lexical_score": 0.0,
        "embedding_similarity": None,
        "llm_score": None,
        "llm_relevance_score": None,
        "llm_relevance_reason": "",
        "visited_content_used": bool(raw_content),
        "final_score": 0.0,
        "match_classification": "unranked",
    }


def _candidate_id(url: str, title: str) -> str:
    digest = hashlib.sha1(f"{url}|{title}".encode("utf-8")).hexdigest()[:12]
    return f"tavily-{digest}"


def _max_results() -> int:
    try:
        return max(1, min(20, int(os.environ.get("AI_SCIENTIST_ADVANCED_QC_MAX_RESULTS", "10"))))
    except ValueError:
        return 10


def _timeout_seconds() -> float:
    try:
        return float(os.environ.get("AI_SCIENTIST_SOURCE_TIMEOUT_SECONDS", "6.0"))
    except ValueError:
        return 6.0


def _include_raw_content() -> bool:
    return os.environ.get("AI_SCIENTIST_TAVILY_INCLUDE_RAW_CONTENT", "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clip(text: str, limit: int) -> str:
    return " ".join(text.split())[:limit]
