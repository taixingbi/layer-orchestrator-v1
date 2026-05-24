"""SSE streaming and non-stream JSON aggregation."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from ..observability.metrics import inc_timeout, observe_pipeline_event
from ..observability.context import bind_conversation_logging_context
from ..observability.usage import build_usage_payload
from .pipeline import stream_answer_query

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
_TERMINAL_STATE_STATUSES = frozenset({"completed", "failed", "skipped"})


def state_slice_from_event(event: dict) -> dict:
    return {
        "phase": event.get("phase"),
        "status": event.get("status"),
        "ui_message": event.get("ui_message") or event.get("message"),
        "started_at": event.get("started_at"),
        "ended_at": event.get("ended_at"),
        "latency_ms": event.get("latency_ms"),
        "metadata": dict(event.get("metadata") or {}),
    }


def merge_phase_states(existing: dict, incoming: dict) -> dict:
    out = dict(existing)
    ex_st = out.get("status")
    in_st = incoming.get("status")
    out["metadata"] = {**(out.get("metadata") or {}), **(incoming.get("metadata") or {})}
    if ex_st in _TERMINAL_STATE_STATUSES:
        if out.get("started_at") is None and incoming.get("started_at"):
            out["started_at"] = incoming["started_at"]
        return out
    if in_st in _TERMINAL_STATE_STATUSES:
        out["status"] = in_st
        out["ui_message"] = incoming.get("ui_message") or out.get("ui_message")
        if incoming.get("ended_at") is not None:
            out["ended_at"] = incoming["ended_at"]
        if incoming.get("latency_ms") is not None:
            out["latency_ms"] = incoming["latency_ms"]
        out["started_at"] = incoming.get("started_at") or out.get("started_at")
        return out
    out["status"] = in_st or ex_st
    out["ui_message"] = incoming.get("ui_message") or out.get("ui_message")
    if incoming.get("started_at"):
        out["started_at"] = incoming["started_at"]
    return out


def _parse_iso_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _compute_total_timing(states: List[dict]) -> Optional[float]:
    starts = [_parse_iso_ts(s.get("started_at")) for s in states]
    ends = [_parse_iso_ts(s.get("ended_at")) for s in states]
    starts = [t for t in starts if t is not None]
    ends = [t for t in ends if t is not None]
    if starts and ends:
        return round((max(ends) - min(starts)).total_seconds() * 1000, 2)
    return None


def _round_ms(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    return None


def _service_latency_from_metadata(metadata: dict) -> Optional[Dict[str, Any]]:
    raw = metadata.get("rag_latency_ms") or metadata.get("tool_latency_ms")
    if isinstance(raw, dict) and raw:
        return raw
    return None


def _merge_phase_latency(
    orchestrator_ms: Optional[float],
    service: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Nest RAG/tool service latency_ms under phase orchestrator object."""
    orchestrator: Dict[str, Any] = {}
    wall = _round_ms(orchestrator_ms)
    if wall is not None:
        orchestrator["wall"] = wall
    if isinstance(service, dict):
        for key, val in service.items():
            if val is None:
                continue
            rounded = _round_ms(val)
            if rounded is not None:
                orchestrator[key] = rounded
            elif isinstance(val, dict):
                orchestrator[key] = val
    if not orchestrator:
        return None
    return {"orchestrator": orchestrator}


def build_latency_ms_summary(states: List[dict]) -> dict:
    by_phase: Dict[str, dict] = {}
    for s in states:
        phase = s.get("phase")
        if phase:
            by_phase[phase] = s

    timings: Dict[str, object] = {}
    total = _compute_total_timing(states)
    if total is not None:
        timings["total"] = total

    intent_router_ms = by_phase.get("intent_router", {}).get("latency_ms")
    if intent_router_ms is not None:
        timings["intent_router"] = {"total": _round_ms(intent_router_ms)}

    rag_state = by_phase.get("rag_query", {}) or by_phase.get("rag", {})
    rag_meta = rag_state.get("metadata") or {}
    rag_obj = _merge_phase_latency(
        rag_state.get("latency_ms"),
        _service_latency_from_metadata(rag_meta),
    )
    if rag_obj:
        timings["rag"] = rag_obj

    tool_state = by_phase.get("tool", {})
    tool_meta = tool_state.get("metadata") or {}
    tool_obj = _merge_phase_latency(
        tool_state.get("latency_ms"),
        _service_latency_from_metadata(tool_meta),
    )
    if tool_obj:
        timings["tool"] = tool_obj

    github_state = by_phase.get("github", {})
    if not github_state and tool_meta.get("tool") == "github_repo_search":
        github_state = tool_state
    github_meta = github_state.get("metadata") or {}
    github_obj = _merge_phase_latency(
        github_state.get("latency_ms"),
        _service_latency_from_metadata(github_meta),
    )
    if github_obj:
        timings["github"] = github_obj
        if tool_meta.get("tool") == "github_repo_search" and "tool" in timings:
            del timings["tool"]

    return timings


async def answer_event_iter(
    question: str,
    *,
    session_id: Optional[str],
    request_id: Optional[str],
    trace_id: Optional[str],
    rag_user: Optional[Dict[str, str]] = None,
    history: Optional[List[Tuple[str, str]]] = None,
    conversation_id: str,
    is_new_conversation: bool,
) -> AsyncIterator[dict]:
    async for chunk in stream_answer_query(
        question,
        session_id=session_id,
        request_id=request_id,
        trace_id=trace_id,
        rag_user=rag_user,
        history=history,
        conversation_id=conversation_id,
        is_new_conversation=is_new_conversation,
    ):
        observe_pipeline_event(chunk)
        yield chunk


async def answer_json(
    question: str,
    *,
    session_id: Optional[str],
    request_id: Optional[str],
    trace_id: Optional[str],
    rag_user: Optional[Dict[str, str]] = None,
    history: Optional[List[Tuple[str, str]]] = None,
    conversation_id: str,
    is_new_conversation: bool,
) -> dict:
    final: dict = {
        "request_id": request_id,
        "session_id": session_id,
        "trace_id": trace_id,
        "conversation_id": conversation_id,
        "is_new_conversation": is_new_conversation,
        "route": None,
        "route_detail": None,
        "rewrite": None,
        "answer": None,
        "citations": [],
        "follow_up_questions": [],
        "usage": build_usage_payload(),
    }
    states_by_phase: Dict[str, dict] = {}
    state_phase_order: List[str] = []
    terminal_usage: Optional[dict] = None
    async for event in answer_event_iter(
        question,
        session_id=session_id,
        request_id=request_id,
        trace_id=trace_id,
        rag_user=rag_user,
        history=history,
        conversation_id=conversation_id,
        is_new_conversation=is_new_conversation,
    ):
        t = event.get("type")
        if t == "request_id":
            final["request_id"] = event.get("request_id")
            final["session_id"] = event.get("session_id")
            final["trace_id"] = event.get("trace_id")
            final["conversation_id"] = event.get("conversation_id")
            if event.get("is_new_conversation") is not None:
                final["is_new_conversation"] = event.get("is_new_conversation")
        elif t == "done":
            for key in ("request_id", "session_id", "trace_id", "conversation_id", "is_new_conversation"):
                if event.get(key) is not None:
                    final[key] = event.get(key)
            usage = event.get("usage")
            if usage is not None:
                terminal_usage = usage
                final["usage"] = usage
            terminal_states = [
                states_by_phase[p]
                for p in state_phase_order
                if states_by_phase[p].get("status") in _TERMINAL_STATE_STATUSES
            ]
            final["latency_ms"] = build_latency_ms_summary(terminal_states)
            continue
        elif t == "rewrite":
            final["rewrite"] = event.get("text")
        elif t == "route":
            final["route"] = event.get("route")
            if event.get("route_detail") is not None:
                final["route_detail"] = event.get("route_detail")
        elif t == "answer":
            final["answer"] = event.get("text")
            final["citations"] = event.get("citations", [])
            final["follow_up_questions"] = event.get("follow_up_questions", [])
            usage = event.get("usage")
            if usage is not None:
                terminal_usage = usage
                final["usage"] = usage
        elif t == "state":
            phase = event.get("phase")
            if not phase:
                continue
            incoming = state_slice_from_event(event)
            if phase not in states_by_phase:
                state_phase_order.append(phase)
                states_by_phase[phase] = incoming
            else:
                states_by_phase[phase] = merge_phase_states(states_by_phase[phase], incoming)
        elif t == "error":
            terminal_states = [
                states_by_phase[p]
                for p in state_phase_order
                if states_by_phase[p].get("status") in _TERMINAL_STATE_STATUSES
            ]
            final["latency_ms"] = build_latency_ms_summary(terminal_states)
            for key in ("request_id", "session_id", "trace_id", "conversation_id", "is_new_conversation"):
                if event.get(key) is not None:
                    final[key] = event.get(key)
            usage = event.get("usage")
            if usage is not None:
                terminal_usage = usage
                final["usage"] = usage
            return {**final, "status": "error", "error": event.get("text")}
    terminal_states = [
        states_by_phase[p]
        for p in state_phase_order
        if states_by_phase[p].get("status") in _TERMINAL_STATE_STATUSES
    ]
    final["latency_ms"] = build_latency_ms_summary(terminal_states)
    if terminal_usage is not None:
        final["usage"] = terminal_usage
    return {**final, "status": "ok"}


def sse_stream_answer_gen(
    question: str,
    *,
    session_id: Optional[str] = None,
    request_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    rag_user: Optional[Dict[str, str]] = None,
    history: Optional[List[Tuple[str, str]]] = None,
    conversation_id: str,
    is_new_conversation: bool,
    request_timeout_s: Optional[float] = None,
    stream_idle_timeout_s: Optional[float] = None,
) -> AsyncIterator[str]:
    def _timeout_error_event(text: str) -> dict:
        return {
            "type": "error",
            "text": text,
            "session_id": session_id,
            "request_id": request_id,
            "trace_id": trace_id,
            "conversation_id": conversation_id,
            "is_new_conversation": is_new_conversation,
        }

    async def _gen():
        async with bind_conversation_logging_context(conversation_id, is_new_conversation):
            ait = answer_event_iter(
                question,
                session_id=session_id,
                request_id=request_id,
                trace_id=trace_id,
                rag_user=rag_user,
                history=history,
                conversation_id=conversation_id,
                is_new_conversation=is_new_conversation,
            ).__aiter__()
            states_by_phase: Dict[str, dict] = {}
            state_phase_order: List[str] = []
            started = time.perf_counter()
            while True:
                timeout_s = stream_idle_timeout_s
                if request_timeout_s is not None:
                    remaining = request_timeout_s - (time.perf_counter() - started)
                    if remaining <= 0:
                        inc_timeout("request")
                        timeout_event = _timeout_error_event(
                            "Error: TimeoutError: request timeout exceeded"
                        )
                        observe_pipeline_event(timeout_event)
                        yield f"data: {json.dumps(timeout_event)}\n\n"
                        return
                    timeout_s = min(timeout_s, remaining) if timeout_s is not None else remaining
                try:
                    chunk = await asyncio.wait_for(ait.__anext__(), timeout=timeout_s)
                except StopAsyncIteration:
                    return
                except asyncio.TimeoutError:
                    if request_timeout_s is not None and (time.perf_counter() - started) >= request_timeout_s:
                        msg = "Error: TimeoutError: request timeout exceeded"
                        inc_timeout("request")
                    else:
                        msg = "Error: TimeoutError: stream idle timeout exceeded"
                        inc_timeout("stream_idle")
                    timeout_event = _timeout_error_event(msg)
                    observe_pipeline_event(timeout_event)
                    yield f"data: {json.dumps(timeout_event)}\n\n"
                    return
                if chunk.get("type") == "state":
                    phase = chunk.get("phase")
                    if phase:
                        incoming = state_slice_from_event(chunk)
                        if phase not in states_by_phase:
                            state_phase_order.append(phase)
                            states_by_phase[phase] = incoming
                        else:
                            states_by_phase[phase] = merge_phase_states(
                                states_by_phase[phase], incoming
                            )
                    continue
                if chunk.get("type") in ("done", "error"):
                    terminal_states = [
                        states_by_phase[p]
                        for p in state_phase_order
                        if states_by_phase[p].get("status") in _TERMINAL_STATE_STATUSES
                    ]
                    chunk = {
                        **chunk,
                        "latency_ms": build_latency_ms_summary(terminal_states),
                    }
                yield f"data: {json.dumps(chunk)}\n\n"

    return _gen()
