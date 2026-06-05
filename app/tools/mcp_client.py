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
    is_new_conversation: bool = False,
) -> Dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "X-Request-Id": request_id or "",
        "X-Session-Id": session_id or "",
        "X-Trace-Id": trace_id or request_id or "",
    }
    cid = (conversation_id or "").strip()
    if cid:
        headers["X-Conversation-Id"] = cid
        headers["X-Is-New-Conversation"] = "true" if is_new_conversation else "false"
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


def _extract_sse_delta_text(obj: Dict[str, Any]) -> str:
    """GitHub MCP v2: delta is `{ \"answer\": { \"text\": \"...\" } }`; legacy: `{ \"text\": \"...\" }`."""
    ans = obj.get("answer")
    if isinstance(ans, dict):
        text = ans.get("text")
        if isinstance(text, str):
            return text
    chunk = obj.get("text")
    return chunk if isinstance(chunk, str) else ""


def _normalize_mcp_tool_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten MCP structuredContent (GitHub v2 / RAG) into ToolResult field dict."""
    out: Dict[str, Any] = {}
    if not isinstance(data, dict):
        return out

    ans = data.get("answer")
    if isinstance(ans, dict):
        out["answer"] = str(ans.get("text") or "").strip()
        cites = ans.get("citations")
        if cites is not None:
            out["citations"] = cites
        blocks = ans.get("blocks")
        if isinstance(blocks, list):
            out["answer_blocks"] = blocks
        notes = ans.get("notes")
        if isinstance(notes, list):
            out["answer_notes"] = notes
        answer_format = ans.get("format")
        if isinstance(answer_format, str) and answer_format.strip():
            out["answer_format"] = answer_format.strip()
    elif isinstance(ans, str):
        out["answer"] = ans.strip()
    elif isinstance(data.get("text"), str):
        out["answer"] = data["text"].strip()

    if data.get("citations") is not None and "citations" not in out:
        out["citations"] = data["citations"]
    if data.get("follow_up_questions") is not None:
        out["follow_up_questions"] = data["follow_up_questions"]

    lat = data.get("latency_ms")
    if isinstance(lat, dict):
        inner: Optional[Dict[str, Any]] = None
        for key in ("tool_github_search", "tool_rag", "tool_tavily_search"):
            nested = lat.get(key)
            if isinstance(nested, dict):
                inner = nested
                break
        out["latency_ms"] = inner if inner is not None else lat
    elif lat is not None:
        out["latency_ms"] = lat if isinstance(lat, dict) else {"total": lat}

    usage = data.get("usage")
    if isinstance(usage, dict):
        out["usage"] = usage

    meta: Dict[str, Any] = {}
    if isinstance(data.get("meta"), dict):
        meta["mcp_meta"] = data["meta"]
    if isinstance(data.get("status"), dict):
        meta["status"] = data["status"]
    if "ok" in data:
        meta["ok"] = data["ok"]
    if meta:
        out["metadata"] = meta

    return out


def _accumulate_github_sse(text: str) -> Dict[str, Any]:
    """Parse GitHub MCP SSE (event: meta / delta / done)."""
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
        if not isinstance(obj, dict):
            continue
        if current_event == "delta":
            chunk = _extract_sse_delta_text(obj)
            if chunk:
                text_chunks.append(chunk)
        elif current_event == "done":
            done_payload = obj
    normalized = _normalize_mcp_tool_payload(done_payload)
    if text_chunks and not normalized.get("answer"):
        normalized["answer"] = "".join(text_chunks).strip()
    return normalized


def _merge_mcp_stream_payload(
    base: Dict[str, Any],
    *,
    github_deltas: List[str],
    progress_events: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Combine GitHub delta text, RAG-style progress events, and done payload."""
    payload = _normalize_mcp_tool_payload(base) if base else {}
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
    normalized = _normalize_mcp_tool_payload(data)
    answer = str(normalized.get("answer") or "").strip()
    citations = normalized.get("citations") if normalized.get("citations") is not None else data.get("citations") or []
    follow_ups = normalized.get("follow_up_questions")
    if follow_ups is None:
        follow_ups = data.get("follow_up_questions") or []
    usage_raw = normalized.get("usage") if normalized.get("usage") is not None else data.get("usage")
    usage = usage_raw if isinstance(usage_raw, dict) else None
    latency = normalized.get("latency_ms")
    if latency is None:
        latency = data.get("latency_ms")
    if isinstance(latency, dict):
        pass
    elif latency is not None:
        latency = {"total": latency}
    else:
        latency = None
    meta = normalized.get("metadata") if isinstance(normalized.get("metadata"), dict) else {}
    if not meta:
        meta = {"source": data.get("source") or "mcp"}
    else:
        meta = dict(meta)
        meta.setdefault("source", "mcp")
    blocks = normalized.get("answer_blocks")
    notes = normalized.get("answer_notes")
    answer_format = normalized.get("answer_format")
    return ToolResult(
        answer=answer,
        answer_blocks=list(blocks) if isinstance(blocks, list) else [],
        answer_notes=list(notes) if isinstance(notes, list) else [],
        answer_format=str(answer_format) if isinstance(answer_format, str) and answer_format else "text",
        citations=list(citations) if citations else [],
        follow_up_questions=list(follow_ups) if follow_ups else [],
        usage=usage,
        latency_ms=latency,
        metadata=meta,
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
            chunk = _extract_sse_delta_text(obj)
            if chunk:
                github_deltas.append(chunk)
                if on_delta:
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
    if isinstance(result.get("answer"), (dict, str)) or isinstance(result.get("latency_ms"), dict):
        return _payload_to_tool_result(result)
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
    is_new_conversation: bool = False,
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
        is_new_conversation=is_new_conversation,
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
