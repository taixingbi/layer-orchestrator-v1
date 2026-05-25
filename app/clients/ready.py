"""Outbound readiness probes for LLM gateway and RAG HTTP service."""

import asyncio
import json
import os
import time
from typing import Any, Dict, Tuple

import httpx

from ..config import gateway_extra_headers, normalized_llm_base_url, settings

_READINESS_RID = "readiness-check"
_NO_CHUNKS_MARKER = "no chunks retrieved"


def _rag_no_chunks_response(response: httpx.Response) -> bool:
    """True when RAG is up but returned empty retrieval for the probe query."""
    text = (response.text or "").strip()
    if not text:
        return False
    try:
        data = response.json()
    except json.JSONDecodeError:
        return _NO_CHUNKS_MARKER in text.lower()
    if isinstance(data, dict):
        detail = data.get("detail")
        if isinstance(detail, str) and _NO_CHUNKS_MARKER in detail.lower():
            return True
    return _NO_CHUNKS_MARKER in text.lower()


def _dep_ok(latency_ms: float) -> Dict[str, Any]:
    return {"ok": True, "status": "ok", "latency_ms": round(latency_ms, 2)}


def _dep_fail(status: str, latency_ms: float, error: str, detail: str | None = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "ok": False,
        "status": status,
        "latency_ms": round(latency_ms, 2),
        "error": error,
    }
    if detail:
        out["detail"] = detail[:500]
    return out


def _dep_not_configured(component: str) -> Dict[str, Any]:
    return {
        "ok": False,
        "status": "not_configured",
        "latency_ms": None,
        "error": f"{component} is not configured",
    }


async def check_llm_gateway(client: httpx.AsyncClient) -> Dict[str, Any]:
    base = normalized_llm_base_url()
    if not base:
        return _dep_not_configured("LLM_GATEWAY_BASE_URL")

    url = f"{base.rstrip('/')}/chat/completions"
    api_key = os.getenv("LLM_API_KEY") or "not-needed"
    headers: Dict[str, str] = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        **gateway_extra_headers(
            request_id=_READINESS_RID,
            session_id=_READINESS_RID,
            trace_id=_READINESS_RID,
        ),
    }
    body = {
        "model": settings.llm_model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    }
    t0 = time.perf_counter()
    try:
        r = await client.post(url, headers=headers, json=body)
        latency_ms = (time.perf_counter() - t0) * 1000
        if r.status_code >= 400:
            return _dep_fail(
                "error",
                latency_ms,
                f"HTTP {r.status_code}",
                (r.text or "")[:500] or None,
            )
        try:
            data = r.json()
        except json.JSONDecodeError as e:
            return _dep_fail("error", latency_ms, "invalid_json", str(e))
        if not isinstance(data, dict):
            return _dep_fail("error", latency_ms, "unexpected_response", None)
        if data.get("error") is not None:
            err = data.get("error")
            msg = err if isinstance(err, str) else json.dumps(err, default=str)[:300]
            return _dep_fail("error", latency_ms, "gateway_error", msg)
        return _dep_ok(latency_ms)
    except httpx.TimeoutException:
        latency_ms = (time.perf_counter() - t0) * 1000
        return _dep_fail("timeout", latency_ms, "timeout", None)
    except httpx.RequestError as e:
        latency_ms = (time.perf_counter() - t0) * 1000
        return _dep_fail("error", latency_ms, type(e).__name__, str(e)[:500])


async def check_rag_http(client: httpx.AsyncClient) -> Dict[str, Any]:
    base = (settings.rag_http_base_url or "").strip().rstrip("/")
    if not base:
        return _dep_not_configured("RAG_HTTP_BASE_URL")

    url = f"{base}/v1/rag/query"
    payload = {
        "question": settings.readiness_rag_question,
        "collection_base": settings.rag_collection_base,
        "k": 1,
        "k_max": 1,
        "include_retrieval_hits": False,
    }
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Request-Id": _READINESS_RID,
        "X-Session-Id": _READINESS_RID,
        "X-Trace-Id": _READINESS_RID,
    }
    t0 = time.perf_counter()
    try:
        r = await client.post(url, headers=headers, json=payload)
        latency_ms = (time.perf_counter() - t0) * 1000
        if r.status_code >= 400:
            if r.status_code == 400 and _rag_no_chunks_response(r):
                return _dep_ok(latency_ms)
            return _dep_fail(
                "error",
                latency_ms,
                f"HTTP {r.status_code}",
                (r.text or "")[:500] or None,
            )
        ctype = (r.headers.get("content-type") or "").lower()
        if "text/event-stream" in ctype:
            return _dep_ok(latency_ms)
        try:
            r.json()
        except json.JSONDecodeError as e:
            return _dep_fail("error", latency_ms, "invalid_json", str(e))
        return _dep_ok(latency_ms)
    except httpx.TimeoutException:
        latency_ms = (time.perf_counter() - t0) * 1000
        return _dep_fail("timeout", latency_ms, "timeout", None)
    except httpx.RequestError as e:
        latency_ms = (time.perf_counter() - t0) * 1000
        return _dep_fail("error", latency_ms, type(e).__name__, str(e)[:500])


async def run_readiness() -> Tuple[bool, Dict[str, Any]]:
    """Run LLM and RAG probes in parallel. Returns (all_required_ok, response_body)."""
    timeout = httpx.Timeout(settings.readiness_timeout_s)
    async with httpx.AsyncClient(timeout=timeout) as client:
        llm, rag = await asyncio.gather(
            check_llm_gateway(client),
            check_rag_http(client),
        )

    all_ok = bool(llm.get("ok")) and bool(rag.get("ok"))
    body: Dict[str, Any] = {
        "status": "ok" if all_ok else "degraded",
        "dependencies": {"llm": llm, "rag": rag},
    }
    return all_ok, body
