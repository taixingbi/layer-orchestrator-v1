# main.py — FastAPI orchestrator (chat completions + RAG)
import asyncio
import contextlib
from datetime import datetime
import json
import logging
import time
import uuid
from typing import Any, AsyncIterator, Dict, List, Literal, Optional, Tuple

from .config import has_langsmith_credentials, settings
from .metrics import (
    inc_timeout,
    metrics_content_type,
    metrics_payload,
    observe_http,
    observe_pipeline_event,
)
from .ready_checks import run_readiness
from .logging_config import new_request_id, setup_logging, shutdown_logging
from .request_context import (
    bind_conversation_logging_context,
    bind_pipeline_phase,
    bind_request_context,
    reset_request_context,
    set_http_status,
)

setup_logging()

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator
from starlette.requests import Request
from .langsmith_feedback import FEEDBACK_TYPES, FeedbackBody, submit_langsmith_feedback
from .agent_rewrite import normalize_history_turns
from .intent_rewrite_router import RouterDecision, normalize_post_router, run_intent_rewrite_router
from .orchestrator import stream_answer_query

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
_http_log = logging.getLogger("layer_orchestrator.http")


def _latency_ms(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000, 2)


def _max_request_body_bytes() -> int:
    return max(1, int(settings.max_request_body_mb * 1024 * 1024))


def _request_timeout_s() -> float:
    return settings.request_timeout_ms / 1000.0


def _stream_idle_timeout_s() -> float:
    return settings.stream_idle_timeout_ms / 1000.0


def _resolve_effective_conversation_id(raw: Optional[str]) -> Tuple[str, bool]:
    """Return (conversation_id, is_new). Blank/missing → new ``conv_<uuidhex>``."""
    cid = (raw or "").strip()
    if cid:
        return cid, False
    return f"conv_{uuid.uuid4().hex}", True


def _validate_answer_body_limits(body: "AnswerBody", raw_size_bytes: int, *, conversation_id: str) -> None:
    if raw_size_bytes > _max_request_body_bytes():
        raise HTTPException(
            status_code=413,
            detail=(
                f"request body too large: {raw_size_bytes} bytes > "
                f"{_max_request_body_bytes()} bytes (MAX_REQUEST_BODY_MB={settings.max_request_body_mb})"
            ),
        )
    q_len = len((body.question or ""))
    if q_len > settings.max_question_chars:
        raise HTTPException(
            status_code=400,
            detail=(
                f"question too long: {q_len} chars > "
                f"{settings.max_question_chars} (MAX_QUESTION_CHARS)"
            ),
        )
    hist_len = len(body.history or [])
    if hist_len > settings.max_history_messages:
        raise HTTPException(
            status_code=400,
            detail=(
                f"history too long: {hist_len} messages > "
                f"{settings.max_history_messages} (MAX_HISTORY_MESSAGES)"
            ),
        )
    conv_len = len(conversation_id)
    context_chars = q_len + sum(len(t.content or "") for t in (body.history or [])) + conv_len
    if context_chars > settings.max_context_chars:
        raise HTTPException(
            status_code=400,
            detail=(
                f"context too large: {context_chars} chars > "
                f"{settings.max_context_chars} (MAX_CONTEXT_CHARS)"
            ),
        )


def _sse_stream_answer_gen(
    question: str,
    session_id: Optional[str] = None,
    request_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    rag_user: Optional[Dict[str, str]] = None,
    history: Optional[List[Tuple[str, str]]] = None,
    *,
    conversation_id: str,
    is_new_conversation: bool,
    request_timeout_s: Optional[float] = None,
    stream_idle_timeout_s: Optional[float] = None,
) -> AsyncIterator[str]:
    """Async generator for POST /orchestrator/answer with stream=true."""

    async def _gen():
        async with bind_conversation_logging_context(conversation_id, is_new_conversation):
            ait = _answer_event_iter(
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
                        timeout_event = {"type": "error", "text": "Error: TimeoutError: request timeout exceeded"}
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
                    timeout_event = {"type": "error", "text": msg}
                    observe_pipeline_event(timeout_event)
                    yield f"data: {json.dumps(timeout_event)}\n\n"
                    return
                yield f"data: {json.dumps(chunk)}\n\n"

    return _gen()


def _reject_body_correlation_fields(raw_body: object) -> None:
    if not isinstance(raw_body, dict):
        return
    correlation_keys = [key for key in ("session_id", "request_id", "trace_id") if key in raw_body]
    if correlation_keys:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{', '.join(correlation_keys)} must be sent in headers only: "
                "X-Session-Id, X-Request-Id, X-Trace-Id"
            ),
        )
    user_keys = [key for key in ("user_id", "user_roles", "user_groups", "user_teams") if key in raw_body]
    if user_keys:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{', '.join(user_keys)} must be sent in headers only: "
                "X-User-Id, X-User-Roles, X-User-Groups, X-User-Teams"
            ),
        )


def _header_ids(request: Request) -> tuple[Optional[str], Optional[str], Optional[str]]:
    return (
        getattr(request.state, "session_id", None),
        getattr(request.state, "request_id", None),
        getattr(request.state, "trace_id", None),
    )


def _header_rag_user(request: Request) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for key in ("user_id", "user_roles", "user_groups", "user_teams"):
        v = getattr(request.state, key, None)
        if isinstance(v, str) and v.strip():
            out[key] = v.strip()
    return out


_TERMINAL_STATE_STATUSES = frozenset({"completed", "failed", "skipped"})


def _state_slice_from_event(event: dict) -> dict:
    return {
        "phase": event.get("phase"),
        "status": event.get("status"),
        "ui_message": event.get("ui_message") or event.get("message"),
        "started_at": event.get("started_at"),
        "ended_at": event.get("ended_at"),
        "latency_ms": event.get("latency_ms"),
        "metadata": dict(event.get("metadata") or {}),
    }


def _merge_phase_states(existing: dict, incoming: dict) -> dict:
    """Merge two state records for the same phase (e.g. running then completed)."""
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


def _build_timings_summary(states: List[dict]) -> dict:
    by_phase: Dict[str, dict] = {}
    for s in states:
        phase = s.get("phase")
        if phase:
            by_phase[phase] = s

    timings: Dict[str, object] = {}
    total = _compute_total_timing(states)
    if total is not None:
        timings["total"] = total

    intent_router = by_phase.get("intent_router", {}).get("latency_ms")
    if intent_router is not None:
        timings["intent_router"] = intent_router

    rag_query_state = by_phase.get("rag_query", {})
    rag_total = rag_query_state.get("latency_ms")
    rag_service = (rag_query_state.get("metadata") or {}).get("rag_latency_ms")
    if rag_total is not None or isinstance(rag_service, dict):
        rag_obj: Dict[str, object] = {}
        if rag_total is not None:
            rag_obj["total"] = rag_total
        if isinstance(rag_service, dict):
            rag_obj["service"] = rag_service
        timings["rag"] = rag_obj

    req_complete = by_phase.get("request_complete", {}).get("latency_ms")
    if req_complete is not None:
        timings["request_complete"] = req_complete

    return timings


async def _answer_event_iter(
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


async def _answer_json(
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
        "rewrite": None,
        "answer": None,
    }
    states_by_phase: Dict[str, dict] = {}
    state_phase_order: List[str] = []
    async for event in _answer_event_iter(
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
            final["conversation_id"] = event.get("conversation_id")
            if event.get("is_new_conversation") is not None:
                final["is_new_conversation"] = event.get("is_new_conversation")
        elif t == "rewrite":
            final["rewrite"] = event.get("text")
        elif t == "route":
            final["route"] = event.get("route")
        elif t == "answer":
            final["answer"] = event.get("text")
            if "citations" in event:
                final["citations"] = event["citations"]
            if "follow_up_questions" in event:
                final["follow_up_questions"] = event["follow_up_questions"]
        elif t == "state":
            phase = event.get("phase")
            if not phase:
                continue
            incoming = _state_slice_from_event(event)
            if phase not in states_by_phase:
                state_phase_order.append(phase)
                states_by_phase[phase] = incoming
            else:
                states_by_phase[phase] = _merge_phase_states(states_by_phase[phase], incoming)
        elif t == "error":
            terminal_states = [
                states_by_phase[p]
                for p in state_phase_order
                if states_by_phase[p].get("status") in _TERMINAL_STATE_STATUSES
            ]
            final["timings_ms"] = _build_timings_summary(terminal_states)
            return {
                **final,
                "status": "error",
                "error": event.get("text"),
            }
    terminal_states = [
        states_by_phase[p]
        for p in state_phase_order
        if states_by_phase[p].get("status") in _TERMINAL_STATE_STATUSES
    ]
    final["timings_ms"] = _build_timings_summary(terminal_states)
    return {
        **final,
        "status": "ok",
    }


@contextlib.asynccontextmanager
async def _lifespan(_app: FastAPI):
    try:
        yield
    finally:
        from .rag_http_tool import aclose_rag_http_client

        await aclose_rag_http_client()
        shutdown_logging()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=_lifespan,
)


@app.middleware("http")
async def _http_request_logging_middleware(request: Request, call_next):
    # Keep health/readiness/metrics checks lightweight and out of request logs.
    if request.url.path in ("/health", "/ready", "/metrics"):
        t0 = time.perf_counter()
        response = await call_next(request)
        observe_http(
            method=request.method,
            path=request.url.path,
            status_code=int(response.status_code),
            latency_s=(time.perf_counter() - t0),
        )
        return response
    if request.url.path == "/orchestrator/answer":
        raw_cl = (request.headers.get("content-length") or "").strip()
        if raw_cl:
            try:
                cl = int(raw_cl)
                if cl > _max_request_body_bytes():
                    return JSONResponse(
                        {
                            "status": "error",
                            "error": (
                                f"request body too large: {cl} bytes > {_max_request_body_bytes()} bytes "
                                f"(MAX_REQUEST_BODY_MB={settings.max_request_body_mb})"
                            ),
                        },
                        status_code=413,
                    )
            except ValueError:
                pass

    request_id = request.headers.get("x-request-id") or new_request_id()
    session_id = request.headers.get("x-session-id")
    trace_id = request.headers.get("x-trace-id") or request_id
    request.state.request_id = request_id
    request.state.session_id = session_id
    request.state.trace_id = trace_id
    hdr = request.headers

    def _strip_opt(h: Optional[str]) -> Optional[str]:
        if h is None:
            return None
        s = h.strip()
        return s if s else None

    request.state.user_id = _strip_opt(hdr.get("x-user-id"))
    request.state.user_roles = _strip_opt(hdr.get("x-user-roles"))
    request.state.user_groups = _strip_opt(hdr.get("x-user-groups"))
    request.state.user_teams = _strip_opt(hdr.get("x-user-teams"))
    path = request.url.path
    method = request.method
    ctx = bind_request_context(
        request_id=request_id,
        session_id=session_id,
        method=method,
        path=path,
    )
    try:
        async with bind_pipeline_phase("http"):
            _http_log.info(
                "http_request_start",
                extra={"trace_id": trace_id},
            )
            t0 = time.perf_counter()
            try:
                response = await call_next(request)
            except Exception:
                latency_ms = _latency_ms(t0)
                observe_http(method=method, path=path, status_code=500, latency_s=latency_ms / 1000.0)
                _http_log.error(
                    "http_request_error",
                    extra={
                        "latency_ms": latency_ms,
                        "trace_id": trace_id,
                        "error_type": "unhandled_exception",
                    },
                )
                raise
            latency_ms = _latency_ms(t0)
            observe_http(method=method, path=path, status_code=int(response.status_code), latency_s=latency_ms / 1000.0)
            response.headers["X-Request-Id"] = request_id
            set_http_status(str(response.status_code))
            http_extra: Dict[str, Any] = {
                "latency_ms": latency_ms,
                "status_code": response.status_code,
                "trace_id": trace_id,
            }
            cid = getattr(request.state, "conversation_id", None)
            if isinstance(cid, str) and cid.strip():
                http_extra["conversation_id"] = cid.strip()
            _http_log.info("http_request_complete", extra=http_extra)
            return response
    finally:
        reset_request_context(ctx)


class HistoryTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class AnswerBody(BaseModel):
    question: str
    stream: bool = False
    history: List[HistoryTurn] = Field(default_factory=list)
    conversation_id: Optional[str] = Field(
        default=None,
        max_length=256,
        description=(
            "Client-owned thread id (optional). Omit, null, or whitespace → server assigns "
            "conv_<uuidhex>; response includes effective conversation_id and is_new_conversation."
        ),
    )

    @field_validator("conversation_id", mode="before")
    @classmethod
    def _blank_conversation_id_to_none(cls, v: object) -> Optional[str]:
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip()
            return s if s else None
        raise ValueError("conversation_id must be a string or null")


def _history_from_answer_body(body: AnswerBody) -> List[Tuple[str, str]]:
    return normalize_history_turns([(t.role, t.content) for t in body.history])


class EvalRouterBody(BaseModel):
    question: str
    expected_route: Optional[Literal["rag", "direct_reply", "clarify", "reject"]] = None
    conversation_id: Optional[str] = Field(
        default=None,
        max_length=256,
        description=(
            "Client-owned thread id (optional). Omit, null, or whitespace → server assigns "
            "conv_<uuidhex>; response includes effective conversation_id and is_new_conversation."
        ),
    )
    router_model: Optional[str] = Field(default=None, max_length=256)
    router_temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    router_prompt_version: Optional[str] = Field(
        default=None,
        max_length=256,
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$",
    )
    router_prompt_override: Optional[str] = None
    history: List[HistoryTurn] = Field(default_factory=list)

    @field_validator("router_model", "router_prompt_version", "conversation_id", mode="before")
    @classmethod
    def _blank_router_str_to_none(cls, v: object) -> Optional[str]:
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip()
            return s if s else None
        raise ValueError("must be a string or null")


def _validate_eval_router_body_limits(body: EvalRouterBody, *, conversation_id: str) -> None:
    q_len = len(body.question or "")
    if q_len > settings.max_question_chars:
        raise HTTPException(
            status_code=400,
            detail=(
                f"question too long: {q_len} chars > "
                f"{settings.max_question_chars} (MAX_QUESTION_CHARS)"
            ),
        )
    hist_len = len(body.history or [])
    if hist_len > settings.max_history_messages:
        raise HTTPException(
            status_code=400,
            detail=(
                f"history too long: {hist_len} messages > "
                f"{settings.max_history_messages} (MAX_HISTORY_MESSAGES)"
            ),
        )
    override = body.router_prompt_override or ""
    ov_len = len(override)
    if ov_len > settings.max_context_chars:
        raise HTTPException(
            status_code=400,
            detail=(
                f"router_prompt_override too long: {ov_len} chars > "
                f"{settings.max_context_chars} (MAX_CONTEXT_CHARS)"
            ),
        )
    conv_len = len(conversation_id)
    context_chars = q_len + sum(len(t.content or "") for t in (body.history or [])) + ov_len + conv_len
    if context_chars > settings.max_context_chars:
        raise HTTPException(
            status_code=400,
            detail=(
                f"context too large: {context_chars} chars > "
                f"{settings.max_context_chars} (MAX_CONTEXT_CHARS)"
            ),
        )


def _history_from_eval_body(body: EvalRouterBody) -> List[Tuple[str, str]]:
    return normalize_history_turns([(t.role, t.content) for t in body.history])


def _router_eval_payload(
    decision: RouterDecision,
    *,
    question: str,
    history: List[Tuple[str, str]],
    expected_route: Optional[str],
) -> dict:
    actual_route = decision.route
    exp = expected_route.strip().lower() if isinstance(expected_route, str) and expected_route.strip() else None

    checks: Dict[str, bool] = {
        "has_rewrite": bool((decision.rewritten_question or "").strip()),
        "route_valid": actual_route in ("rag", "direct_reply", "clarify", "reject"),
        "direct_reply_has_answer": (
            actual_route != "direct_reply" or bool((decision.direct_answer or "").strip())
        ),
    }
    if exp is not None:
        checks["route_match"] = actual_route == exp
    else:
        checks["route_match"] = True
    if history:
        checks["history_followup_rewritten"] = (
            (decision.rewritten_question or "").strip().lower() != (question or "").strip().lower()
        )
    else:
        checks["history_followup_rewritten"] = True
    notes: List[str] = []
    if not checks["has_rewrite"]:
        notes.append("rewritten_question is empty")
    if not checks["route_valid"]:
        notes.append("route is not in allowed set")
    if exp is not None and not checks["route_match"]:
        notes.append(f"route mismatch: expected {exp}, got {actual_route}")
    if not checks["direct_reply_has_answer"]:
        notes.append("direct_reply route returned empty answer")
    if history and not checks["history_followup_rewritten"]:
        notes.append("history exists but rewritten_question did not change from question")
    all_checks_pass = all(checks.values())
    return {
        "expected_route": exp,
        "actual_route": actual_route,
        "route_match": (actual_route == exp) if exp is not None else None,
        "all_checks_pass": all_checks_pass,
        "checks": checks,
        "notes": notes,
    }


@app.post("/orchestrator/answer")
async def orchestrator_answer(body: AnswerBody, request: Request):
    """Unified endpoint: stream=true returns SSE; stream=false returns aggregated JSON."""
    raw_bytes = await request.body()
    conversation_id, is_new_conversation = _resolve_effective_conversation_id(body.conversation_id)
    request.state.conversation_id = conversation_id
    async with bind_conversation_logging_context(conversation_id, is_new_conversation):
        _validate_answer_body_limits(body, len(raw_bytes), conversation_id=conversation_id)
        raw_body = await request.json()
        _reject_body_correlation_fields(raw_body)
        session_id, request_id, trace_id = _header_ids(request)
        rag_user = _header_rag_user(request)
        hist = _history_from_answer_body(body)
        request_timeout_s = _request_timeout_s()
        stream_idle_timeout_s = _stream_idle_timeout_s()
    if body.stream:
        return StreamingResponse(
            _sse_stream_answer_gen(
                body.question,
                session_id=session_id,
                request_id=request_id,
                trace_id=trace_id,
                rag_user=rag_user,
                history=hist,
                conversation_id=conversation_id,
                is_new_conversation=is_new_conversation,
                request_timeout_s=request_timeout_s,
                stream_idle_timeout_s=stream_idle_timeout_s,
            ),
            media_type="text/event-stream",
            headers=SSE_HEADERS,
        )
    async with bind_conversation_logging_context(conversation_id, is_new_conversation):
        try:
            result = await asyncio.wait_for(
                _answer_json(
                    body.question,
                    session_id=session_id,
                    request_id=request_id,
                    trace_id=trace_id,
                    rag_user=rag_user,
                    history=hist,
                    conversation_id=conversation_id,
                    is_new_conversation=is_new_conversation,
                ),
                timeout=request_timeout_s,
            )
        except asyncio.TimeoutError:
            inc_timeout("request")
            return JSONResponse(
                {
                    "status": "error",
                    "error": "request timeout exceeded",
                    "request_id": request_id,
                    "session_id": session_id,
                    "trace_id": trace_id,
                    "conversation_id": conversation_id,
                    "is_new_conversation": is_new_conversation,
                },
                status_code=504,
            )
        status_code = 200 if result.get("status") == "ok" else 500
        return JSONResponse(result, status_code=status_code)


@app.post("/orchestrator/eval/router")
async def orchestrator_eval_router(request: Request):
    """Evaluate intent router decision only (no RAG execution)."""
    raw_bytes = await request.body()
    if len(raw_bytes) > _max_request_body_bytes():
        raise HTTPException(
            status_code=413,
            detail=(
                f"request body too large: {len(raw_bytes)} bytes > "
                f"{_max_request_body_bytes()} bytes (MAX_REQUEST_BODY_MB={settings.max_request_body_mb})"
            ),
        )
    try:
        raw_obj = json.loads(raw_bytes)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid JSON body")
    if not isinstance(raw_obj, dict):
        raise HTTPException(status_code=400, detail="JSON body must be an object")
    _reject_body_correlation_fields(raw_obj)
    body = EvalRouterBody.model_validate(raw_obj)
    conversation_id, is_new_conversation = _resolve_effective_conversation_id(body.conversation_id)
    request.state.conversation_id = conversation_id
    _validate_eval_router_body_limits(body, conversation_id=conversation_id)
    session_id, request_id, trace_id = _header_ids(request)
    async with bind_conversation_logging_context(conversation_id, is_new_conversation):
        hist = _history_from_eval_body(body)
        resolved_temp = 0.0 if body.router_temperature is None else float(body.router_temperature)
        resolved_model = (body.router_model or "").strip() or settings.llm_model
        run_meta: Dict[str, Any] = {}
        decision = await run_intent_rewrite_router(
            body.question,
            hist,
            request_id=request_id,
            session_id=session_id,
            trace_id=trace_id,
            router_model=body.router_model,
            router_temperature=body.router_temperature,
            router_prompt_version=body.router_prompt_version,
            router_system_prompt=body.router_prompt_override,
            runtime_meta=run_meta,
            conversation_id=conversation_id,
            is_new_conversation=is_new_conversation,
        )
        decision = normalize_post_router(decision)
        evaluation = _router_eval_payload(
            decision,
            question=body.question,
            history=hist,
            expected_route=body.expected_route,
        )
        prompt_override_used = bool((body.router_prompt_override or "").strip())
        return {
            "request_id": request_id,
            "session_id": session_id,
            "trace_id": trace_id,
            "conversation_id": conversation_id,
            "is_new_conversation": is_new_conversation,
            "router": {
                "model": resolved_model,
                "temperature": resolved_temp,
                "prompt_version": body.router_prompt_version,
                "prompt_source": run_meta.get("prompt_source"),
                "prompt_file": run_meta.get("prompt_file"),
                "prompt_fallback_from": run_meta.get("prompt_requested_fallback"),
                "smalltalk_intent": run_meta.get("smalltalk_intent"),
                "prompt_override_used": prompt_override_used,
            },
            "decision": {
                "rewritten_question": decision.rewritten_question,
                "route": decision.route,
                "answer": decision.direct_answer,
                "reason": decision.reason,
            },
            "evaluation": evaluation,
            "status": "ok",
        }


@app.post("/feedback")
async def submit_feedback(body: FeedbackBody):
    """Submit feedback on an agent response (thumbs up/down, type, optional comment)."""
    if body.feedback_type and body.feedback_type not in FEEDBACK_TYPES:
        return {"status": "error", "message": f"feedback_type must be one of: {', '.join(sorted(FEEDBACK_TYPES))}"}
    run_id_for_feedback = body.agent_graph_run_id or body.trace_id or body.request_id
    logging.getLogger("layer_orchestrator.feedback").info(
        "feedback_received",
        extra={
            "gateway_meta": {
                "rating": body.rating,
                "feedback_type": body.feedback_type,
                "question_preview": (body.question or "")[:80] or None,
                "comment_preview": (body.comment or "")[:80] or None,
            },
        },
    )
    if run_id_for_feedback and has_langsmith_credentials():
        await asyncio.to_thread(
            submit_langsmith_feedback,
            agent_graph_run_id=run_id_for_feedback,
            rating=body.rating,
            feedback_type=body.feedback_type,
            comment=body.comment,
        )
    return {"status": "ok", "message": "Feedback received"}


@app.get("/health")
def health() -> dict:
    """Return app and LangSmith config for health checks."""
    return {
        "status": "ok",
        "app_version": settings.app_version,
        "app_name": settings.app_name,
        "langchain_project": settings.langchain_project,
        "langsmith_tracing": settings.langsmith_tracing,
        "langchain_endpoint": settings.langchain_endpoint,
    }


@app.get("/ready")
async def ready():
    """Verify LLM gateway and RAG HTTP service; 503 if any required dependency fails."""
    all_ok, body = await run_readiness()
    status_code = 200 if all_ok else 503
    return JSONResponse(body, status_code=status_code)


@app.get("/metrics")
def metrics():
    """Prometheus metrics endpoint."""
    return Response(content=metrics_payload(), media_type=metrics_content_type())
