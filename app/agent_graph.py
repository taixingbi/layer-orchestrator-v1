"""Build LangGraph agents from MCP server configs (with caching)."""
import asyncio
import uuid
from typing import Any, Dict, List, Literal, Optional, Tuple

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.graph import StateGraph, START
from langgraph.graph.message import MessagesState
from langgraph.prebuilt import ToolNode

from .agent_answer_judge import evaluate_answer
from .config import gateway_llm_invoke_kwargs, get_llm, settings
from .rag_http_tool import query_rag_http
from .utils import extract_message_content, first_user_text, message_role

MAX_RETRIES = 1
_agent_cache: Dict[tuple, Any] = {}


class AgentState(MessagesState, total=False):
    retry_count: int
    judge_passed: bool


def _should_continue(state: AgentState) -> Literal["tool_node", "judge"]:
    last = state["messages"][-1]
    tool_calls = getattr(last, "tool_calls", None) or (last.get("tool_calls") if isinstance(last, dict) else None)
    return "tool_node" if tool_calls else "judge"


def _judge_continue(state: AgentState) -> Literal["__end__", "llm_call"]:
    return "__end__" if state.get("judge_passed") else "llm_call"


async def _inject_request_context(request, execute):
    """Inject request_id and session_id from config into MCP tool arguments (tools/call pattern)."""
    config = getattr(getattr(request, "runtime", None), "config", None) or {}
    configurable = config.get("configurable") or {}
    request_id = configurable.get("request_id")
    session_id = configurable.get("session_id")
    tool_call = request.tool_call
    args = dict(tool_call.get("args", {}) if isinstance(tool_call, dict) else getattr(tool_call, "args", {}))
    if request_id is not None:
        args["request_id"] = request_id
    if session_id is not None:
        args["session_id"] = session_id
    if isinstance(tool_call, dict):
        modified_call = {**tool_call, "args": args}
    else:
        modified_call = {
            "name": getattr(tool_call, "name", ""),
            "args": args,
            "id": getattr(tool_call, "id", ""),
            "type": getattr(tool_call, "type", "tool_call"),
        }
    return await execute(request.override(tool_call=modified_call))


async def build_graph_agent(
    servers: Optional[dict] = None,
    tools: Optional[list] = None,
    tools_timeout_s: float = 60.0,
    *,
    rag_http_deterministic: bool = False,
):
    """Build (or return cached) compiled LangGraph agent.

    Pass either ``servers`` (MCP HTTP transport) or pre-built ``tools`` (e.g. HTTP RAG).

    When ``rag_http_deterministic`` is True, RAG is fetched once via HTTP (no LLM tool
    calls). Use this for OpenAI-compatible gateways (e.g. vLLM) that do not expose
    ``tool_choice`` without ``--tool-call-parser``.
    """
    if rag_http_deterministic:
        if servers or tools:
            raise ValueError("rag_http_deterministic must not pass servers or tools")
        if not settings.rag_http_base_url:
            raise ValueError("RAG_HTTP_BASE_URL is required for rag_http_deterministic")
        url = ((settings.rag_http_base_url or "").rstrip("/") + "/v1/rag/query").lower()
        cache_key: Tuple[Any, ...] = ("rag_http_det", url, tools_timeout_s)
    else:
        if bool(servers) == bool(tools):
            raise ValueError("Pass exactly one of: servers (MCP config), tools (tool list)")
        if servers:
            url = next(iter(servers.values()))["url"].rstrip("/")
        else:
            url = ((settings.rag_http_base_url or "").rstrip("/") + "/v1/rag/query").lower()
        cache_key = (url, tools_timeout_s)
    if cache_key in _agent_cache:
        return _agent_cache[cache_key]

    async def judge_node(state: AgentState, config: RunnableConfig):
        messages = state["messages"]
        retry_count = state.get("retry_count", 0)
        if retry_count >= MAX_RETRIES:
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
        passed, feedback = await evaluate_answer(
            question,
            answer,
            evidence=evidence,
            request_id=cfg.get("request_id"),
            session_id=cfg.get("session_id"),
        )
        if passed or retry_count >= MAX_RETRIES:
            return {"judge_passed": True}
        return {
            "judge_passed": False,
            "messages": [HumanMessage(content=f"The previous answer was not good enough. Reason: {feedback} Please improve your answer.")],
            "retry_count": retry_count + 1,
        }

    if rag_http_deterministic:
        base_llm_det = get_llm(temperature=0)

        async def retrieve_node(state: AgentState, config: RunnableConfig):
            cfg = (config or {}).get("configurable") or {}
            question = first_user_text(state["messages"])
            evidence = await query_rag_http(
                question,
                str(cfg.get("request_id") or ""),
                str(cfg.get("session_id") or ""),
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
                cfg.get("request_id"), cfg.get("session_id")
            )
            result = await base_llm_det.ainvoke(state["messages"], config=config, **invoke_kw)
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
        return compiled

    if servers:
        client = MultiServerMCPClient(servers, tool_name_prefix=False)
        tools = await asyncio.wait_for(client.get_tools(), timeout=tools_timeout_s)
    if not tools:
        raise ValueError("no tools loaded")
    tool_node = ToolNode(tools, awrap_tool_call=_inject_request_context)
    base_llm_mcp = get_llm(temperature=0)

    async def llm_call(state: AgentState, config: RunnableConfig):
        cfg = (config or {}).get("configurable") or {}
        invoke_kw = gateway_llm_invoke_kwargs(
            cfg.get("request_id"), cfg.get("session_id")
        )
        # OpenAI-compatible stacks (e.g. vLLM) reject tool_choice "auto" unless the
        # server enables it. Omitting tool_choice implies "auto", so we use "required"
        # only when tools may be called, and a plain model after tool results.
        messages = state["messages"]
        last = messages[-1]
        if isinstance(last, ToolMessage):
            model = base_llm_mcp
        else:
            model = base_llm_mcp.bind_tools(tools, tool_choice="required")
        result = await model.ainvoke(messages, config=config, **invoke_kw)
        return {"messages": [result]}

    g = StateGraph(AgentState)
    g.add_node("llm_call", llm_call)
    g.add_node("tool_node", tool_node)
    g.add_node("judge", judge_node)
    g.add_edge(START, "llm_call")
    g.add_conditional_edges("llm_call", _should_continue, ["tool_node", "judge"])
    g.add_edge("tool_node", "llm_call")
    g.add_conditional_edges("judge", _judge_continue, ["__end__", "llm_call"])
    compiled = g.compile()
    _agent_cache[cache_key] = compiled
    return compiled