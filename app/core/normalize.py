"""Request normalization and validation helpers."""

from __future__ import annotations

import uuid
from typing import Dict, Optional, Tuple

from fastapi import HTTPException

from ..config import settings
from ..schemas.request import AnswerBody, EvalRouterBody


def max_request_body_bytes() -> int:
    return max(1, int(settings.max_request_body_mb * 1024 * 1024))


def request_timeout_s() -> float:
    return settings.request_timeout_ms / 1000.0


def stream_idle_timeout_s() -> float:
    return settings.stream_idle_timeout_ms / 1000.0


def resolve_effective_conversation_id(raw: Optional[str]) -> Tuple[str, bool]:
    """Return (conversation_id, is_new). Blank/missing → new ``conv_<uuidhex>``."""
    cid = (raw or "").strip()
    if cid:
        return cid, False
    return f"conv_{uuid.uuid4().hex}", True


def validate_answer_body_limits(body: AnswerBody, raw_size_bytes: int, *, conversation_id: str) -> None:
    if raw_size_bytes > max_request_body_bytes():
        raise HTTPException(
            status_code=413,
            detail=(
                f"request body too large: {raw_size_bytes} bytes > "
                f"{max_request_body_bytes()} bytes (MAX_REQUEST_BODY_MB={settings.max_request_body_mb})"
            ),
        )
    q_len = len((body.question or ""))
    if q_len > settings.max_question_chars:
        raise HTTPException(
            status_code=400,
            detail=(
                f"question too long: {q_len} chars > "
                f"{settings.max_question_chars} (MAX_QUESTION_CHARS)"
            ),
        )
    hist_len = len(body.history or [])
    if hist_len > settings.max_history_messages:
        raise HTTPException(
            status_code=400,
            detail=(
                f"history too long: {hist_len} messages > "
                f"{settings.max_history_messages} (MAX_HISTORY_MESSAGES)"
            ),
        )
    conv_len = len(conversation_id)
    context_chars = q_len + sum(len(t.content or "") for t in (body.history or [])) + conv_len
    if context_chars > settings.max_context_chars:
        raise HTTPException(
            status_code=400,
            detail=(
                f"context too large: {context_chars} chars > "
                f"{settings.max_context_chars} (MAX_CONTEXT_CHARS)"
            ),
        )


def validate_eval_router_body_limits(body: EvalRouterBody, *, conversation_id: str) -> None:
    q_len = len(body.question or "")
    if q_len > settings.max_question_chars:
        raise HTTPException(
            status_code=400,
            detail=(
                f"question too long: {q_len} chars > "
                f"{settings.max_question_chars} (MAX_QUESTION_CHARS)"
            ),
        )
    hist_len = len(body.history or [])
    if hist_len > settings.max_history_messages:
        raise HTTPException(
            status_code=400,
            detail=(
                f"history too long: {hist_len} messages > "
                f"{settings.max_history_messages} (MAX_HISTORY_MESSAGES)"
            ),
        )
    override = body.router_prompt_override or ""
    ov_len = len(override)
    if ov_len > settings.max_context_chars:
        raise HTTPException(
            status_code=400,
            detail=(
                f"router_prompt_override too long: {ov_len} chars > "
                f"{settings.max_context_chars} (MAX_CONTEXT_CHARS)"
            ),
        )
    conv_len = len(conversation_id)
    context_chars = q_len + sum(len(t.content or "") for t in (body.history or [])) + ov_len + conv_len
    if context_chars > settings.max_context_chars:
        raise HTTPException(
            status_code=400,
            detail=(
                f"context too large: {context_chars} chars > "
                f"{settings.max_context_chars} (MAX_CONTEXT_CHARS)"
            ),
        )


def reject_body_correlation_fields(raw_body: object) -> None:
    if not isinstance(raw_body, dict):
        return
    correlation_keys = [key for key in ("session_id", "request_id", "trace_id") if key in raw_body]
    if correlation_keys:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{', '.join(correlation_keys)} must be sent in headers only: "
                "X-Session-Id, X-Request-Id, X-Trace-Id"
            ),
        )
    user_keys = [key for key in ("user_id", "user_roles", "user_groups", "user_teams") if key in raw_body]
    if user_keys:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{', '.join(user_keys)} must be sent in headers only: "
                "X-User-Id, X-User-Roles, X-User-Groups, X-User-Teams"
            ),
        )


def header_rag_user(request) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for key in ("user_id", "user_roles", "user_groups", "user_teams"):
        v = getattr(request.state, key, None)
        if isinstance(v, str) and v.strip():
            out[key] = v.strip()
    return out


def header_ids(request) -> tuple[Optional[str], Optional[str], Optional[str]]:
    return (
        getattr(request.state, "session_id", None),
        getattr(request.state, "request_id", None),
        getattr(request.state, "trace_id", None),
    )


def trace_id_from_header(request) -> bool:
    """True when the client sent a non-empty ``X-Trace-Id`` (vs middleware default)."""
    return bool(getattr(request.state, "trace_id_from_header", False))
