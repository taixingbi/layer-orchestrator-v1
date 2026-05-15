"""LangChain tool that calls the RAG HTTP API (POST /v1/rag/query)."""

import asyncio
import json
import logging
import random
from typing import Any, Dict, List, Optional, Tuple

import httpx
from langchain_core.tools import tool

from .config import settings

_rag_log = logging.getLogger("layer_orchestrator.rag_http")
_RAG_LOG_JSON_MAX_CHARS = 80_000

# JSON keys tried in order for the user-visible answer string (RAG API variants).
_RAG_ANSWER_KEYS: Tuple[str, ...] = ("answer", "response", "generated_answer", "text")

# Retry only idempotent, transient cases (timeouts, connection errors, overload / gateway).
_RAG_RETRYABLE_STATUS: frozenset = frozenset({429, 502, 503, 504})
_RAG_RETRY_AFTER_CAP_S: float = 30.0
_RAG_BACKOFF_CAP_S: float = 10.0

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


def rag_primary_answer_text(data: Any) -> str:
    """Prefer the RAG JSON `answer` field (verbatim user-facing string)."""
    if isinstance(data, dict):
        for key in _RAG_ANSWER_KEYS:
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return _format_rag_response(data)


def rag_tool_sidecar(data: Any) -> Dict[str, Any]:
    """Citations and follow-ups from RAG JSON for the orchestrator response body."""
    if not isinstance(data, dict):
        return {}
    out: Dict[str, Any] = {}
    if "citations" in data:
        out["citations"] = data["citations"]
    if "follow_up_questions" in data:
        out["follow_up_questions"] = data["follow_up_questions"]
    return out


def _format_rag_response(data: Any) -> str:
    """Turn JSON into a concise string for the LLM."""
    if not isinstance(data, dict):
        return json.dumps(data, default=str)[:50000]
    parts: List[str] = []
    for key in _RAG_ANSWER_KEYS:
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
            for key in _RAG_ANSWER_KEYS:
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


def _rag_api_body_for_log(data: Any) -> Dict[str, Any]:
    """Mirror RAG JSON for metadata sidecars (answer, citations, follow_up_questions, latency_ms)."""
    if not isinstance(data, dict):
        return {"_shape": type(data).__name__}
    out: Dict[str, Any] = {}
    for key in ("answer", "citations", "follow_up_questions", "latency_ms"):
        if key in data:
            out[key] = data[key]
    if "answer" not in out:
        for alt in _RAG_ANSWER_KEYS[1:]:
            if alt in data and data[alt] is not None:
                out["answer"] = data[alt]
                break
    return out


def _rag_payload_for_log(data: Any, *, max_chars: int = _RAG_LOG_JSON_MAX_CHARS) -> Any:
    """Full request/response JSON for structured logs; truncate only when serialization is huge."""
    try:
        serialized = json.dumps(data, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return {"_unserializable": repr(data)[:2000]}
    if len(serialized) <= max_chars:
        return data
    return {
        "_truncated": True,
        "_original_bytes": len(serialized),
        "_preview": serialized[:max_chars],
    }


def _log_rag_query_request(*, url: str, payload: Dict[str, Any], headers: Dict[str, str]) -> None:
    _rag_log.info(
        "rag_query_api_request",
        extra={
            "event": "rag_query_api_request",
            "gateway_meta": {
                "url": url,
                "rag_api_request": _rag_payload_for_log(payload),
                "rag_api_request_headers": dict(headers),
            },
        },
    )


def _log_rag_query_response(
    *,
    url: str,
    http_status: int,
    attempts: int,
    data: Any,
    content_type: str = "",
) -> None:
    _rag_log.info(
        "rag_query_api_response",
        extra={
            "event": "rag_query_api_response",
            "gateway_meta": {
                "url": url,
                "http_status_code": http_status,
                "rag_http_attempts": attempts,
                "content_type": content_type or None,
                "rag_api_response": _rag_payload_for_log(data),
            },
        },
    )


def _rag_retry_delay_s(attempt_index: int, response: Optional[httpx.Response]) -> float:
    """Exponential backoff with jitter; honors Retry-After on 429 when present."""
    base = settings.rag_http_retry_backoff_s * (2**attempt_index)
    base = min(_RAG_BACKOFF_CAP_S, base)
    if response is not None and response.status_code == 429:
        raw = (response.headers.get("retry-after") or "").strip()
        if raw:
            try:
                base = max(base, min(_RAG_RETRY_AFTER_CAP_S, float(raw)))
            except ValueError:
                pass
    # jitter in [0.5 * base, base]
    return base * (0.5 + 0.5 * random.random())


async def query_rag_http(
    question: str,
    request_id: str = "",
    session_id: str = "",
    trace_id: str = "",
    *,
    user_id: str = "",
    user_roles: str = "",
    user_groups: str = "",
    user_teams: str = "",
    conversation_id: str = "",
    is_new_conversation: bool = False,
) -> str:
    """POST /v1/rag/query and return formatted text for the LLM."""
    text, _ = await query_rag_http_with_meta(
        question,
        request_id,
        session_id,
        trace_id,
        user_id=user_id,
        user_roles=user_roles,
        user_groups=user_groups,
        user_teams=user_teams,
        conversation_id=conversation_id,
        is_new_conversation=is_new_conversation,
    )
    return text


async def query_rag_http_with_meta(
    question: str,
    request_id: str = "",
    session_id: str = "",
    trace_id: str = "",
    *,
    user_id: str = "",
    user_roles: str = "",
    user_groups: str = "",
    user_teams: str = "",
    conversation_id: str = "",
    is_new_conversation: bool = False,
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
    cid = (conversation_id or "").strip()
    if cid:
        payload["conversation_id"] = cid
    url = f"{base}/v1/rag/query"
    # Prefer JSON (same as typical curl without Accept: event-stream) so the body
    # includes full `latency_ms` breakdown. SSE streams often omit or split metrics.
    headers = {
        "Accept": "application/json",
        "X-Request-Id": request_id or "",
        "X-Session-Id": session_id or "",
        "X-Trace-Id": trace_id or request_id or "",
        "X-User-Id": user_id or "",
        "X-User-Roles": user_roles or "",
        "X-User-Groups": user_groups or "",
        "X-User-Teams": user_teams or "",
        "X-Conversation-Id": cid,
        "X-Is-New-Conversation": ("true" if is_new_conversation else "false") if cid else "",
    }
    headers = {k: v for k, v in headers.items() if v}
    _log_rag_query_request(url=url, payload=payload, headers=headers)
    client = _shared_http_client()
    max_attempts = settings.rag_http_max_attempts
    response: Optional[httpx.Response] = None
    attempt = 0
    while attempt < max_attempts:
        try:
            response = await client.post(url, json=payload, headers=headers)
        except (httpx.TimeoutException, httpx.RequestError):
            attempt += 1
            if attempt >= max_attempts:
                raise
            await asyncio.sleep(_rag_retry_delay_s(attempt - 1, None))
            continue
        if response.status_code in _RAG_RETRYABLE_STATUS:
            attempt += 1
            if attempt >= max_attempts:
                response.raise_for_status()
            await asyncio.sleep(_rag_retry_delay_s(attempt - 1, response))
            continue
        response.raise_for_status()
        break
    assert response is not None
    http_status = response.status_code
    ctype = (response.headers.get("content-type") or "").lower()
    if "text/event-stream" in ctype:
        events: List[str] = []
        for line in response.text.splitlines():
            if line.startswith("data:"):
                events.append(line[5:].strip())
        data = _accumulate_sse_payload(events)
    else:
        data = response.json()
    _log_rag_query_response(
        url=url,
        http_status=http_status,
        attempts=attempt + 1,
        data=data,
        content_type=ctype,
    )
    metadata: Dict[str, Any] = {
        "http_status_code": http_status,
        "rag_http_attempts": attempt + 1,
    }
    rag_latency_ms = _extract_rag_latency_ms(data)
    if rag_latency_ms is not None:
        metadata["rag_latency_ms"] = rag_latency_ms
    metadata["rag_api_response"] = _rag_api_body_for_log(data)
    sidecar = rag_tool_sidecar(data)
    if sidecar:
        metadata["rag_tool_sidecar"] = sidecar
    return rag_primary_answer_text(data), metadata


def create_rag_http_tools():
    """Tools for the HTTP RAG service (requires RAG_HTTP_BASE_URL)."""

    @tool
    async def query_knowledge_base(
        question: str,
        request_id: str = "",
        session_id: str = "",
        trace_id: str = "",
        user_id: str = "",
        user_roles: str = "",
        user_groups: str = "",
        user_teams: str = "",
        conversation_id: str = "",
        is_new_conversation: bool = False,
    ) -> str:
        """Retrieve relevant knowledge from the configured vector collection (RAG). Use for questions that need factual or policy information from the knowledge base."""
        return await query_rag_http(
            question,
            request_id,
            session_id,
            trace_id,
            user_id=user_id,
            user_roles=user_roles,
            user_groups=user_groups,
            user_teams=user_teams,
            conversation_id=conversation_id,
            is_new_conversation=is_new_conversation,
        )

    return [query_knowledge_base]
