import asyncio
import logging
import uuid
from builtins import BaseExceptionGroup
from typing import Any, AsyncIterator, List, Optional, Tuple

from langchain_core.callbacks import AsyncCallbackHandler

from .agent_graph import build_graph_agent
from .agent_rewrite import rewrite_query
from .config import get_langsmith_tags, settings
from .intent_gate import get_canned_answer
from .utils import last_ai_content


class _AgentRunIdCallback(AsyncCallbackHandler):
    """Capture LangSmith run_id of the root agent_graph run."""

    def __init__(self, run_ids: List[str]):
        self.run_ids = run_ids

    async def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, **kwargs):
        if parent_run_id is None:
            self.run_ids.append(str(run_id))


async def run_graph(
    messages: list,
    servers: Optional[dict],
    tools_timeout_s: float,
    invoke_timeout_s: float,
    *,
    tools: Optional[list] = None,
    rag_http_deterministic: bool = False,
    request_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Tuple[List[Any], Optional[str]]:
    """Run one phase (RAG) and return (messages, agent_graph_run_id). agent_graph_run_id from LangSmith."""
    if not servers and not tools and not rag_http_deterministic:
        return messages, None
    agent = await build_graph_agent(
        servers=servers if servers else None,
        tools=tools,
        tools_timeout_s=tools_timeout_s,
        rag_http_deterministic=rag_http_deterministic,
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
    out = await asyncio.wait_for(
        agent.ainvoke({"messages": messages}, config=config),
        timeout=invoke_timeout_s,
    )
    agent_graph_run_id = run_ids[0] if run_ids else None
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
    try:
        rag_servers = settings.rag_server_config
        use_http_rag = bool(settings.rag_http_base_url)
        yield {"type": "request_id", "session_id": session_id, "request_id": request_id}
        # IntentGate (smalltalk?) — agent
        canned = await get_canned_answer(
            query, request_id=request_id, session_id=session_id
        )
        if canned is not None:
            yield {"type": "answer", "text": canned}
            yield {"type": "state", "phase": "done", "message": "Complete"}
            return
        # no → EntityRewrite (Taixing?) → Router → Graph
        yield {"type": "state", "phase": "rewrite", "message": "Rewriting question..."}
        rewritten = await rewrite_query(query, request_id=request_id, session_id=session_id)
        yield {"type": "rewrite", "text": rewritten}
        yield {"type": "route", "route": "RAG"}
        messages = [{"role": "user", "content": rewritten}]
        agent_graph_run_id = None
        if use_http_rag:
            yield {"type": "state", "phase": "rag", "message": "Running RAG phase..."}
            messages, agent_graph_run_id = await run_graph(
                messages,
                None,
                tools_s,
                invoke_s,
                rag_http_deterministic=True,
                request_id=request_id,
                session_id=session_id,
            )
        elif rag_servers:
            yield {"type": "state", "phase": "rag", "message": "Running RAG phase..."}
            messages, agent_graph_run_id = await run_graph(
                messages,
                rag_servers,
                tools_s,
                invoke_s,
                request_id=request_id,
                session_id=session_id,
            )
        content = last_ai_content(messages)
        if content:
            event = {"type": "answer", "text": content}
            if agent_graph_run_id:
                event["agent_graph_run_id"] = agent_graph_run_id
            yield event
        yield {"type": "state", "phase": "done", "message": "Complete"}
    except Exception as e:
        err_text = format_error(e)
        logging.getLogger("layer_orchestrator.pipeline").error(
            "stream_answer_error",
            extra={
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
