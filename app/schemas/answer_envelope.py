"""Client response envelope: meta + answer + follow_up_questions + latency_ms + usage + status."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from .route import InternalIntentRoute, RouteDetail, ToolRoute

# Latency / usage phase keys (underscore; aligned with schema-request-response.md).
LATENCY_KEY_RAG = "tool_rag"
LATENCY_KEY_GITHUB_SEARCH = "tool_github_search"
LATENCY_KEY_TAVILY_SEARCH = "tool_tavily_search"

USAGE_KEY_RAG = LATENCY_KEY_RAG
USAGE_KEY_GITHUB_SEARCH = LATENCY_KEY_GITHUB_SEARCH
USAGE_KEY_TAVILY_SEARCH = LATENCY_KEY_TAVILY_SEARCH

_MCP_TOOL_NAME = {
    "user_profile": "rag_query",
    "github_repo_search": "ask_repo",
    "web_search": "web_search",
}

_TOOL_TYPE = {
    "user_profile": "rag",
    "github_repo_search": "github",
    "web_search": "web",
}


def _user_block(rag_user: Optional[Dict[str, str]]) -> Dict[str, str]:
    u = rag_user or {}
    return {
        "id": str(u.get("user_id") or ""),
        "roles": str(u.get("user_roles") or ""),
        "groups": str(u.get("user_groups") or ""),
        "teams": str(u.get("user_teams") or ""),
    }


def route_meta_from_detail(detail: Any) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Build meta.route and meta.tool from route_detail."""
    if isinstance(detail, ToolRoute):
        mcp_name = _MCP_TOOL_NAME.get(detail.name, detail.name)
        tool_type = _TOOL_TYPE.get(detail.name, "tool")
        route = {
            "type": "tool",
            "tool": mcp_name,
            "confidence": float(detail.confidence),
        }
        if detail.reason:
            route["reason"] = detail.reason
        tool = {"name": mcp_name, "type": tool_type, "version": "v1"}
        if detail.repo:
            tool["repo"] = detail.repo
        return route, tool
    if isinstance(detail, InternalIntentRoute):
        route = {
            "type": "internal_intent",
            "tool": detail.name,
            "confidence": float(detail.confidence),
        }
        if detail.reason:
            route["reason"] = detail.reason
        tool = {"name": detail.name, "type": "internal_intent", "version": "v1"}
        return route, tool
    if isinstance(detail, dict):
        t = detail.get("type")
        name = str(detail.get("name") or "")
        if t == "tool":
            fake = ToolRoute.model_validate({**detail, "type": "tool"})
            return route_meta_from_detail(fake)
        if t == "internal_intent":
            fake = InternalIntentRoute.model_validate({**detail, "type": "internal_intent"})
            return route_meta_from_detail(fake)
    return {"type": "unknown", "tool": "", "confidence": 0.0}, {"name": "", "type": "unknown", "version": "v1"}


def build_meta(
    *,
    request_id: Optional[str],
    session_id: Optional[str],
    trace_id: Optional[str],
    conversation_id: str,
    is_new_conversation: bool,
    route_detail: Any,
    rewrite: Optional[str],
    rag_user: Optional[Dict[str, str]] = None,
    extra_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    route, tool = route_meta_from_detail(route_detail)
    meta: Dict[str, Any] = {
        "request_id": request_id,
        "session_id": session_id,
        "trace_id": trace_id,
        "conversation_id": conversation_id,
        "is_new_conversation": is_new_conversation,
        "user": _user_block(rag_user),
        "route": route,
        "tool": tool,
    }
    if rewrite is not None and str(rewrite).strip():
        meta["rewrite"] = rewrite
    if extra_meta:
        meta.update(extra_meta)
    return meta


def build_answer_block(
    text: Optional[str],
    citations: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    return {
        "text": text if text is not None else "",
        "citations": list(citations) if citations else [],
    }


def build_status(*, ok: bool, state: Optional[str] = None) -> Dict[str, Any]:
    if state is None:
        state = "completed" if ok else "failed"
    return {"ok": ok, "state": state}


def build_answer_envelope(
    *,
    request_id: Optional[str],
    session_id: Optional[str],
    trace_id: Optional[str],
    conversation_id: str,
    is_new_conversation: bool,
    route_detail: Any,
    rewrite: Optional[str],
    answer_text: Optional[str],
    citations: Optional[List[Any]] = None,
    follow_up_questions: Optional[List[Any]] = None,
    latency_ms: Optional[Dict[str, Any]] = None,
    usage: Optional[Dict[str, Any]] = None,
    rag_user: Optional[Dict[str, str]] = None,
    ok: bool = True,
    state: Optional[str] = None,
    error: Optional[str] = None,
    extra_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Full `/orchestrator/answer` body (non-stream and stream terminal events)."""
    out: Dict[str, Any] = {
        "meta": build_meta(
            request_id=request_id,
            session_id=session_id,
            trace_id=trace_id,
            conversation_id=conversation_id,
            is_new_conversation=is_new_conversation,
            route_detail=route_detail,
            rewrite=rewrite,
            rag_user=rag_user,
            extra_meta=extra_meta,
        ),
        "answer": build_answer_block(answer_text, citations),
        "follow_up_questions": list(follow_up_questions) if follow_up_questions else [],
        "latency_ms": latency_ms if isinstance(latency_ms, dict) else {},
        "usage": usage if isinstance(usage, dict) else {},
        "status": build_status(ok=ok, state=state),
    }
    if error:
        out["error"] = error
    return out


def latency_key_for_tool(orchestrator_tool_name: str) -> Optional[str]:
    if orchestrator_tool_name == "user_profile":
        return LATENCY_KEY_RAG
    if orchestrator_tool_name == "github_repo_search":
        return LATENCY_KEY_GITHUB_SEARCH
    if orchestrator_tool_name == "web_search":
        return LATENCY_KEY_TAVILY_SEARCH
    return None


def normalize_latency_ms_keys(latency_ms: Dict[str, Any]) -> Dict[str, Any]:
    """Map legacy hyphen keys to underscore envelope keys."""
    if not latency_ms:
        return {}
    out = dict(latency_ms)
    for old, new in (
        ("tool-rag", LATENCY_KEY_RAG),
        ("tool-github-search", LATENCY_KEY_GITHUB_SEARCH),
        ("tool-tavily-search", LATENCY_KEY_TAVILY_SEARCH),
    ):
        if old in out and new not in out:
            out[new] = out.pop(old)
    return out


def normalize_usage_keys(usage: Dict[str, Any]) -> Dict[str, Any]:
    if not usage:
        return {}
    out = dict(usage)
    for old, new in (
        ("tool-rag", USAGE_KEY_RAG),
        ("tool-github-search", USAGE_KEY_GITHUB_SEARCH),
        ("tool-tavily-search", USAGE_KEY_TAVILY_SEARCH),
    ):
        if old in out and new not in out:
            out[new] = out.pop(old)
    # Drop flat token fields at usage root (envelope uses usage.total only).
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        out.pop(key, None)
    return out
