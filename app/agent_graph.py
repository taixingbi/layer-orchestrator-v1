"""Build the FastAPI-only LangGraph agent (HTTP RAG retrieve-only; no answer LLM)."""
import logging
import time
import uuid
from typing import Any, Dict, List, Tuple

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from .agent_graph_state import AgentState
from .config import settings
from .graph_emit import emit_pipeline_state
from .pipeline_state import utc_now_iso
from .rag_http_tool import query_rag_http_with_meta
from .request_context import bind_pipeline_phase
from .utils import first_user_text

_agent_cache: Dict[tuple, Any] = {}
_graph_log = logging.getLogger("layer_orchestrator.agent_graph")


async def build_graph_agent(
    tools_timeout_s: float = 60.0,
):
    """Build (or return cached) compiled LangGraph: single retrieve node, RAG text is the answer."""
    if not settings.rag_http_base_url:
        raise ValueError("RAG_HTTP_BASE_URL is required in FastAPI-only mode")
    url = ((settings.rag_http_base_url or "").rstrip("/") + "/v1/rag/query").lower()
    cache_key: Tuple[Any, ...] = ("rag_http_retrieve_only", url, tools_timeout_s)
    if cache_key in _agent_cache:
        _graph_log.debug(
            "agent_graph_cache_hit",
            extra={"event": "agent_graph_cache_hit", "gateway_meta": {"cache_key": str(cache_key)}},
        )
        return _agent_cache[cache_key]

    async def retrieve_node(state: AgentState, config: RunnableConfig):
        async with bind_pipeline_phase("rag_query"):
            t0 = time.perf_counter()
            cfg = (config or {}).get("configurable") or {}
            question = str(cfg.get("standalone_question") or "").strip() or first_user_text(state["messages"])
            cid = str(cfg.get("conversation_id") or "").strip()
            is_new = bool(cfg.get("is_new_conversation"))
            rag_started_at = utc_now_iso()
            await emit_pipeline_state(
                config,
                phase="rag_query",
                status="running",
                ui_message="Querying knowledge base...",
                started_at=rag_started_at,
                metadata={"question_len": len(question or "")},
            )
            gw_start: Dict[str, Any] = {"question_len": len(question or "")}
            if cid:
                gw_start["conversation_id"] = cid
                gw_start["is_new_conversation"] = is_new
            _graph_log.debug(
                "retrieve_started",
                extra={"event": "retrieve_started", "gateway_meta": gw_start},
            )
            evidence, rag_meta = await query_rag_http_with_meta(
                question,
                str(cfg.get("request_id") or ""),
                str(cfg.get("session_id") or ""),
                str(cfg.get("trace_id") or ""),
                user_id=str(cfg.get("user_id") or ""),
                user_roles=str(cfg.get("user_roles") or ""),
                user_groups=str(cfg.get("user_groups") or ""),
                user_teams=str(cfg.get("user_teams") or ""),
                conversation_id=cid,
                is_new_conversation=is_new,
            )
            _graph_log.debug(
                "rag_query_completed",
                extra={
                    "event": "rag_query_completed",
                    "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
                    "gateway_meta": {
                        "evidence_len": len(evidence or ""),
                        "http_status_code": rag_meta.get("http_status_code"),
                        **({"conversation_id": cid, "is_new_conversation": is_new} if cid else {}),
                    },
                },
            )
            _graph_log.debug(
                "retrieve_completed",
                extra={
                    "event": "retrieve_completed",
                    "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
                    "gateway_meta": {
                        "evidence_len": len(evidence or ""),
                        **({"conversation_id": cid, "is_new_conversation": is_new} if cid else {}),
                    },
                },
            )
            state_meta = {
                "evidence_len": len(evidence or ""),
                **{k: v for k, v in rag_meta.items() if k != "rag_api_response"},
            }
            await emit_pipeline_state(
                config,
                phase="rag_query",
                status="completed",
                ui_message="Knowledge base results received",
                started_at=rag_started_at,
                ended_at=utc_now_iso(),
                latency_ms=(time.perf_counter() - t0) * 1000,
                metadata=state_meta,
            )
            tid = f"call_rag_{uuid.uuid4().hex[:16]}"
            synthetic = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "query_knowledge_base",
                        "args": {"question": question},
                        "id": tid,
                        "type": "tool_call",
                    }
                ],
            )
            sidecar = (rag_meta or {}).get("rag_tool_sidecar") or {}
            rag_envelope: Dict[str, Any] = dict(sidecar) if sidecar else {}
            if (rag_meta or {}).get("usage"):
                rag_envelope["usage"] = rag_meta["usage"]
            tool_kw: Dict[str, Any] = {
                "content": evidence,
                "tool_call_id": tid,
                "name": "query_knowledge_base",
            }
            if rag_envelope:
                tool_kw["additional_kwargs"] = {"rag_envelope": rag_envelope}
            tool_msg = ToolMessage(**tool_kw)
            return {"messages": [synthetic, tool_msg]}

    g = StateGraph(AgentState)
    g.add_node("retrieve", retrieve_node)
    g.add_edge(START, "retrieve")
    g.add_edge("retrieve", END)
    compiled = g.compile()
    _agent_cache[cache_key] = compiled
    _graph_log.info(
        "agent_graph_compiled",
        extra={"event": "agent_graph_compiled", "gateway_meta": {"cache_key": str(cache_key)}},
    )
    return compiled
