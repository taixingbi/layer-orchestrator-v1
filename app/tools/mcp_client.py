"""Shared MCP JSON-RPC client and SSE normalizers."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

import httpx

from ..config import settings
from ..schemas.tool import ToolResult

_mcp_log = logging.getLogger("layer_orchestrator.mcp")
_client: Optional[httpx.AsyncClient] = None


def _shared_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.tools_timeout_s),
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=40),
        )
    return _client


async def aclose_mcp_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _mcp_headers(
    *,
    request_id: str,
    session_id: str,
    trace_id: str,
    rag_user: Optional[Dict[str, str]] = None,
    conversation_id: str = "",
) -> Dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "X-Request-Id": request_id or "",
        "X-Session-Id": session_id or "",
        "X-Trace-Id": trace_id or request_id or "",
    }
    if conversation_id:
        headers["X-Conversation-Id"] = conversation_id
    if rag_user:
        for key, hdr in (
            ("user_id", "X-User-Id"),
            ("user_roles", "X-User-Roles"),
            ("user_groups", "X-User-Groups"),
            ("user_teams", "X-User-Teams"),
        ):
            v = rag_user.get(key)
            if v:
                headers[hdr] = v
    return {k: v for k, v in headers.items() if v}


def _parse_mcp_progress_message(message: str) -> Optional[Dict[str, Any]]:
    if not message:
        return None
    try:
        obj = json.loads(message)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _emit_progress_event(
    inner: Dict[str, Any],
    *,
    progress_events: List[Dict[str, Any]],
    on_delta: Optional[Callable[[str], None]],
) -> None:
    progress_events.append(inner)
    if inner.get("type") == "answer_delta":
        chunk = inner.get("text") or ""
        if on_delta and chunk:
            on_delta(chunk)


def _accumulate_progress_events(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge MCP progress JSON events (RAG MCP style) into one payload."""
    text_chunks: List[str] = []
    citations: Any = None
    follow_up_questions: Any = None
    usage: Any = None
    latency_ms: Dict[str, Any] = {}
    for ev in events:
        t = ev.get("type")
        if t == "answer_delta":
            chunk = ev.get("text")
            if isinstance(chunk, str):
                text_chunks.append(chunk)
        elif t == "citations":
            citations = ev.get("items", ev)
        elif t == "follow_up_questions":
            follow_up_questions = ev.get("items", ev)
        elif t == "usage":
            usage = ev
        elif t == "latency":
            phase = ev.get("phase")
            ms = ev.get("ms")
            if phase is not None and ms is not None:
                latency_ms[str(phase)] = ms
            nested = ev.get("latency_ms")
            if isinstance(nested, dict):
                latency_ms.update(nested)
        elif t == "latency_ms" and isinstance(ev, dict):
            for key, val in ev.items():
                if key != "type" and val is not None:
                    latency_ms[key] = val
        elif isinstance(ev.get("answer"), str):
            text_chunks.append(ev["answer"])
    out: Dict[str, Any] = {}
    if text_chunks:
        out["answer"] = "".join(text_chunks).strip()
    if citations is not None:
        out["citations"] = citations
    if follow_up_questions is not None:
        out["follow_up_questions"] = follow_up_questions
    if usage is not None:
        out["usage"] = usage
    if latency_ms:
        out["latency_ms"] = latency_ms
    return out


def _accumulate_github_sse(text: str) -> Dict[str, Any]:
    """Parse GitHub MCP SSE (event: delta / done)."""
    text_chunks: List[str] = []
    done_payload: Dict[str, Any] = {}
    current_event: Optional[str] = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            current_event = None
            continue
        if stripped.startswith("event:"):
            current_event = stripped[6:].strip()
            continue
        if not stripped.startswith("data:"):
            continue
        raw = stripped[5:].strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if current_event == "delta" and isinstance(obj, dict):
            chunk = obj.get("text")
            if isinstance(chunk, str):
                text_chunks.append(chunk)
        elif current_event == "done" and isinstance(obj, dict):
            done_payload = obj
    out: Dict[str, Any] = dict(done_payload)
    if text_chunks and not out.get("answer"):
        out["answer"] = "".join(text_chunks).strip()
    return out


def _merge_mcp_stream_payload(
    base: Dict[str, Any],
    *,
    github_deltas: List[str],
    progress_events: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Combine GitHub delta text, RAG-style progress events, and done payload."""
    payload = dict(base)
    if not payload.get("answer") and github_deltas:
        payload["answer"] = "".join(github_deltas).strip()
    if not progress_events:
        return payload
    merged = _accumulate_progress_events(progress_events)
    if not payload.get("answer") and merged.get("answer"):
        payload["answer"] = merged["answer"]
    prog_lat = merged.get("latency_ms")
    if isinstance(prog_lat, dict):
        existing = payload.get("latency_ms")
        if isinstance(existing, dict):
            payload["latency_ms"] = {**prog_lat, **existing}
        else:
            payload["latency_ms"] = prog_lat
    for key in ("citations", "follow_up_questions", "usage"):
        if key not in payload and merged.get(key) is not None:
            payload[key] = merged[key]
    return payload


def _payload_to_tool_result(data: Dict[str, Any]) -> ToolResult:
    answer = str(data.get("answer") or data.get("text") or "").strip()
    citations = data.get("citations") or []
    follow_ups = data.get("follow_up_questions") or []
    usage_raw = data.get("usage")
    usage = usage_raw if isinstance(usage_raw, dict) else None
    latency = data.get("latency_ms")
    if isinstance(latency, dict):
        pass
    elif latency is not None:
        latency = {"total": latency}
    else:
        latency = None
    return ToolResult(
        answer=answer,
        citations=list(citations) if citations else [],
        follow_up_questions=list(follow_ups) if follow_ups else [],
        usage=usage,
        latency_ms=latency,
        metadata={"source": data.get("source") or "mcp"},
    )


def _emit_events_from_list(
    events: List[Dict[str, Any]],
    *,
    on_delta: Optional[Callable[[str], None]],
) -> Dict[str, Any]:
    progress: List[Dict[str, Any]] = []
    for ev in events:
        if isinstance(ev, dict):
            _emit_progress_event(ev, progress_events=progress, on_delta=on_delta)
    return _accumulate_progress_events(progress)


async def _parse_mcp_sse_lines(
    lines: AsyncIterator[str],
    *,
    on_delta: Optional[Callable[[str], None]] = None,
) -> ToolResult:
    progress_events: List[Dict[str, Any]] = []
    github_deltas: List[str] = []
    current_event: Optional[str] = None

    async for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped:
            current_event = None
            continue
        if stripped.startswith("event:"):
            current_event = stripped[6:].strip()
            continue
        if not stripped.startswith("data:"):
            continue
        raw = stripped[5:].strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if current_event == "message" and isinstance(obj, dict):
            params = obj.get("params") or {}
            msg = params.get("message")
            inner = _parse_mcp_progress_message(msg) if isinstance(msg, str) else None
            if inner:
                _emit_progress_event(inner, progress_events=progress_events, on_delta=on_delta)
        elif current_event == "delta" and isinstance(obj, dict):
            chunk = obj.get("text") or ""
            github_deltas.append(chunk)
            if on_delta and chunk:
                on_delta(chunk)
        elif current_event == "done" and isinstance(obj, dict):
            payload = _merge_mcp_stream_payload(
                obj,
                github_deltas=github_deltas,
                progress_events=progress_events,
            )
            if payload.get("answer") or payload.get("latency_ms"):
                return _payload_to_tool_result(payload)

    payload = _merge_mcp_stream_payload(
        {},
        github_deltas=github_deltas,
        progress_events=progress_events,
    )
    if payload.get("answer") or payload.get("latency_ms"):
        return _payload_to_tool_result(payload)
    return ToolResult(answer="")


async def _tool_result_from_json_payload(
    data: Any,
    *,
    on_delta: Optional[Callable[[str], None]] = None,
) -> ToolResult:
    if not isinstance(data, dict):
        return ToolResult(answer=json.dumps(data, default=str)[:50000])
    if "result" not in data:
        return ToolResult(answer=json.dumps(data, default=str)[:50000])
    result = data["result"]
    if not isinstance(result, dict):
        return ToolResult(answer=json.dumps(data, default=str)[:50000])
    content = result.get("content")
    if isinstance(content, list) and content:
        text = content[0].get("text") if isinstance(content[0], dict) else None
        if text:
            try:
                inner = json.loads(text)
                if isinstance(inner, dict):
                    if inner.get("events"):
                        merged = _emit_events_from_list(inner["events"], on_delta=on_delta)
                        return _payload_to_tool_result(merged)
                    if inner.get("answer") or inner.get("latency_ms"):
                        return _payload_to_tool_result(inner)
            except json.JSONDecodeError:
                return ToolResult(answer=str(text))
    sc = result.get("structuredContent")
    if isinstance(sc, dict):
        if sc.get("events"):
            merged = _emit_events_from_list(sc["events"], on_delta=on_delta)
            return _payload_to_tool_result(merged)
        if sc.get("answer") or sc.get("latency_ms"):
            return _payload_to_tool_result(sc)
    return ToolResult(answer=json.dumps(data, default=str)[:50000])


async def call_mcp_tool(
    *,
    base_url: str,
    tool_name: str,
    arguments: Dict[str, Any],
    request_id: str = "",
    session_id: str = "",
    trace_id: str = "",
    rag_user: Optional[Dict[str, str]] = None,
    conversation_id: str = "",
    stream: bool = True,
    on_delta: Optional[Callable[[str], None]] = None,
) -> ToolResult:
    """POST /v1/mcp tools/call; stream SSE lines and invoke on_delta per answer_delta."""
    base = (base_url or "").strip().rstrip("/")
    if not base:
        raise ValueError("MCP base URL is not set")
    url = f"{base}/v1/mcp"
    rpc_id = request_id or str(uuid.uuid4())
    payload = {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": {**arguments, "stream": stream}},
    }
    headers = _mcp_headers(
        request_id=request_id,
        session_id=session_id,
        trace_id=trace_id,
        rag_user=rag_user,
        conversation_id=conversation_id,
    )
    client = _shared_client()
    _mcp_log.info(
        "mcp_tool_call",
        extra={
            "event": "mcp_tool_call",
            "gateway_meta": {"url": url, "tool": tool_name, "stream": stream},
        },
    )
    async with client.stream("POST", url, json=payload, headers=headers) as response:
        response.raise_for_status()
        ctype = (response.headers.get("content-type") or "").lower()
        if "text/event-stream" in ctype:
            return await _parse_mcp_sse_lines(response.aiter_lines(), on_delta=on_delta)
        body = await response.aread()
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return ToolResult(answer=body.decode("utf-8", errors="replace")[:50000])
    return await _tool_result_from_json_payload(data, on_delta=on_delta)
