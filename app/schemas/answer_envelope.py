"""Client response envelope: meta + answer + follow_up_questions + latency_ms + usage + status."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union

from .route import InternalIntentRoute, RouteDetail, ToolRoute

RouteSource = Literal[
    "deterministic_rule",
    "llm_router",
    "smalltalk_seed",
    "smalltalk_pattern",
    "injection_guard",
    "override_rule",
]

_PROMPT_SOURCE_TO_ROUTE_SOURCE: Dict[str, RouteSource] = {
    "injection_guard": "injection_guard",
    "smalltalk_seed": "smalltalk_seed",
    "smalltalk_pattern": "smalltalk_pattern",
    "versioned_file": "llm_router",
    "body_override": "llm_router",
}

_OVERRIDE_REASON_MARKERS = (
    "[server: github_repo_keyword",
    "[server: kb_grounded",
    "[server: general_immigration",
    "[server: empty direct_reply",
)

# Latency / usage phase keys (underscore; aligned with schema-request-response.md).
LATENCY_KEY_RAG = "tool_rag"
LATENCY_KEY_GITHUB_SEARCH = "tool_github_search"
LATENCY_KEY_TAVILY_SEARCH = "tool_tavily_search"

USAGE_KEY_RAG = LATENCY_KEY_RAG
USAGE_KEY_GITHUB_SEARCH = LATENCY_KEY_GITHUB_SEARCH
USAGE_KEY_TAVILY_SEARCH = LATENCY_KEY_TAVILY_SEARCH

# Orchestrator tool id (route_detail.name) → client latency_ms / usage key.
TOOL_LATENCY_USAGE_KEYS: Dict[str, str] = {
    "rag_private_kb": LATENCY_KEY_RAG,
    "github_search": LATENCY_KEY_GITHUB_SEARCH,
    "web_search": LATENCY_KEY_TAVILY_SEARCH,
}

_TOOL_TYPE = {
    "rag_private_kb": "rag_private_kb",
    "github_search": "github",
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


def route_source_from_prompt_source(prompt_source: Optional[str]) -> RouteSource:
    key = (prompt_source or "").strip()
    return _PROMPT_SOURCE_TO_ROUTE_SOURCE.get(key, "llm_router")


def route_source_after_normalize(
    *,
    pre_deterministic: bool,
    prompt_source: Optional[str],
    reason: str,
) -> RouteSource:
    """Resolve client meta.route.source from how routing was decided."""
    if pre_deterministic:
        return "deterministic_rule"
    r = reason or ""
    if any(marker in r for marker in _OVERRIDE_REASON_MARKERS):
        return "override_rule"
    return route_source_from_prompt_source(prompt_source)


def route_meta_from_detail(
    detail: Any,
    *,
    source: Optional[RouteSource] = None,
) -> tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """Build meta.route and optional meta.tool (tools only) from route_detail."""
    if isinstance(detail, ToolRoute):
        orch_name = detail.name
        phase_key = TOOL_LATENCY_USAGE_KEYS.get(orch_name, orch_name)
        tool_type = _TOOL_TYPE.get(orch_name, "tool")
        route: Dict[str, Any] = {
            "type": "tool",
            "tool": orch_name,
            "confidence": float(detail.confidence),
        }
        if detail.reason:
            route["reason"] = detail.reason
        if source:
            route["source"] = source
        tool: Dict[str, Any] = {"name": orch_name, "type": tool_type, "version": "v1", "key": phase_key}
        if detail.repo and orch_name != "github_search":
            tool["repo"] = detail.repo
        return route, tool
    if isinstance(detail, InternalIntentRoute):
        route = {
            "type": "internal_intent",
            "intent": detail.name,
            "confidence": float(detail.confidence),
        }
        if detail.reason:
            route["reason"] = detail.reason
        if source:
            route["source"] = source
        return route, None
    if isinstance(detail, dict):
        t = detail.get("type")
        if t == "tool":
            fake = ToolRoute.model_validate({**detail, "type": "tool"})
            return route_meta_from_detail(fake, source=source)
        if t == "internal_intent":
            fake = InternalIntentRoute.model_validate({**detail, "type": "internal_intent"})
            return route_meta_from_detail(fake, source=source)
    route = {"type": "unknown", "confidence": 0.0}
    if source:
        route["source"] = source
    return route, None


def build_meta(
    *,
    request_id: Optional[str],
    session_id: Optional[str],
    trace_id: Optional[str],
    conversation_id: str,
    is_new_conversation: bool,
    route_detail: Any,
    rewrite: Optional[str],
    route_source: Optional[RouteSource] = None,
    rag_user: Optional[Dict[str, str]] = None,
    extra_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    route, tool = route_meta_from_detail(route_detail, source=route_source)
    meta: Dict[str, Any] = {
        "request_id": request_id,
        "session_id": session_id,
        "trace_id": trace_id,
        "conversation_id": conversation_id,
        "is_new_conversation": is_new_conversation,
        "user": _user_block(rag_user),
        "route": route,
    }
    if tool is not None:
        meta["tool"] = tool
    if rewrite is not None and str(rewrite).strip():
        meta["rewrite"] = rewrite
    if extra_meta:
        meta.update(extra_meta)
    return meta


def build_answer_block(
    text: Optional[str],
    citations: Optional[List[Any]] = None,
    *,
    blocks: Optional[List[Any]] = None,
    notes: Optional[List[Any]] = None,
    answer_format: Optional[str] = None,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "text": text if text is not None else "",
        "citations": list(citations) if citations else [],
    }
    if blocks:
        out["blocks"] = list(blocks)
    if notes:
        out["notes"] = list(notes)
    if answer_format:
        out["format"] = answer_format
    return out


def status_code_for_exception(exc: BaseException) -> str:
    """Map exceptions to client status.code values."""
    if isinstance(exc, (TimeoutError,)):
        return "tool_timeout"
    name = type(exc).__name__.lower()
    if "timeout" in name:
        return "tool_timeout"
    return "error"


def build_status(
    *,
    ok: bool,
    state: Optional[str] = None,
    code: Optional[str] = None,
) -> Dict[str, Any]:
    if state is None:
        state = "completed" if ok else "failed"
    if code is None:
        code = "ok" if ok else "error"
    return {"ok": ok, "state": state, "code": code}


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
    answer_blocks: Optional[List[Any]] = None,
    answer_notes: Optional[List[Any]] = None,
    answer_format: Optional[str] = None,
    follow_up_questions: Optional[List[Any]] = None,
    latency_ms: Optional[Dict[str, Any]] = None,
    usage: Optional[Dict[str, Any]] = None,
    rag_user: Optional[Dict[str, str]] = None,
    ok: bool = True,
    state: Optional[str] = None,
    code: Optional[str] = None,
    route_source: Optional[RouteSource] = None,
    error: Optional[str] = None,
    extra_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Full `/v1/orchestrator/answer` body (non-stream and stream terminal events)."""
    out: Dict[str, Any] = {
        "meta": build_meta(
            request_id=request_id,
            session_id=session_id,
            trace_id=trace_id,
            conversation_id=conversation_id,
            is_new_conversation=is_new_conversation,
            route_detail=route_detail,
            rewrite=rewrite,
            route_source=route_source,
            rag_user=rag_user,
            extra_meta=extra_meta,
        ),
        "answer": build_answer_block(
            answer_text,
            citations,
            blocks=answer_blocks,
            notes=answer_notes,
            answer_format=answer_format,
        ),
        "follow_up_questions": list(follow_up_questions) if follow_up_questions else [],
        "latency_ms": latency_ms if isinstance(latency_ms, dict) else {},
        "usage": usage if isinstance(usage, dict) else {},
        "status": build_status(ok=ok, state=state, code=code),
    }
    if error:
        out["error"] = error
    return out


def latency_key_for_tool(orchestrator_tool_name: str) -> Optional[str]:
    return TOOL_LATENCY_USAGE_KEYS.get(orchestrator_tool_name)


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
