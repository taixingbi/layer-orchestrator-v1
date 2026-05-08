import asyncio
import contextlib
import logging
import time
import uuid
from builtins import BaseExceptionGroup
from typing import Any, AsyncIterator, Awaitable, Callable, List, Optional, Tuple

from langchain_core.callbacks import AsyncCallbackHandler

from .agent_graph import build_graph_agent
from .agent_rewrite import rewrite_query
from .config import get_langsmith_tags, settings
from .intent_gate import get_canned_answer
from .pipeline_state import state_event, utc_now_iso
from .utils import last_ai_content

_pipeline_log = logging.getLogger("layer_orchestrator.pipeline")


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
    emit_state: Optional[Callable[..., Awaitable[None]]] = None,
) -> Tuple[List[Any], Optional[str]]:
    """Run one phase (RAG) and return (messages, agent_graph_run_id). agent_graph_run_id from LangSmith."""
    t0 = time.perf_counter()
    _pipeline_log.info(
        "graph_run_started",
        extra={"event": "graph_run_started", "request_id": request_id or "-", "session_id": session_id or "-"},
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
    if emit_state is not None:
        configurable["emit_state"] = emit_state
    config = {
        "run_name": "agent_graph",
        "callbacks": [callback],
        "tags": get_langsmith_tags(request_id=request_id, session_id=session_id),
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


async def answer_query_sync(
    query: str,
    *,
    tools_timeout_s: Optional[float] = None,
    invoke_timeout_s: Optional[float] = None,
    request_id: Optional[str] = None,
    session_id: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> str:
    """Run agent and return the final answer. Consumes stream_answer_query for single code path."""
    answer = ""
    async for event in stream_answer_query(
        query,
        request_id=request_id,
        session_id=session_id,
        trace_id=trace_id,
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
    tools_timeout_s: Optional[float] = None,
    invoke_timeout_s: Optional[float] = None,
) -> AsyncIterator[dict]:
    """Stream the assistant reply. IntentGate (smalltalk) → canned answer; else EntityRewrite → Router → Graph (RAG)."""
    request_id = request_id or str(uuid.uuid4())
    tools_s = tools_timeout_s if tools_timeout_s is not None else settings.tools_timeout_s
    invoke_s = invoke_timeout_s if invoke_timeout_s is not None else settings.invoke_timeout_s
    t0 = time.perf_counter()
    _pipeline_log.info(
        "request_started",
        extra={
            "event": "request_started",
            "request_id": request_id,
            "session_id": session_id or "-",
            "gateway_meta": {"tools_timeout_s": tools_s, "invoke_timeout_s": invoke_s},
        },
    )
    try:
        use_http_rag = bool(settings.rag_http_base_url)
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
        yield {"type": "request_id", "session_id": session_id, "request_id": request_id}
        # IntentGate (smalltalk?) — agent
        canned = await get_canned_answer(
            query, request_id=request_id, session_id=session_id, trace_id=trace_id
        )
        if canned is not None:
            _pipeline_log.info(
                "intent_gate_canned",
                extra={
                    "event": "intent_gate_canned",
                    "request_id": request_id,
                    "session_id": session_id or "-",
                    "gateway_meta": {"answer_len": len(canned)},
                },
            )
            yield {"type": "answer", "text": canned}
            done_ts = utc_now_iso()
            yield state_event(
                phase="request_complete",
                status="completed",
                ui_message="Complete",
                started_at=done_ts,
                ended_at=done_ts,
                latency_ms=0,
            )
            _pipeline_log.info(
                "request_completed",
                extra={
                    "event": "request_completed",
                    "request_id": request_id,
                    "session_id": session_id or "-",
                    "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
                },
            )
            return
        # no → EntityRewrite (Taixing?) → Router → Graph
        rewrite_started_perf = time.perf_counter()
        rewrite_started_at = utc_now_iso()
        yield state_event(
            phase="rewrite",
            status="running",
            ui_message="Rewriting question...",
            started_at=rewrite_started_at,
            metadata={"query_len": len(query or "")},
        )
        _pipeline_log.info(
            "rewrite_started",
            extra={"event": "rewrite_started", "request_id": request_id, "session_id": session_id or "-"},
        )
        rewritten = await rewrite_query(
            query,
            request_id=request_id,
            session_id=session_id,
            trace_id=trace_id,
        )
        rewrite_ended_at = utc_now_iso()
        yield state_event(
            phase="rewrite",
            status="completed",
            ui_message="Question rewritten",
            started_at=rewrite_started_at,
            ended_at=rewrite_ended_at,
            latency_ms=(time.perf_counter() - rewrite_started_perf) * 1000,
            metadata={"rewritten_len": len(rewritten or "")},
        )
        _pipeline_log.info(
            "rewrite_completed",
            extra={
                "event": "rewrite_completed",
                "request_id": request_id,
                "session_id": session_id or "-",
                "gateway_meta": {"rewritten_len": len(rewritten or "")},
            },
        )
        _pipeline_log.debug(
            "rewrite_diagnostics",
            extra={
                "event": "rewrite_diagnostics",
                "request_id": request_id,
                "session_id": session_id or "-",
                "gateway_meta": {
                    "original_len": len(query or ""),
                    "rewritten_len": len(rewritten or ""),
                    "rewritten_preview": (rewritten or "")[:120] or None,
                },
            },
        )
        yield {"type": "rewrite", "text": rewritten}
        _pipeline_log.info(
            "route_selected",
            extra={
                "event": "route_selected",
                "request_id": request_id,
                "session_id": session_id or "-",
                "gateway_meta": {"route": "RAG"},
            },
        )
        yield {"type": "route", "route": "RAG"}
        route_ts = utc_now_iso()
        yield state_event(
            phase="route_decision",
            status="completed",
            ui_message="Route selected",
            started_at=route_ts,
            ended_at=route_ts,
            latency_ms=0,
            metadata={"route": "RAG"},
        )
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
        _pipeline_log.info(
            "rag_started",
            extra={"event": "rag_started", "request_id": request_id, "session_id": session_id or "-"},
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
                emit_state=emit_graph_state,
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
        _pipeline_log.info(
            "rag_completed",
            extra={
                "event": "rag_completed",
                "request_id": request_id,
                "session_id": session_id or "-",
                "latency_ms": round((time.perf_counter() - rag_started_perf) * 1000, 2),
                "gateway_meta": {"has_agent_graph_run_id": bool(agent_graph_run_id)},
            },
        )
        content = last_ai_content(messages)
        if content:
            _pipeline_log.info(
                "answer_emitted",
                extra={
                    "event": "answer_emitted",
                    "request_id": request_id,
                    "session_id": session_id or "-",
                    "gateway_meta": {"answer_len": len(content)},
                },
            )
            event = {"type": "answer", "text": content}
            if agent_graph_run_id:
                event["agent_graph_run_id"] = agent_graph_run_id
            yield event
        done_ts = utc_now_iso()
        yield state_event(
            phase="request_complete",
            status="completed",
            ui_message="Complete",
            started_at=done_ts,
            ended_at=done_ts,
            latency_ms=0,
        )
        _pipeline_log.info(
            "request_completed",
            extra={
                "event": "request_completed",
                "request_id": request_id,
                "session_id": session_id or "-",
                "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
            },
        )
    except Exception as e:
        err_text = format_error(e)
        fail_ts = utc_now_iso()
        yield state_event(
            phase="request_complete",
            status="failed",
            ui_message="Request failed",
            started_at=fail_ts,
            ended_at=fail_ts,
            latency_ms=0,
            metadata={"error_type": type(e).__name__},
        )
        if not getattr(e, "_pipeline_logged", False):
            _pipeline_log.error(
                "stream_answer_error",
                extra={
                    "event": "stream_answer_error",
                    "request_id": request_id,
                    "session_id": session_id or "-",
                    "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
                    "structured_error": {"type": type(e).__name__, "message": str(e)},
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                },
            )
        yield {"type": "error", "text": err_text}


def format_error(e: BaseException) -> str:
    """Unwrap ExceptionGroup / BaseExceptionGroup to the first underlying cause."""
    if isinstance(e, BaseExceptionGroup) and e.exceptions:
        return format_error(e.exceptions[0])
    return f"Error: {type(e).__name__}: {e}"
