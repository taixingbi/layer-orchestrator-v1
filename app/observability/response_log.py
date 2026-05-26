"""Build gateway_meta for final_response_emitted (client envelope + routing debug)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..schemas.answer_envelope import (
    build_answer_envelope,
    normalize_latency_ms_keys,
    normalize_usage_keys,
)


def build_routing_meta(
    *,
    route_initial: str,
    route_initial_detail: Optional[Dict[str, Any]],
    route_final: str,
    route_final_detail: Optional[Dict[str, Any]],
    route_source: str,
    answer_source: str,
    is_new_conversation: bool,
) -> Dict[str, Any]:
    initial_detail = route_initial_detail or {}
    final_detail = route_final_detail or {}
    return {
        "route_initial": route_initial,
        "route_initial_detail": initial_detail,
        "route_final": route_final,
        "route_final_detail": final_detail,
        "route_source": route_source,
        "override_applied": route_initial != route_final or initial_detail != final_detail,
        "answer_source": answer_source,
        "is_new_conversation": bool(is_new_conversation),
    }


def build_final_response_log(
    *,
    request_id: Optional[str],
    session_id: Optional[str],
    trace_id: Optional[str],
    conversation_id: str,
    is_new_conversation: bool,
    route_detail: Any,
    route_source: str,
    rewrite_text: Optional[str],
    answer_text: Optional[str],
    citations: Optional[List[Any]] = None,
    follow_up_questions: Optional[List[Any]] = None,
    usage: Optional[Dict[str, Any]] = None,
    phase_states: Optional[List[dict]] = None,
    rag_user: Optional[Dict[str, str]] = None,
    route_initial: str,
    route_initial_detail: Optional[Dict[str, Any]],
    route_final: str,
    route_final_detail: Optional[Dict[str, Any]],
    answer_source: str,
    ok: bool = True,
    error: Optional[str] = None,
    state: Optional[str] = None,
    code: Optional[str] = None,
) -> Dict[str, Any]:
    """Same envelope as POST /v1/orchestrator/answer JSON / SSE done, plus routing debug."""
    from ..core.sse import build_latency_ms_summary

    states = list(phase_states or [])
    latency_ms = normalize_latency_ms_keys(build_latency_ms_summary(states))
    usage_payload = normalize_usage_keys(usage if isinstance(usage, dict) else {})

    envelope = build_answer_envelope(
        request_id=request_id,
        session_id=session_id,
        trace_id=trace_id,
        conversation_id=conversation_id,
        is_new_conversation=is_new_conversation,
        route_detail=route_detail,
        rewrite=rewrite_text,
        route_source=route_source,  # type: ignore[arg-type]
        answer_text=answer_text,
        citations=citations,
        follow_up_questions=follow_up_questions,
        latency_ms=latency_ms,
        usage=usage_payload,
        rag_user=rag_user,
        ok=ok,
        state=state,
        code=code,
        error=error,
    )
    routing = build_routing_meta(
        route_initial=route_initial,
        route_initial_detail=route_initial_detail,
        route_final=route_final,
        route_final_detail=route_final_detail,
        route_source=route_source,
        answer_source=answer_source,
        is_new_conversation=is_new_conversation,
    )
    return {"routing": routing, "response": envelope}
