"""Main orchestration pipeline: normalize → rewrite → route → intent | tool → answer."""

import asyncio
import logging
import time
import uuid
from builtins import BaseExceptionGroup
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from ..config import settings
from ..intents.registry import resolve_intent_answer
from .state import state_event, utc_now_iso
from ..observability.context import bind_pipeline_phase
from ..schemas.route import (
    InternalIntentRoute,
    RouteDetail,
    ToolRoute,
    legacy_route_from_detail,
    route_detail_to_dict,
)
from ..tools.github_repo_search import run_github_repo_search
from ..tools.user_profile import run_user_profile
from ..tools.web_search import run_web_search
from ..observability.usage import build_usage_payload
from .router import (
    decision_to_route_detail,
    normalize_post_router,
    resolve_route,
    run_intent_rewrite_router,
)

_pipeline_log = logging.getLogger("layer_orchestrator.pipeline")
_downstream_semaphore: Optional[asyncio.Semaphore] = None
_downstream_semaphore_limit: Optional[int] = None


def _get_downstream_semaphore() -> Optional[asyncio.Semaphore]:
    limit = settings.max_concurrent_downstream_calls
    global _downstream_semaphore, _downstream_semaphore_limit
    if limit <= 0:
        _downstream_semaphore = None
        _downstream_semaphore_limit = None
        return None
    if _downstream_semaphore is None or _downstream_semaphore_limit != limit:
        _downstream_semaphore = asyncio.Semaphore(limit)
        _downstream_semaphore_limit = limit
    return _downstream_semaphore


def _answer_event(
    text: str,
    *,
    citations: Optional[List[Any]] = None,
    follow_up_questions: Optional[List[Any]] = None,
    usage: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    event: Dict[str, Any] = {
        "type": "answer",
        "text": text,
        "citations": list(citations) if citations is not None else [],
        "follow_up_questions": list(follow_up_questions) if follow_up_questions is not None else [],
    }
    if usage is not None:
        event["usage"] = usage
    return event


def _answer_delta_event(text: str) -> Dict[str, Any]:
    return {"type": "answer_delta", "text": text}


def _stream_correlation_fields(
    *,
    session_id: Optional[str],
    request_id: str,
    trace_id: Optional[str],
    conversation_id: Optional[str],
    is_new_conversation: bool,
) -> Dict[str, Any]:
    cid = (conversation_id or "").strip() or None
    return {
        "session_id": session_id,
        "request_id": request_id,
        "trace_id": trace_id,
        "conversation_id": cid,
        "is_new_conversation": is_new_conversation,
    }


async def _yield_request_complete_done(
    t0: float,
    request_id: str,
    session_id: Optional[str],
    *,
    trace_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    is_new_conversation: bool = False,
    usage: Optional[Dict[str, Any]] = None,
) -> AsyncIterator[dict]:
    done_ts = utc_now_iso()
    complete_state = state_event(
        phase="request_complete",
        status="completed",
        ui_message="Complete",
        started_at=done_ts,
        ended_at=done_ts,
        latency_ms=0,
    )
    cid = (conversation_id or "").strip() or None
    extra: Dict[str, Any] = {
        "event": "request_completed",
        "request_id": request_id,
        "session_id": session_id or "-",
        "trace_id": (trace_id or request_id or "-"),
        "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
    }
    if cid:
        extra["gateway_meta"] = {"is_new_conversation": bool(is_new_conversation)}
    async with bind_pipeline_phase("request_complete"):
        _pipeline_log.info("request_completed", extra=extra)
    yield complete_state
    done_event: Dict[str, Any] = {
        "type": "done",
        **_stream_correlation_fields(
            session_id=session_id,
            request_id=request_id,
            trace_id=trace_id,
            conversation_id=cid,
            is_new_conversation=is_new_conversation,
        ),
    }
    if usage is not None:
        done_event["usage"] = usage
    yield done_event


def _route_event(detail: RouteDetail, rewrite: str) -> Dict[str, Any]:
    flat = legacy_route_from_detail(detail)
    return {
        "type": "route",
        "route": flat,
        "route_detail": route_detail_to_dict(detail),
        "text": rewrite,
    }


def _internal_answer(detail: RouteDetail, *, direct_answer: Optional[str] = None) -> str:
    if direct_answer and direct_answer.strip():
        return direct_answer.strip()
    if isinstance(detail, InternalIntentRoute):
        if detail.name == "clarify":
            return "Please clarify your question."
        if detail.name == "reject":
            return "I can't help with that request."
    return direct_answer or ""


async def _run_tool(
    detail: ToolRoute,
    question: str,
    *,
    request_id: str,
    session_id: Optional[str],
    trace_id: Optional[str],
    rag_user: Optional[Dict[str, str]],
    conversation_id: str,
    is_new_conversation: bool,
    emit_delta,
) -> Tuple[str, List[Any], List[Any], Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    from ..config import mcp_rag_enabled

    name = detail.name
    if name == "user_profile":
        if not mcp_rag_enabled() and not settings.rag_http_base_url:
            raise ValueError("RAG is not configured (RAG_HTTP_BASE_URL or MCP_RAG_BASE_URL)")
        result = await run_user_profile(
            question,
            request_id=request_id or "",
            session_id=session_id or "",
            trace_id=trace_id or "",
            rag_user=rag_user,
            conversation_id=conversation_id,
            is_new_conversation=is_new_conversation,
            on_delta=emit_delta,
        )
    elif name == "github_repo_search":
        result = await run_github_repo_search(
            question,
            repo=detail.repo,
            request_id=request_id or "",
            session_id=session_id or "",
            trace_id=trace_id or "",
            rag_user=rag_user,
            conversation_id=conversation_id,
            on_delta=emit_delta,
        )
    elif name == "web_search":
        result = await run_web_search(question)
    else:
        raise ValueError(f"Unknown tool: {name}")
    return (
        result.answer,
        result.citations,
        result.follow_up_questions,
        result.usage,
        result.latency_ms,
    )


async def stream_answer_query(
    query: str,
    *,
    session_id: Optional[str] = None,
    request_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    rag_user: Optional[Dict[str, str]] = None,
    history: Optional[List[Tuple[str, str]]] = None,
    conversation_id: Optional[str] = None,
    is_new_conversation: bool = False,
    tools_timeout_s: Optional[float] = None,
    invoke_timeout_s: Optional[float] = None,
) -> AsyncIterator[dict]:
    """Stream assistant reply: rewrite → route → internal intent | tool → answer."""
    request_id = request_id or str(uuid.uuid4())
    hist = list(history) if history else []
    conv = (conversation_id or "").strip()
    conv_gw = (
        {"conversation_id": conv, "is_new_conversation": bool(is_new_conversation)} if conv else {}
    )
    t0 = time.perf_counter()
    intent_router_usage: Optional[Dict[str, int]] = None
    tool_usage: Optional[Dict[str, Any]] = None
    route_detail: Optional[RouteDetail] = None
    rewrite_text = (query or "").strip()
    direct_answer: Optional[str] = None

    try:
        async with bind_pipeline_phase("request"):
            _pipeline_log.info(
                "request_started",
                extra={
                    "event": "request_started",
                    "request_id": request_id,
                    "session_id": session_id or "-",
                    "gateway_meta": dict(conv_gw),
                },
            )
        yield {
            "type": "request_id",
            **_stream_correlation_fields(
                session_id=session_id,
                request_id=request_id,
                trace_id=trace_id,
                conversation_id=conv or conversation_id,
                is_new_conversation=is_new_conversation,
            ),
        }

        router_started_perf = time.perf_counter()
        router_started_at = utc_now_iso()
        yield state_event(
            phase="intent_router",
            status="running",
            ui_message="Routing request...",
            started_at=router_started_at,
            metadata={"query_len": len(query or "")},
        )

        pre = resolve_route(query, hist)
        if pre:
            route_detail, direct_answer, rewrite_text = pre
        else:
            async with bind_pipeline_phase("intent_router"):
                decision = await run_intent_rewrite_router(
                    query,
                    hist,
                    request_id=request_id,
                    session_id=session_id,
                    trace_id=trace_id,
                    conversation_id=conv or None,
                    is_new_conversation=is_new_conversation,
                )
                decision = normalize_post_router(decision, latest_question=query, history=hist)
                intent_router_usage = decision.router_usage
                route_detail = decision_to_route_detail(decision)
                rewrite_text = (decision.rewritten_question or query or "").strip()
                direct_answer = decision.direct_answer
                if decision.route in ("direct_reply", "clarify", "reject") and not isinstance(
                    route_detail, ToolRoute
                ):
                    name = decision.route if decision.route != "direct_reply" else "help"
                    route_detail = InternalIntentRoute(
                        name=name if name in ("clarify", "reject") else "help",
                        confidence=1.0,
                        reason=decision.reason or "",
                    )

        flat_route = legacy_route_from_detail(route_detail)
        router_ended_at = utc_now_iso()
        yield state_event(
            phase="intent_router",
            status="completed",
            ui_message="Route selected",
            started_at=router_started_at,
            ended_at=router_ended_at,
            latency_ms=(time.perf_counter() - router_started_perf) * 1000,
            metadata={
                "route": flat_route,
                "route_detail": route_detail_to_dict(route_detail),
                "rewritten_len": len(rewrite_text),
            },
        )
        yield {"type": "rewrite", "text": rewrite_text}
        yield _route_event(route_detail, rewrite_text)

        request_usage = build_usage_payload(intent_router=intent_router_usage)

        if isinstance(route_detail, InternalIntentRoute):
            answer_text = _internal_answer(route_detail, direct_answer=direct_answer)
            if route_detail.name in ("identity", "greeting", "help", "capabilities") and not answer_text:
                answer_text = resolve_intent_answer(route_detail.name) or answer_text
            yield _answer_event(answer_text, usage=request_usage)
            async for ev in _yield_request_complete_done(
                t0,
                request_id,
                session_id,
                trace_id=trace_id,
                conversation_id=conv or None,
                is_new_conversation=is_new_conversation,
                usage=request_usage,
            ):
                yield ev
            return

        if isinstance(route_detail, ToolRoute):
            tool_started = utc_now_iso()
            tool_started_perf = time.perf_counter()
            yield state_event(
                phase="rag" if route_detail.name == "user_profile" else "tool",
                status="running",
                ui_message=f"Running {route_detail.name}...",
                started_at=tool_started,
                metadata={"tool": route_detail.name},
            )
            delta_queue: asyncio.Queue[Optional[str]] = asyncio.Queue()

            def _emit_delta(chunk: str) -> None:
                if chunk:
                    delta_queue.put_nowait(chunk)

            async def _tool_task() -> Tuple[str, List[Any], List[Any], Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
                sem = _get_downstream_semaphore()
                try:
                    if sem is not None:
                        async with sem:
                            return await _run_tool(
                                route_detail,
                                rewrite_text,
                                request_id=request_id,
                                session_id=session_id,
                                trace_id=trace_id,
                                rag_user=rag_user,
                                conversation_id=conv,
                                is_new_conversation=is_new_conversation,
                                emit_delta=_emit_delta,
                            )
                    return await _run_tool(
                        route_detail,
                        rewrite_text,
                        request_id=request_id,
                        session_id=session_id,
                        trace_id=trace_id,
                        rag_user=rag_user,
                        conversation_id=conv,
                        is_new_conversation=is_new_conversation,
                        emit_delta=_emit_delta,
                    )
                finally:
                    delta_queue.put_nowait(None)

            task = asyncio.create_task(_tool_task())
            while True:
                chunk = await delta_queue.get()
                if chunk is None:
                    break
                yield _answer_delta_event(chunk)
            answer_text, citations, follow_ups, t_usage, t_latency = await task

            tool_usage = t_usage
            rag_part = tool_usage if route_detail.name == "user_profile" else None
            request_usage = build_usage_payload(intent_router=intent_router_usage, rag=rag_part)

            yield state_event(
                phase="rag" if route_detail.name == "user_profile" else "tool",
                status="completed",
                ui_message=f"{route_detail.name} completed",
                started_at=tool_started,
                ended_at=utc_now_iso(),
                latency_ms=(time.perf_counter() - tool_started_perf) * 1000,
                metadata={"tool": route_detail.name, "tool_latency_ms": t_latency},
            )
            yield _answer_event(
                answer_text,
                citations=citations,
                follow_up_questions=follow_ups,
                usage=request_usage,
            )
            async for ev in _yield_request_complete_done(
                t0,
                request_id,
                session_id,
                trace_id=trace_id,
                conversation_id=conv or None,
                is_new_conversation=is_new_conversation,
                usage=request_usage,
            ):
                yield ev
            return

        raise ValueError("No route_detail resolved")

    except Exception as e:
        err_text = format_error(e)
        async with bind_pipeline_phase("error"):
            fail_ts = utc_now_iso()
            if not getattr(e, "_pipeline_logged", False):
                err_extra: Dict[str, Any] = {
                    "event": "stream_answer_error",
                    "request_id": request_id,
                    "session_id": session_id or "-",
                    "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
                    "structured_error": {"type": type(e).__name__, "message": str(e)},
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                }
                if conv:
                    err_extra["gateway_meta"] = dict(conv_gw)
                _pipeline_log.error("stream_answer_error", extra=err_extra)
        yield state_event(
            phase="request_complete",
            status="failed",
            ui_message="Request failed",
            started_at=fail_ts,
            ended_at=fail_ts,
            latency_ms=0,
            metadata={"error_type": type(e).__name__},
        )
        err_event: Dict[str, Any] = {
            "type": "error",
            "text": err_text,
            **_stream_correlation_fields(
                session_id=session_id,
                request_id=request_id,
                trace_id=trace_id,
                conversation_id=conv or conversation_id,
                is_new_conversation=is_new_conversation,
            ),
        }
        err_event["usage"] = build_usage_payload(intent_router=intent_router_usage, rag=tool_usage)
        yield err_event


def format_error(e: BaseException) -> str:
    if isinstance(e, BaseExceptionGroup) and e.exceptions:
        return format_error(e.exceptions[0])
    return f"Error: {type(e).__name__}: {e}"


async def answer_query_sync(
    query: str,
    *,
    tools_timeout_s: Optional[float] = None,
    invoke_timeout_s: Optional[float] = None,
    request_id: Optional[str] = None,
    session_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    rag_user: Optional[Dict[str, str]] = None,
    history: Optional[List[Tuple[str, str]]] = None,
    conversation_id: Optional[str] = None,
    is_new_conversation: bool = False,
) -> str:
    answer = ""
    async for event in stream_answer_query(
        query,
        request_id=request_id,
        session_id=session_id,
        trace_id=trace_id,
        rag_user=rag_user,
        history=list(history) if history is not None else None,
        conversation_id=conversation_id,
        is_new_conversation=is_new_conversation,
        tools_timeout_s=tools_timeout_s,
        invoke_timeout_s=invoke_timeout_s,
    ):
        if event.get("type") == "answer":
            answer = event.get("text", "")
        elif event.get("type") == "error":
            return event.get("text", "Unknown error")
    return answer
