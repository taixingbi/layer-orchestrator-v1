import asyncio
import logging
import time
import uuid
from builtins import BaseExceptionGroup
from typing import Any, AsyncIterator, List, Optional, Tuple

from langchain_core.callbacks import AsyncCallbackHandler

from .agent_graph import build_graph_agent
from .agent_rewrite import rewrite_query
from .config import get_langsmith_tags, settings
from .intent_gate import get_canned_answer
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
    configurable = {k: v for k, v in (("request_id", request_id), ("session_id", session_id)) if v is not None}
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
) -> str:
    """Run agent and return the final answer. Consumes stream_answer_query for single code path."""
    answer = ""
    async for event in stream_answer_query(
        query,
        request_id=request_id,
        session_id=session_id,
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
            query, request_id=request_id, session_id=session_id
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
            yield {"type": "state", "phase": "done", "message": "Complete"}
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
        _pipeline_log.info(
            "rewrite_started",
            extra={"event": "rewrite_started", "request_id": request_id, "session_id": session_id or "-"},
        )
        yield {"type": "state", "phase": "rewrite", "message": "Rewriting question..."}
        rewritten = await rewrite_query(query, request_id=request_id, session_id=session_id)
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
        messages = [{"role": "user", "content": rewritten}]
        agent_graph_run_id = None
        if not use_http_rag:
            raise ValueError("RAG_HTTP_BASE_URL is required in FastAPI-only mode")
        _pipeline_log.info(
            "rag_started",
            extra={"event": "rag_started", "request_id": request_id, "session_id": session_id or "-"},
        )
        yield {"type": "state", "phase": "rag", "message": "Running RAG phase..."}
        rag_t0 = time.perf_counter()
        messages, agent_graph_run_id = await run_graph(
            messages,
            tools_s,
            invoke_s,
            request_id=request_id,
            session_id=session_id,
        )
        _pipeline_log.info(
            "rag_completed",
            extra={
                "event": "rag_completed",
                "request_id": request_id,
                "session_id": session_id or "-",
                "latency_ms": round((time.perf_counter() - rag_t0) * 1000, 2),
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
        yield {"type": "state", "phase": "done", "message": "Complete"}
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
