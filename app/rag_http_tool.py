"""LangChain tool that calls the RAG HTTP API (POST /v1/rag/query)."""

import json
from typing import Any, Dict, List, Optional, Tuple

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


def _accumulate_sse_payload(raw_events: List[str]) -> Any:
    """Best-effort SSE data aggregation into a JSON-like payload."""
    text_chunks: List[str] = []
    retrieval_hits: Any = None
    latency_ms: Any = None
    last_obj: Any = None
    for raw in raw_events:
        item = raw.strip()
        if not item or item == "[DONE]":
            continue
        try:
            obj = json.loads(item)
        except json.JSONDecodeError:
            text_chunks.append(item)
            continue
        last_obj = obj
        if isinstance(obj, dict):
            for key in ("answer", "response", "generated_answer", "text"):
                val = obj.get(key)
                if isinstance(val, str) and val:
                    text_chunks.append(val)
            # Common chunk styles.
            if obj.get("type") in ("token", "chunk", "delta"):
                chunk_text = obj.get("text") or obj.get("delta") or obj.get("content")
                if isinstance(chunk_text, str) and chunk_text:
                    text_chunks.append(chunk_text)
            if "retrieval_hits" in obj:
                retrieval_hits = obj.get("retrieval_hits")
            elif "hits" in obj:
                retrieval_hits = obj.get("hits")
            if "latency_ms" in obj:
                latency_ms = obj.get("latency_ms")
    if text_chunks or retrieval_hits is not None:
        payload = {
            "text": "".join(text_chunks).strip(),
            "retrieval_hits": retrieval_hits,
        }
        if latency_ms is not None:
            payload["latency_ms"] = latency_ms
        return payload
    return last_obj if last_obj is not None else {"text": ""}


def _extract_rag_latency_ms(data: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(data, dict):
        return None
    latency = data.get("latency_ms")
    if isinstance(latency, dict):
        return latency
    if isinstance(latency, (int, float)):
        return {"total": latency}
    return None


async def query_rag_http(
    question: str,
    request_id: str = "",
    session_id: str = "",
    trace_id: str = "",
) -> str:
    """POST /v1/rag/query and return formatted text for the LLM."""
    text, _ = await query_rag_http_with_meta(question, request_id, session_id, trace_id)
    return text


async def query_rag_http_with_meta(
    question: str,
    request_id: str = "",
    session_id: str = "",
    trace_id: str = "",
) -> Tuple[str, Dict[str, Any]]:
    """POST /v1/rag/query and return (formatted_text, metadata)."""
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
        "Accept": "text/event-stream",
        "X-Request-Id": request_id or "",
        "X-Session-Id": session_id or "",
        "X-Trace-Id": trace_id or request_id or "",
    }
    headers = {k: v for k, v in headers.items() if v}
    client = _shared_http_client()
    async with client.stream("POST", url, json=payload, headers=headers) as r:
        r.raise_for_status()
        ctype = (r.headers.get("content-type") or "").lower()
        if "text/event-stream" in ctype:
            events: List[str] = []
            async for line in r.aiter_lines():
                if line.startswith("data:"):
                    events.append(line[5:].strip())
            data = _accumulate_sse_payload(events)
        else:
            data = await r.json()
    metadata: Dict[str, Any] = {}
    rag_latency_ms = _extract_rag_latency_ms(data)
    if rag_latency_ms is not None:
        metadata["rag_latency_ms"] = rag_latency_ms
    return _format_rag_response(data), metadata


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
