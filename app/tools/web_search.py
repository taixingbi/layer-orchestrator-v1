"""Web search via Tavily API."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from ..config import settings
from ..schemas.tool import ToolResult


def _tavily_client():
    try:
        from tavily import AsyncTavilyClient
    except ImportError as e:
        raise ValueError("tavily-python is not installed") from e
    return AsyncTavilyClient(api_key=settings.tavily_api_key)


def _format_results_as_answer(results: List[Dict[str, Any]], tavily_answer: Optional[str]) -> str:
    if tavily_answer and tavily_answer.strip():
        return tavily_answer.strip()
    lines: List[str] = []
    for i, r in enumerate(results[: settings.tavily_max_results], start=1):
        title = (r.get("title") or "Source").strip()
        content = (r.get("content") or "").strip()
        snippet = content[:400] + ("…" if len(content) > 400 else "")
        lines.append(f"- {title}: {snippet} [{i}]")
    return "\n".join(lines) if lines else "No web results found."


def _results_to_citations(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for i, r in enumerate(results[: settings.tavily_max_results], start=1):
        out.append(
            {
                "cite_id": i,
                "url": r.get("url"),
                "text": (r.get("content") or r.get("title") or "")[:2000],
                "source": "web",
                "title": r.get("title"),
            }
        )
    return out


async def run_web_search(question: str) -> ToolResult:
    if not settings.tavily_api_key:
        raise ValueError("TAVILY_API_KEY is not set")
    t0 = time.perf_counter()
    client = _tavily_client()
    response = await client.search(
        query=question,
        search_depth=settings.tavily_search_depth,
        max_results=settings.tavily_max_results,
        include_answer=True,
    )
    results = list(response.get("results") or [])
    answer = _format_results_as_answer(results, response.get("answer"))
    latency_ms = {"web_search": round((time.perf_counter() - t0) * 1000, 2)}
    return ToolResult(
        answer=answer,
        citations=_results_to_citations(results),
        follow_up_questions=[],
        usage=None,
        latency_ms=latency_ms,
        metadata={"transport": "tavily"},
    )
