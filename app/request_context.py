"""ASGI request correlation for JSON logs (same idea as layer-rag-query ``request_context``)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import AsyncIterator, Optional

_request_id: ContextVar[str] = ContextVar("request_id", default="-")
_session_id: ContextVar[str] = ContextVar("session_id", default="-")
_http_method: ContextVar[str] = ContextVar("http_method", default="-")
_http_path: ContextVar[str] = ContextVar("http_path", default="-")
_http_status: ContextVar[str] = ContextVar("http_status", default="-")
_pipeline_phase: ContextVar[str] = ContextVar("pipeline_phase", default="-")
_conversation_id: ContextVar[str] = ContextVar("conversation_id", default="-")
_is_new_conversation: ContextVar[str] = ContextVar("is_new_conversation", default="-")


def get_request_id() -> str:
    return _request_id.get()


def get_session_id() -> str:
    return _session_id.get()


def get_http_method() -> str:
    return _http_method.get()


def get_http_path() -> str:
    return _http_path.get()


def get_http_status() -> str:
    return _http_status.get()


def get_pipeline_phase() -> str:
    return _pipeline_phase.get()


def get_conversation_id() -> str:
    return _conversation_id.get()


def get_is_new_conversation_flag() -> str:
    """Returns ``true`` / ``false`` when bound; ``-`` when unknown."""
    return _is_new_conversation.get()


@asynccontextmanager
async def bind_conversation_logging_context(
    conversation_id: str, is_new_conversation: bool
) -> AsyncIterator[None]:
    """Bind effective thread id for JSON logs (async-safe; do not use sync ``contextmanager`` across ``await``)."""
    cid = (conversation_id or "").strip() or "-"
    flag = "true" if is_new_conversation else "false"
    t_cid = _conversation_id.set(cid)
    t_new = _is_new_conversation.set(flag)
    try:
        yield
    finally:
        _conversation_id.reset(t_cid)
        _is_new_conversation.reset(t_new)


@asynccontextmanager
async def bind_pipeline_phase(phase: str) -> AsyncIterator[None]:
    """Set active pipeline phase for JSON logs (nested contexts restore previous value)."""
    token = _pipeline_phase.set(phase or "-")
    try:
        yield
    finally:
        _pipeline_phase.reset(token)


@dataclass(frozen=True)
class _RequestContextTokens:
    rid: Token[str]
    sid: Token[str]
    method: Token[str]
    path: Token[str]
    status: Token[str]


def bind_request_context(
    *,
    request_id: str,
    session_id: Optional[str],
    method: str,
    path: str,
    status: str = "-",
) -> _RequestContextTokens:
    """Set context for the current task; caller must ``reset_request_context`` in ``finally``.

    Does **not** set ``pipeline_phase``: HTTP middleware ``finally`` runs before ``StreamingResponse``
    bodies finish, so resetting ``_pipeline_phase`` there would break nested ``bind_pipeline_phase``
    in the stream (ContextVar token / context mismatch).
    """
    rid = request_id.strip() or "-"
    sid_raw = (session_id or "").strip() or "-"
    return _RequestContextTokens(
        rid=_request_id.set(rid),
        sid=_session_id.set("-" if rid == "-" else sid_raw),
        method=_http_method.set(method or "-"),
        path=_http_path.set(path or "-"),
        status=_http_status.set(status or "-"),
    )


def reset_request_context(tokens: _RequestContextTokens) -> None:
    _request_id.reset(tokens.rid)
    _session_id.reset(tokens.sid)
    _http_method.reset(tokens.method)
    _http_path.reset(tokens.path)
    _http_status.reset(tokens.status)


def set_http_status(status: str) -> None:
    """Update response status in context (e.g. before logging completes)."""
    _http_status.set(status or "-")
