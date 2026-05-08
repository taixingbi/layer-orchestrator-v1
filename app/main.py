# main.py — FastAPI orchestrator (chat completions + RAG)
import asyncio
import contextlib
import json
import logging
import time
from typing import AsyncIterator, Optional

from .config import has_langsmith_credentials, settings
from .logging_config import new_request_id, setup_logging, shutdown_logging
from .request_context import bind_request_context, reset_request_context, set_http_status

setup_logging()

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from starlette.requests import Request
from .langsmith_feedback import FEEDBACK_TYPES, FeedbackBody, submit_langsmith_feedback
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
) -> AsyncIterator[str]:
    """Async generator for POST /orchestrator/answer with stream=true."""
    async def _gen():
        async for chunk in _answer_event_iter(
            question, session_id=session_id, request_id=request_id, trace_id=trace_id
        ):
            yield f"data: {json.dumps(chunk)}\n\n"
    return _gen()


def _reject_body_correlation_fields(raw_body: object) -> None:
    forbidden_keys = [
        key
        for key in ("session_id", "request_id", "trace_id")
        if isinstance(raw_body, dict) and key in raw_body
    ]
    if forbidden_keys:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{', '.join(forbidden_keys)} must be sent in headers only: "
                "X-Session-Id, X-Request-Id, X-Trace-Id"
            ),
        )


def _header_ids(request: Request) -> tuple[Optional[str], Optional[str], Optional[str]]:
    return (
        getattr(request.state, "session_id", None),
        getattr(request.state, "request_id", None),
        getattr(request.state, "trace_id", None),
    )


async def _answer_event_iter(
    question: str,
    *,
    session_id: Optional[str],
    request_id: Optional[str],
    trace_id: Optional[str],
) -> AsyncIterator[dict]:
    async for chunk in stream_answer_query(
        question,
        session_id=session_id,
        request_id=request_id,
        trace_id=trace_id,
    ):
        yield chunk


async def _answer_json(
    question: str,
    *,
    session_id: Optional[str],
    request_id: Optional[str],
    trace_id: Optional[str],
) -> dict:
    final: dict = {
        "request_id": request_id,
        "session_id": session_id,
        "trace_id": trace_id,
        "route": None,
        "rewrite": None,
        "answer": None,
        "agent_graph_run_id": None,
        "states": [],
    }
    async for event in _answer_event_iter(
        question,
        session_id=session_id,
        request_id=request_id,
        trace_id=trace_id,
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
            final["agent_graph_run_id"] = event.get("agent_graph_run_id")
        elif t == "state":
            final["states"].append(
                {"phase": event.get("phase"), "message": event.get("message")}
            )
        elif t == "error":
            return {
                **final,
                "status": "error",
                "error": event.get("text"),
            }
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
    path = request.url.path
    method = request.method
    ctx = bind_request_context(
        request_id=request_id,
        session_id=session_id,
        method=method,
        path=path,
    )
    try:
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


class AnswerBody(BaseModel):
    question: str
    stream: bool = False


@app.post("/orchestrator/answer")
async def orchestrator_answer(body: AnswerBody, request: Request):
    """Unified endpoint: stream=true returns SSE; stream=false returns aggregated JSON."""
    raw_body = await request.json()
    _reject_body_correlation_fields(raw_body)
    session_id, request_id, trace_id = _header_ids(request)
    if body.stream:
        return StreamingResponse(
            _sse_stream_answer_gen(
                body.question,
                session_id=session_id,
                request_id=request_id,
                trace_id=trace_id,
            ),
            media_type="text/event-stream",
            headers=SSE_HEADERS,
        )
    result = await _answer_json(
        body.question,
        session_id=session_id,
        request_id=request_id,
        trace_id=trace_id,
    )
    status_code = 200 if result.get("status") == "ok" else 500
    return JSONResponse(result, status_code=status_code)


@app.post("/feedback")
async def submit_feedback(body: FeedbackBody):
    """Submit feedback on an agent response (thumbs up/down, type, optional comment)."""
    if body.feedback_type and body.feedback_type not in FEEDBACK_TYPES:
        return {"status": "error", "message": f"feedback_type must be one of: {', '.join(sorted(FEEDBACK_TYPES))}"}
    agent_graph_run_id = body.agent_graph_run_id or body.request_id
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
    if agent_graph_run_id and has_langsmith_credentials():
        await asyncio.to_thread(
            submit_langsmith_feedback,
            agent_graph_run_id=agent_graph_run_id,
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
