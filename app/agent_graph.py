"""Build the FastAPI-only LangGraph agent (HTTP RAG + judge loop)."""
import logging
import time
import uuid
from typing import Any, Dict, List, Literal, Optional, Tuple

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START

from .agent_graph_state import AgentState
from .config import gateway_llm_invoke_kwargs, get_llm, settings
from .graph_emit import emit_pipeline_state
from .graph_judge import judge_node
from .pipeline_state import utc_now_iso
from .rag_http_tool import query_rag_http_with_meta
from .request_context import bind_pipeline_phase
from .utils import extract_message_content, first_user_text, message_role

_agent_cache: Dict[tuple, Any] = {}
_graph_log = logging.getLogger("layer_orchestrator.agent_graph")

_ANSWER_SYSTEM = "Answer using the retrieved context. Be concise."


def _tool_evidence_text(messages: List[Any]) -> str:
    chunks: List[str] = []
    for m in messages:
        if message_role(m) == "tool":
            c = extract_message_content(m)
            if c:
                chunks.append(c)
    return "\n\n".join(chunks) if chunks else ""


def _last_real_ai_answer(messages: List[Any]) -> Optional[str]:
    for m in reversed(messages):
        if message_role(m) not in ("ai", "assistant"):
            continue
        tcalls = getattr(m, "tool_calls", None) or (
            m.get("tool_calls") if isinstance(m, dict) else None
        )
        if tcalls:
            continue
        c = (extract_message_content(m) or "").strip()
        if c:
            return c
    return None


def _judge_feedback_content(messages: List[Any]) -> Optional[str]:
    for m in reversed(messages):
        if message_role(m) not in ("human", "user"):
            continue
        c = extract_message_content(m) or ""
        if "not good enough" in c.lower():
            return c
    return None


def _build_answer_human_content(cfg: Dict[str, Any], state: AgentState, evidence: str) -> str:
    orig = str(cfg.get("original_question") or "").strip() or first_user_text(state["messages"])
    standalone = str(cfg.get("standalone_question") or "").strip() or first_user_text(state["messages"])
    parts = [f"Original user question:\n{orig}", f"Standalone question:\n{standalone}"]
    hist = str(cfg.get("history_snippet") or "").strip()
    if hist:
        parts.append(f"Conversation context:\n{hist}")
    parts.append(f"Retrieved context:\n{evidence}")
    return "\n\n".join(parts)


def _judge_continue(state: AgentState) -> Literal["__end__", "llm_call"]:
    return "__end__" if state.get("judge_passed") else "llm_call"


async def build_graph_agent(
    tools_timeout_s: float = 60.0,
):
    """Build (or return cached) compiled LangGraph agent (HTTP RAG deterministic mode)."""
    if not settings.rag_http_base_url:
        raise ValueError("RAG_HTTP_BASE_URL is required in FastAPI-only mode")
    url = ((settings.rag_http_base_url or "").rstrip("/") + "/v1/rag/query").lower()
    cache_key: Tuple[Any, ...] = ("rag_http_det", url, tools_timeout_s)
    if cache_key in _agent_cache:
        _graph_log.debug(
            "agent_graph_cache_hit",
            extra={"event": "agent_graph_cache_hit", "gateway_meta": {"cache_key": str(cache_key)}},
        )
        return _agent_cache[cache_key]

    base_llm = get_llm(temperature=0)

    async def retrieve_node(state: AgentState, config: RunnableConfig):
        async with bind_pipeline_phase("rag_query"):
            t0 = time.perf_counter()
            cfg = (config or {}).get("configurable") or {}
            question = str(cfg.get("standalone_question") or "").strip() or first_user_text(state["messages"])
            rag_started_at = utc_now_iso()
            await emit_pipeline_state(
                config,
                phase="rag_query",
                status="running",
                ui_message="Querying knowledge base...",
                started_at=rag_started_at,
                metadata={"question_len": len(question or "")},
            )
            _graph_log.debug(
                "retrieve_started",
                extra={"event": "retrieve_started", "gateway_meta": {"question_len": len(question or "")}},
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
            )
            _graph_log.info(
                "rag_query_api_response",
                extra={
                    "event": "rag_query_api_response",
                    "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
                    "gateway_meta": {
                        "evidence_len": len(evidence or ""),
                        "http_status_code": rag_meta.get("http_status_code"),
                        "rag_api_response": rag_meta.get("rag_api_response"),
                    },
                },
            )
            _graph_log.debug(
                "retrieve_completed",
                extra={
                    "event": "retrieve_completed",
                    "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
                    "gateway_meta": {"evidence_len": len(evidence or "")},
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
            tool_msg = ToolMessage(
                content=evidence,
                tool_call_id=tid,
                name="query_knowledge_base",
            )
            return {"messages": [synthetic, tool_msg]}

    async def llm_call(state: AgentState, config: RunnableConfig):
        cfg = (config or {}).get("configurable") or {}
        invoke_kw = gateway_llm_invoke_kwargs(
            cfg.get("request_id"), cfg.get("session_id"), cfg.get("trace_id")
        )
        retry = state.get("retry_count", 0)
        llm_phase = "llm_call_retry" if retry > 0 else "llm_call"
        async with bind_pipeline_phase(llm_phase):
            t0 = time.perf_counter()
            attempt = retry + 1
            msgs_count = len(state.get("messages", []))
            llm_started_at = utc_now_iso()
            await emit_pipeline_state(
                config,
                phase=llm_phase,
                status="running",
                ui_message="Generating answer..." if attempt == 1 else "Regenerating answer...",
                started_at=llm_started_at,
                metadata={"attempt": attempt, "messages_count": msgs_count},
            )
            _graph_log.debug(
                "llm_call_started",
                extra={"event": "llm_call_started", "gateway_meta": {"messages_count": msgs_count}},
            )
            evidence = _tool_evidence_text(state["messages"])
            base_human = _build_answer_human_content(cfg, state, evidence)
            if retry == 0:
                llm_messages: List[Any] = [
                    SystemMessage(content=_ANSWER_SYSTEM),
                    HumanMessage(content=base_human),
                ]
            else:
                llm_messages = [
                    SystemMessage(content=_ANSWER_SYSTEM),
                    HumanMessage(content=base_human),
                ]
                prev = _last_real_ai_answer(state["messages"])
                fb = _judge_feedback_content(state["messages"])
                if prev:
                    llm_messages.append(AIMessage(content=prev))
                if fb:
                    llm_messages.append(HumanMessage(content=fb))
            result = await base_llm.ainvoke(llm_messages, config=config, **invoke_kw)
            _graph_log.debug(
                "llm_call_completed",
                extra={
                    "event": "llm_call_completed",
                    "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
                    "gateway_meta": {"response_len": len(extract_message_content(result) or "")},
                },
            )
            await emit_pipeline_state(
                config,
                phase=llm_phase,
                status="completed",
                ui_message="Answer generated",
                started_at=llm_started_at,
                ended_at=utc_now_iso(),
                latency_ms=(time.perf_counter() - t0) * 1000,
                metadata={
                    "attempt": attempt,
                    "messages_count": msgs_count,
                    "response_len": len(extract_message_content(result) or ""),
                },
            )
            return {"messages": [result]}

    g = StateGraph(AgentState)
    g.add_node("retrieve", retrieve_node)
    g.add_node("llm_call", llm_call)
    g.add_node("judge", judge_node)
    g.add_edge(START, "retrieve")
    g.add_edge("retrieve", "llm_call")
    g.add_edge("llm_call", "judge")
    g.add_conditional_edges("judge", _judge_continue, ["__end__", "llm_call"])
    compiled = g.compile()
    _agent_cache[cache_key] = compiled
    _graph_log.info(
        "agent_graph_compiled",
        extra={"event": "agent_graph_compiled", "gateway_meta": {"cache_key": str(cache_key)}},
    )
    return compiled
