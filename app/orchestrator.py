import asyncio
import contextlib
import logging
import time
import uuid
from builtins import BaseExceptionGroup
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional, Tuple

from langchain_core.callbacks import AsyncCallbackHandler

from .agent_graph import build_graph_agent
from .config import get_langsmith_tags, settings
from .intent_rewrite_router import (
    normalize_post_router,
    run_intent_rewrite_router,
)
from .pipeline_state import state_event, utc_now_iso
from .request_context import bind_pipeline_phase
from .utils import last_rag_tool_envelope, last_rag_tool_evidence

_pipeline_log = logging.getLogger("layer_orchestrator.pipeline")
_downstream_semaphore: Optional[asyncio.Semaphore] = None
_downstream_semaphore_limit: Optional[int] = None


def _get_downstream_semaphore() -> Optional[asyncio.Semaphore]:
    """Optional cap for concurrent downstream graph/RAG work."""
    global _downstream_semaphore, _downstream_semaphore_limit
    limit = settings.max_concurrent_downstream_calls
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
) -> Dict[str, Any]:
    """Answer SSE/JSON chunk; citations and follow-ups always present (empty when not from RAG)."""
    return {
        "type": "answer",
        "text": text,
        "citations": list(citations) if citations is not None else [],
        "follow_up_questions": list(follow_up_questions) if follow_up_questions is not None else [],
    }


def _stream_correlation_fields(
    *,
    session_id: Optional[str],
    request_id: str,
    trace_id: Optional[str],
    conversation_id: Optional[str],
    is_new_conversation: bool,
) -> Dict[str, Any]:
    """Correlation ids echoed on stream events (request_id, done, error)."""
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
) -> AsyncIterator[dict]:
    """Terminal success: request_complete state + log + done event."""
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
    yield {
        "type": "done",
        **_stream_correlation_fields(
            session_id=session_id,
            request_id=request_id,
            trace_id=trace_id,
            conversation_id=cid,
            is_new_conversation=is_new_conversation,
        ),
    }


class _AgentRunIdCallback(AsyncCallbackHandler):
    """Capture LangSmith run_id of the root agent_graph run."""

    def __init__(self, run_ids: List[str]):
        self.run_ids = run_ids

    async def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, **kwargs):
        if parent_run_id is None:
            self.run_ids.append(str(run_id))


async def run_graph(
    messages: list,
    tools_timeout_s: float,
    invoke_timeout_s: float,
    *,
    request_id: Optional[str] = None,
    session_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    rag_user: Optional[Dict[str, str]] = None,
    standalone_question: Optional[str] = None,
    emit_state: Optional[Callable[..., Awaitable[None]]] = None,
    downstream_acquire_timeout_s: Optional[float] = None,
    conversation_id: Optional[str] = None,
    is_new_conversation: bool = False,
) -> Tuple[List[Any], Optional[str]]:
    """Run one phase (RAG) and return (messages, agent_graph_run_id). agent_graph_run_id from LangSmith."""
    t0 = time.perf_counter()
    semaphore = _get_downstream_semaphore()
    acquired = False
    if semaphore is not None:
        if downstream_acquire_timeout_s is not None:
            await asyncio.wait_for(semaphore.acquire(), timeout=downstream_acquire_timeout_s)
        else:
            await semaphore.acquire()
        acquired = True
    try:
        cg = (conversation_id or "").strip()
        async with bind_pipeline_phase("agent_graph"):
            _pipeline_log.info(
                "graph_run_started",
                extra={
                    "event": "graph_run_started",
                    "request_id": request_id or "-",
                    "session_id": session_id or "-",
                    **({"gateway_meta": {"conversation_id": cg, "is_new_conversation": bool(is_new_conversation)}} if cg else {}),
                },
            )
            agent = await build_graph_agent(
                tools_timeout_s=tools_timeout_s,
            )
            run_ids: List[str] = []
            callback = _AgentRunIdCallback(run_ids)
            configurable = {
                k: v
                for k, v in (("request_id", request_id), ("session_id", session_id), ("trace_id", trace_id))
                if v is not None
            }
            if rag_user:
                for key in ("user_id", "user_roles", "user_groups", "user_teams"):
                    v = rag_user.get(key)
                    if v:
                        configurable[key] = v
            if cg:
                configurable["conversation_id"] = cg
                configurable["is_new_conversation"] = bool(is_new_conversation)
            if standalone_question:
                configurable["standalone_question"] = standalone_question
            if emit_state is not None:
                configurable["emit_state"] = emit_state
            config = {
                "run_name": "agent_graph",
                "callbacks": [callback],
                "tags": get_langsmith_tags(
                    request_id=request_id,
                    session_id=session_id,
                    conversation_id=cg or None,
                ),
                "configurable": configurable,
            }
            try:
                out = await asyncio.wait_for(
                    agent.ainvoke({"messages": messages}, config=config),
                    timeout=invoke_timeout_s,
                )
            except Exception as e:
                _pipeline_log.error(
                    "graph_run_failed",
                    extra={
                        "event": "graph_run_failed",
                        "request_id": request_id or "-",
                        "session_id": session_id or "-",
                        "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                        "structured_error": {"type": type(e).__name__, "message": str(e)},
                    },
                )
                setattr(e, "_pipeline_logged", True)
                raise
            agent_graph_run_id = run_ids[0] if run_ids else None
            _pipeline_log.info(
                "graph_run_completed",
                extra={
                    "event": "graph_run_completed",
                    "request_id": request_id or "-",
                    "session_id": session_id or "-",
                    "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
                    "gateway_meta": {"has_agent_graph_run_id": bool(agent_graph_run_id)},
                },
            )
            return out["messages"], agent_graph_run_id
    finally:
        if acquired and semaphore is not None:
            semaphore.release()


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
    """Run agent and return the final answer. Consumes stream_answer_query for single code path."""
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
    """Stream the assistant reply. Intent/rewrite router (one LLM) → rag | direct_reply | clarify | reject."""
    request_id = request_id or str(uuid.uuid4())
    tools_s = tools_timeout_s if tools_timeout_s is not None else settings.tools_timeout_s
    invoke_s = invoke_timeout_s if invoke_timeout_s is not None else settings.invoke_timeout_s
    request_timeout_s = settings.request_timeout_ms / 1000.0
    t0 = time.perf_counter()
    use_http_rag = bool(settings.rag_http_base_url)
    hist = list(history) if history else []
    conv = (conversation_id or "").strip()
    conv_gw = (
        {"conversation_id": conv, "is_new_conversation": bool(is_new_conversation)} if conv else {}
    )
    try:
        async with bind_pipeline_phase("request"):
            _pipeline_log.info(
                "request_started",
                extra={
                    "event": "request_started",
                    "request_id": request_id,
                    "session_id": session_id or "-",
                    "gateway_meta": {
                        "tools_timeout_s": tools_s,
                        "invoke_timeout_s": invoke_s,
                        "conversation_id": conv or None,
                        "is_new_conversation": is_new_conversation,
                    },
                },
            )
            _pipeline_log.debug(
                "request_context",
                extra={
                    "event": "request_context",
                    "request_id": request_id,
                    "session_id": session_id or "-",
                    "gateway_meta": {
                        "query_len": len(query or ""),
                        "query_preview": (query or "")[:120] or None,
                        "use_http_rag": use_http_rag,
                    },
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
            router_ended_at = utc_now_iso()
            _pipeline_log.info(
                "intent_router_phase_completed",
                extra={
                    "event": "intent_router_phase_completed",
                    "request_id": request_id,
                    "session_id": session_id or "-",
                    "gateway_meta": {
                        "route": decision.route,
                        "rewritten_preview": (decision.rewritten_question or "")[:120] or None,
                        **conv_gw,
                    },
                },
            )
        yield state_event(
            phase="intent_router",
            status="completed",
            ui_message="Route selected",
            started_at=router_started_at,
            ended_at=router_ended_at,
            latency_ms=(time.perf_counter() - router_started_perf) * 1000,
            metadata={
                "route": decision.route,
                "reason": (decision.reason or "")[:500] or None,
                "rewritten_len": len(decision.rewritten_question or ""),
            },
        )
        yield {"type": "rewrite", "text": decision.rewritten_question}
        yield {"type": "route", "route": decision.route}

        if decision.route != "rag":
            if decision.route == "direct_reply":
                answer_text = (decision.direct_answer or "").strip()
            elif decision.route == "clarify":
                answer_text = (decision.direct_answer or "").strip() or "Please clarify your question."
            else:
                answer_text = (decision.direct_answer or "").strip() or "I can't help with that request."
            _pipeline_log.info(
                "router_terminal_answer",
                extra={
                    "event": "router_terminal_answer",
                    "request_id": request_id,
                    "session_id": session_id or "-",
                    "gateway_meta": {
                        "route": decision.route,
                        "answer_len": len(answer_text),
                        **conv_gw,
                    },
                },
            )
            yield _answer_event(answer_text)
            async for ev in _yield_request_complete_done(
                t0,
                request_id,
                session_id,
                trace_id=trace_id,
                conversation_id=conv or None,
                is_new_conversation=is_new_conversation,
            ):
                yield ev
            return

        rewritten = (decision.rewritten_question or "").strip()
        messages = [{"role": "user", "content": rewritten}]
        agent_graph_run_id = None
        if not use_http_rag:
            skipped_ts = utc_now_iso()
            yield state_event(
                phase="rag",
                status="skipped",
                ui_message="RAG skipped: configuration missing",
                started_at=skipped_ts,
                ended_at=skipped_ts,
                latency_ms=0,
            )
            raise ValueError("RAG_HTTP_BASE_URL is required in FastAPI-only mode")
        rag_started_perf = time.perf_counter()
        rag_started_at = utc_now_iso()
        yield state_event(
            phase="rag",
            status="running",
            ui_message="Running RAG phase...",
            started_at=rag_started_at,
            metadata={
                "collection": settings.rag_collection_base,
                "k": settings.rag_k,
                "k_max": settings.rag_k_max,
            },
        )
        async with bind_pipeline_phase("rag"):
            _pipeline_log.info(
                "rag_started",
                extra={
                    "event": "rag_started",
                    "request_id": request_id,
                    "session_id": session_id or "-",
                    **({"gateway_meta": dict(conv_gw)} if conv_gw else {}),
                },
            )
        state_queue: asyncio.Queue = asyncio.Queue()

        async def emit_graph_state(**kwargs):
            await state_queue.put(state_event(**kwargs))

        graph_task = asyncio.create_task(
            run_graph(
                messages,
                tools_s,
                invoke_s,
                request_id=request_id,
                session_id=session_id,
                trace_id=trace_id,
                rag_user=rag_user,
                standalone_question=rewritten.strip(),
                emit_state=emit_graph_state,
                downstream_acquire_timeout_s=request_timeout_s,
                conversation_id=conv or None,
                is_new_conversation=is_new_conversation,
            )
        )
        try:
            while not graph_task.done():
                get_task = asyncio.create_task(state_queue.get())
                done, _ = await asyncio.wait(
                    {graph_task, get_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if get_task in done:
                    try:
                        ev = get_task.result()
                    except asyncio.CancelledError:
                        continue
                    yield ev
                if graph_task in done:
                    if not get_task.done():
                        get_task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await get_task
                    break
            while True:
                try:
                    yield state_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
            messages, agent_graph_run_id = graph_task.result()
        except BaseException:
            if not graph_task.done():
                graph_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await graph_task
            raise
        graph_answer = last_rag_tool_evidence(messages)
        if graph_answer:
            async with bind_pipeline_phase("rag"):
                _pipeline_log.info(
                    "answer_emitted",
                    extra={
                        "event": "answer_emitted",
                        "request_id": request_id,
                        "session_id": session_id or "-",
                        "gateway_meta": {"answer_len": len(graph_answer), **conv_gw},
                    },
                )
            env = last_rag_tool_envelope(messages)
            yield _answer_event(
                graph_answer,
                citations=env.get("citations"),
                follow_up_questions=env.get("follow_up_questions"),
            )
        rag_ended_at = utc_now_iso()
        yield state_event(
            phase="rag",
            status="completed",
            ui_message="RAG phase completed",
            started_at=rag_started_at,
            ended_at=rag_ended_at,
            latency_ms=(time.perf_counter() - rag_started_perf) * 1000,
            metadata={
                "collection": settings.rag_collection_base,
                "k": settings.rag_k,
                "k_max": settings.rag_k_max,
            },
        )
        async with bind_pipeline_phase("rag"):
            _pipeline_log.info(
                "rag_completed",
                extra={
                    "event": "rag_completed",
                    "request_id": request_id,
                    "session_id": session_id or "-",
                    "latency_ms": round((time.perf_counter() - rag_started_perf) * 1000, 2),
                    "gateway_meta": {
                        "has_agent_graph_run_id": bool(agent_graph_run_id),
                        **conv_gw,
                    },
                },
            )
        async for ev in _yield_request_complete_done(
            t0,
            request_id,
            session_id,
            trace_id=trace_id,
            conversation_id=conv or None,
            is_new_conversation=is_new_conversation,
        ):
            yield ev
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
        yield {
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


def format_error(e: BaseException) -> str:
    """Unwrap ExceptionGroup / BaseExceptionGroup to the first underlying cause."""
    if isinstance(e, BaseExceptionGroup) and e.exceptions:
        return format_error(e.exceptions[0])
    return f"Error: {type(e).__name__}: {e}"
