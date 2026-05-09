"""Build the FastAPI-only LangGraph agent (HTTP RAG + judge loop)."""
import logging
import time
import uuid
from typing import Any, Dict, List, Literal, Optional, Tuple

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START
from langgraph.graph.message import MessagesState

from .agent_answer_judge import evaluate_answer
from .config import gateway_llm_invoke_kwargs, get_llm, settings
from .pipeline_state import utc_now_iso
from .rag_http_tool import query_rag_http_with_meta
from .request_context import bind_pipeline_phase
from .utils import extract_message_content, first_user_text, message_role

MAX_RETRIES = 1
_agent_cache: Dict[tuple, Any] = {}
_graph_log = logging.getLogger("layer_orchestrator.agent_graph")


class AgentState(MessagesState, total=False):
    retry_count: int
    judge_passed: bool


def _judge_continue(state: AgentState) -> Literal["__end__", "llm_call"]:
    return "__end__" if state.get("judge_passed") else "llm_call"


async def _emit_state(config: Optional[RunnableConfig], **kwargs: Any) -> None:
    fn = ((config or {}).get("configurable") or {}).get("emit_state")
    if callable(fn):
        await fn(**kwargs)


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

    async def judge_node(state: AgentState, config: RunnableConfig):
        messages = state["messages"]
        retry_count = state.get("retry_count", 0)
        phase_name = "judge_retry" if retry_count > 0 else "judge"
        async with bind_pipeline_phase(phase_name):
            _graph_log.debug("judge_started", extra={"event": "judge_started"})
            if retry_count >= MAX_RETRIES:
                _graph_log.debug(
                    "judge_skipped_max_retries",
                    extra={"event": "judge_skipped_max_retries", "gateway_meta": {"retry_count": retry_count}},
                )
                skipped_ts = utc_now_iso()
                await _emit_state(
                    config,
                    phase=phase_name,
                    status="skipped",
                    ui_message="Judge skipped (max retries reached)",
                    started_at=skipped_ts,
                    ended_at=skipped_ts,
                    metadata={"retry_count": retry_count},
                )
                return {"judge_passed": True}
            question = ""
            answer = ""
            tool_contents: List[str] = []
            for m in messages:
                role = message_role(m)
                if role in ("human", "user") and not question:
                    question = extract_message_content(m)
                elif role == "ai":
                    answer = extract_message_content(m)
                elif role == "tool":
                    tool_contents.append(extract_message_content(m))
            evidence = "\n".join(f"[E{i+1}] {c}" for i, c in enumerate(tool_contents) if c) or None
            cfg = (config or {}).get("configurable") or {}
            judge_started_at = utc_now_iso()
            t_judge = time.perf_counter()
            await _emit_state(
                config,
                phase=phase_name,
                status="running",
                ui_message="Evaluating answer quality...",
                started_at=judge_started_at,
                metadata={"retry_count": retry_count},
            )
            passed, feedback = await evaluate_answer(
                question,
                answer,
                evidence=evidence,
                request_id=cfg.get("request_id"),
                session_id=cfg.get("session_id"),
                trace_id=cfg.get("trace_id"),
            )
            will_retry = not passed and retry_count < MAX_RETRIES
            _graph_log.debug(
                "judge_evaluated",
                extra={
                    "event": "judge_evaluated",
                    "gateway_meta": {
                        "retry_count": retry_count,
                        "passed": passed,
                        "feedback_preview": (feedback or "")[:120] or None,
                    },
                },
            )
            await _emit_state(
                config,
                phase=phase_name,
                status="completed",
                ui_message="Judge completed",
                started_at=judge_started_at,
                ended_at=utc_now_iso(),
                latency_ms=(time.perf_counter() - t_judge) * 1000,
                metadata={
                    "retry_count": retry_count,
                    "passed": passed,
                    "feedback_preview": (feedback or "")[:120] or None,
                    "will_retry": will_retry,
                },
            )
            if passed or retry_count >= MAX_RETRIES:
                return {"judge_passed": True}
            return {
                "judge_passed": False,
                "messages": [HumanMessage(content=f"The previous answer was not good enough. Reason: {feedback} Please improve your answer.")],
                "retry_count": retry_count + 1,
            }

    base_llm = get_llm(temperature=0)

    async def retrieve_node(state: AgentState, config: RunnableConfig):
        async with bind_pipeline_phase("rag_query"):
            t0 = time.perf_counter()
            cfg = (config or {}).get("configurable") or {}
            question = first_user_text(state["messages"])
            rag_started_at = utc_now_iso()
            await _emit_state(
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
            await _emit_state(
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
            await _emit_state(
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
            result = await base_llm.ainvoke(state["messages"], config=config, **invoke_kw)
            _graph_log.debug(
                "llm_call_completed",
                extra={
                    "event": "llm_call_completed",
                    "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
                    "gateway_meta": {"response_len": len(extract_message_content(result) or "")},
                },
            )
            await _emit_state(
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