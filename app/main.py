# main.py — FastAPI orchestrator (chat completions + RAG)
import asyncio
import contextlib
from datetime import datetime
import json
import logging
import time
from typing import AsyncIterator, Dict, List, Literal, Optional, Tuple

from .config import has_langsmith_credentials, settings
from .logging_config import new_request_id, setup_logging, shutdown_logging
from .request_context import bind_pipeline_phase, bind_request_context, reset_request_context, set_http_status

setup_logging()

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.requests import Request
from .langsmith_feedback import FEEDBACK_TYPES, FeedbackBody, submit_langsmith_feedback
from .agent_rewrite import normalize_history_turns
from .orchestrator import stream_answer_query

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
_http_log = logging.getLogger("layer_orchestrator.http")


def _latency_ms(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000, 2)


def _sse_stream_answer_gen(
    question: str,
    session_id: Optional[str] = None,
    request_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    rag_user: Optional[Dict[str, str]] = None,
    history: Optional[List[Tuple[str, str]]] = None,
) -> AsyncIterator[str]:
    """Async generator for POST /orchestrator/answer with stream=true."""
    async def _gen():
        async for chunk in _answer_event_iter(
            question,
            session_id=session_id,
            request_id=request_id,
            trace_id=trace_id,
            rag_user=rag_user,
            history=history,
        ):
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
) -> AsyncIterator[dict]:
    async for chunk in stream_answer_query(
        question,
        session_id=session_id,
        request_id=request_id,
        trace_id=trace_id,
        rag_user=rag_user,
        history=history,
    ):
        yield chunk


async def _answer_json(
    question: str,
    *,
    session_id: Optional[str],
    request_id: Optional[str],
    trace_id: Optional[str],
    rag_user: Optional[Dict[str, str]] = None,
    history: Optional[List[Tuple[str, str]]] = None,
) -> dict:
    final: dict = {
        "request_id": request_id,
        "session_id": session_id,
        "trace_id": trace_id,
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
    ):
        t = event.get("type")
        if t == "request_id":
            final["request_id"] = event.get("request_id")
            final["session_id"] = event.get("session_id")
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
    # Keep health checks lightweight and out of request logs.
    if request.url.path == "/health":
        return await call_next(request)

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
            response.headers["X-Request-Id"] = request_id
            set_http_status(str(response.status_code))
            _http_log.info(
                "http_request_complete",
                extra={
                    "latency_ms": latency_ms,
                    "status_code": response.status_code,
                    "trace_id": trace_id,
                },
            )
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


def _history_from_answer_body(body: AnswerBody) -> List[Tuple[str, str]]:
    return normalize_history_turns([(t.role, t.content) for t in body.history])


@app.post("/orchestrator/answer")
async def orchestrator_answer(body: AnswerBody, request: Request):
    """Unified endpoint: stream=true returns SSE; stream=false returns aggregated JSON."""
    raw_body = await request.json()
    _reject_body_correlation_fields(raw_body)
    session_id, request_id, trace_id = _header_ids(request)
    rag_user = _header_rag_user(request)
    hist = _history_from_answer_body(body)
    if body.stream:
        return StreamingResponse(
            _sse_stream_answer_gen(
                body.question,
                session_id=session_id,
                request_id=request_id,
                trace_id=trace_id,
                rag_user=rag_user,
                history=hist,
            ),
            media_type="text/event-stream",
            headers=SSE_HEADERS,
        )
    result = await _answer_json(
        body.question,
        session_id=session_id,
        request_id=request_id,
        trace_id=trace_id,
        rag_user=rag_user,
        history=hist,
    )
    status_code = 200 if result.get("status") == "ok" else 500
    return JSONResponse(result, status_code=status_code)


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
