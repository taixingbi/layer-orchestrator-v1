"""SSE streaming and non-stream JSON aggregation."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from ..observability.metrics import inc_timeout, observe_pipeline_event
from ..observability.context import bind_conversation_logging_context
from ..schemas.response import empty_answer_accumulator
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


def _mcp_latency_passthrough(metadata: dict, *keys: str) -> Optional[Dict[str, Any]]:
    """Return upstream MCP/HTTP latency_ms dict unchanged."""
    for key in keys:
        raw = metadata.get(key)
        if isinstance(raw, dict) and raw:
            return raw
    return None


def _rag_mcp_latency(metadata: dict) -> Optional[Dict[str, Any]]:
    return _mcp_latency_passthrough(metadata, "rag_latency_ms", "tool_latency_ms")


def _github_mcp_latency(metadata: dict) -> Optional[Dict[str, Any]]:
    return _mcp_latency_passthrough(metadata, "github_latency_ms", "tool_latency_ms")


from ..schemas.answer_envelope import (
    LATENCY_KEY_GITHUB_SEARCH,
    LATENCY_KEY_RAG,
    LATENCY_KEY_TAVILY_SEARCH,
    build_answer_envelope,
    normalize_latency_ms_keys,
    normalize_usage_keys,
)

_GITHUB_SEARCH_PHASE = "github-search"
_GITHUB_SEARCH_TOOL = "github_search"
_RAG_TOOL = "user_profile"


def _rag_state(by_phase: Dict[str, dict]) -> dict:
    for phase in ("rag_query", "rag", "tool"):
        state = by_phase.get(phase, {})
        if not state:
            continue
        meta = state.get("metadata") or {}
        if phase == "tool" and meta.get("tool") != _RAG_TOOL:
            continue
        return state
    return {}


def _github_search_state(by_phase: Dict[str, dict], tool_state: dict) -> dict:
    for phase in (_GITHUB_SEARCH_PHASE, "github", "tool"):
        state = by_phase.get(phase, {})
        if not state:
            continue
        meta = state.get("metadata") or {}
        if phase == "tool" and meta.get("tool") != _GITHUB_SEARCH_TOOL:
            continue
        return state
    tool_meta = tool_state.get("metadata") or {}
    if tool_meta.get("tool") == _GITHUB_SEARCH_TOOL:
        return tool_state
    return {}


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

    rag_state = _rag_state(by_phase)
    rag_obj = _rag_mcp_latency(rag_state.get("metadata") or {})
    if rag_obj:
        timings[LATENCY_KEY_RAG] = rag_obj

    tool_state = by_phase.get("tool", {})
    tool_meta = tool_state.get("metadata") or {}
    if tool_meta.get("tool") == "web_search":
        tool_obj = _mcp_latency_passthrough(tool_meta, "tool_latency_ms")
        if tool_obj:
            timings[LATENCY_KEY_TAVILY_SEARCH] = tool_obj

    github_state = _github_search_state(by_phase, tool_state)
    github_meta = github_state.get("metadata") or {}
    github_obj = _github_mcp_latency(github_meta)
    if github_obj:
        timings[LATENCY_KEY_GITHUB_SEARCH] = github_obj

    return timings


class AnswerResponseAccumulator:
    """Merge pipeline events; finalize to meta/answer/latency_ms/usage envelope."""

    def __init__(
        self,
        *,
        request_id: Optional[str],
        session_id: Optional[str],
        trace_id: Optional[str],
        conversation_id: str,
        is_new_conversation: bool,
        rag_user: Optional[Dict[str, str]] = None,
    ) -> None:
        self.rag_user = rag_user
        self.body: Dict[str, Any] = empty_answer_accumulator(
            request_id=request_id,
            session_id=session_id,
            trace_id=trace_id,
            conversation_id=conversation_id,
            is_new_conversation=is_new_conversation,
        )
        self.states_by_phase: Dict[str, dict] = {}
        self.state_phase_order: List[str] = []

    def apply(self, event: dict) -> None:
        t = event.get("type")
        if t == "request_id":
            for key in ("request_id", "session_id", "trace_id", "conversation_id", "is_new_conversation"):
                if event.get(key) is not None:
                    self.body[key] = event.get(key)
        elif t == "rewrite":
            self.body["rewrite"] = event.get("text")
        elif t == "route":
            if event.get("route_detail") is not None:
                self.body["route_detail"] = event.get("route_detail")
            if event.get("route_source") is not None:
                self.body["route_source"] = event.get("route_source")
        elif t == "answer":
            if isinstance(event.get("answer"), dict):
                ans = event["answer"]
                self.body["answer_text"] = ans.get("text")
                self.body["citations"] = ans.get("citations", [])
            else:
                self.body["answer_text"] = event.get("text")
                self.body["citations"] = event.get("citations", [])
            self.body["follow_up_questions"] = event.get("follow_up_questions", [])
            usage = event.get("usage")
            if usage is not None:
                self.body["usage"] = usage
        elif t == "state":
            phase = event.get("phase")
            if not phase:
                return
            incoming = state_slice_from_event(event)
            if phase not in self.states_by_phase:
                self.state_phase_order.append(phase)
                self.states_by_phase[phase] = incoming
            else:
                self.states_by_phase[phase] = merge_phase_states(
                    self.states_by_phase[phase], incoming
                )
        elif t == "done":
            for key in ("request_id", "session_id", "trace_id", "conversation_id", "is_new_conversation"):
                if event.get(key) is not None:
                    self.body[key] = event.get(key)
            usage = event.get("usage")
            if usage is not None:
                self.body["usage"] = usage

    def _terminal_states(self) -> List[dict]:
        return [
            self.states_by_phase[p]
            for p in self.state_phase_order
            if self.states_by_phase[p].get("status") in _TERMINAL_STATE_STATUSES
        ]

    def finalize(
        self,
        *,
        ok: bool,
        error: Optional[str] = None,
        state: Optional[str] = None,
        code: Optional[str] = None,
    ) -> Dict[str, Any]:
        latency = normalize_latency_ms_keys(build_latency_ms_summary(self._terminal_states()))
        usage = normalize_usage_keys(self.body.get("usage") or {})
        return build_answer_envelope(
            request_id=self.body.get("request_id"),
            session_id=self.body.get("session_id"),
            trace_id=self.body.get("trace_id"),
            conversation_id=self.body.get("conversation_id") or "",
            is_new_conversation=bool(self.body.get("is_new_conversation")),
            route_detail=self.body.get("route_detail"),
            rewrite=self.body.get("rewrite"),
            route_source=self.body.get("route_source"),
            answer_text=self.body.get("answer_text"),
            citations=self.body.get("citations"),
            follow_up_questions=self.body.get("follow_up_questions"),
            latency_ms=latency,
            usage=usage,
            rag_user=self.rag_user,
            ok=ok,
            state=state,
            code=code,
            error=error,
        )

    def enrich_terminal_event(self, event: dict) -> dict:
        if event.get("type") == "error":
            err = event.get("error") or event.get("text")
            if event.get("route_source") is not None:
                self.body["route_source"] = event.get("route_source")
            code = event.get("status_code") or "error"
            merged = self.finalize(ok=False, error=err, state="failed", code=code)
            return {**merged, "type": "error", "text": err or ""}
        merged = self.finalize(ok=True, code="ok")
        return {**merged, "type": "done"}


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
    acc = AnswerResponseAccumulator(
        request_id=request_id,
        session_id=session_id,
        trace_id=trace_id,
        conversation_id=conversation_id,
        is_new_conversation=is_new_conversation,
        rag_user=rag_user,
    )
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
        if t == "error":
            acc.apply(event)
            err = event.get("error") or event.get("text")
            code = event.get("status_code") or "error"
            return acc.finalize(ok=False, error=err, state="failed", code=code)
        acc.apply(event)
        if t == "done":
            return acc.finalize(ok=True, code="ok")
    return acc.finalize(ok=True, code="ok")


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
            **build_answer_envelope(
                request_id=request_id,
                session_id=session_id,
                trace_id=trace_id,
                conversation_id=conversation_id,
                is_new_conversation=is_new_conversation,
                route_detail=None,
                rewrite=None,
                answer_text=None,
                citations=[],
                follow_up_questions=[],
                latency_ms={},
                usage={},
                rag_user=rag_user,
                ok=False,
                state="failed",
                code="error",
                error=text,
            ),
            "type": "error",
            "text": text,
        }

    async def _gen():
        async with bind_conversation_logging_context(conversation_id, is_new_conversation):
            acc = AnswerResponseAccumulator(
                request_id=request_id,
                session_id=session_id,
                trace_id=trace_id,
                conversation_id=conversation_id,
                is_new_conversation=is_new_conversation,
                rag_user=rag_user,
            )
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
                    acc.apply(chunk)
                    continue
                acc.apply(chunk)
                if chunk.get("type") in ("done", "error"):
                    chunk = acc.enrich_terminal_event(chunk)
                yield f"data: {json.dumps(chunk)}\n\n"

    return _gen()
