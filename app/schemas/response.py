"""Aggregated response helpers (non-stream JSON shape)."""

from typing import Optional

from ..observability.usage import build_usage_payload


def empty_answer_response(
    *,
    request_id: Optional[str],
    session_id: Optional[str],
    trace_id: Optional[str],
    conversation_id: str,
    is_new_conversation: bool,
) -> dict:
    return {
        "request_id": request_id,
        "session_id": session_id,
        "trace_id": trace_id,
        "conversation_id": conversation_id,
        "is_new_conversation": is_new_conversation,
        "route": None,
        "route_detail": None,
        "rewrite": None,
        "answer": None,
        "citations": [],
        "follow_up_questions": [],
        "usage": build_usage_payload(),
    }
