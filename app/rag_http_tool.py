"""LangChain tool that calls the RAG HTTP API (POST /v1/rag/query)."""

import json
from typing import Any, List, Optional

import httpx
from langchain_core.tools import tool

from .config import settings

_http_client: Optional[httpx.AsyncClient] = None


def _shared_http_client() -> httpx.AsyncClient:
    """One AsyncClient per process for connection reuse to the RAG service."""
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.tools_timeout_s),
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=40),
        )
    return _http_client


async def aclose_rag_http_client() -> None:
    """Close the shared client (call from app shutdown)."""
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None


def _format_rag_response(data: Any) -> str:
    """Turn JSON into a concise string for the LLM."""
    if not isinstance(data, dict):
        return json.dumps(data, default=str)[:50000]
    parts: List[str] = []
    for key in ("answer", "response", "generated_answer", "text"):
        val = data.get(key)
        if val:
            parts.append(f"{key}: {val}")
    hits = data.get("retrieval_hits") if "retrieval_hits" in data else data.get("hits")
    if hits is not None:
        parts.append("Retrieval hits:\n" + json.dumps(hits, indent=2)[:20000])
    if not parts:
        return json.dumps(data, indent=2)[:50000]
    return "\n\n".join(parts)


async def query_rag_http(
    question: str,
    request_id: str = "",
    session_id: str = "",
    trace_id: str = "",
) -> str:
    """POST /v1/rag/query and return formatted text for the LLM."""
    base = (settings.rag_http_base_url or "").rstrip("/")
    if not base:
        raise ValueError("RAG_HTTP_BASE_URL is not set")
    payload = {
        "question": question,
        "collection_base": settings.rag_collection_base,
        "k": settings.rag_k,
        "k_max": settings.rag_k_max,
        "include_retrieval_hits": settings.rag_include_retrieval_hits,
    }
    url = f"{base}/v1/rag/query"
    headers = {
        "X-Request-Id": request_id or "",
        "X-Session-Id": session_id or "",
        "X-Trace-Id": trace_id or request_id or "",
    }
    headers = {k: v for k, v in headers.items() if v}
    client = _shared_http_client()
    r = await client.post(url, json=payload, headers=headers)
    r.raise_for_status()
    data = r.json()
    return _format_rag_response(data)


def create_rag_http_tools():
    """Tools for the HTTP RAG service (requires RAG_HTTP_BASE_URL)."""

    @tool
    async def query_knowledge_base(
        question: str,
        request_id: str = "",
        session_id: str = "",
        trace_id: str = "",
    ) -> str:
        """Retrieve relevant knowledge from the configured vector collection (RAG). Use for questions that need factual or policy information from the knowledge base."""
        return await query_rag_http(question, request_id, session_id, trace_id)

    return [query_knowledge_base]
