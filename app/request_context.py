"""ASGI request correlation for JSON logs (same idea as layer-rag-query ``request_context``)."""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Optional

_request_id: ContextVar[str] = ContextVar("request_id", default="-")
_session_id: ContextVar[str] = ContextVar("session_id", default="-")
_http_method: ContextVar[str] = ContextVar("http_method", default="-")
_http_path: ContextVar[str] = ContextVar("http_path", default="-")
_http_status: ContextVar[str] = ContextVar("http_status", default="-")


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
    """Set context for the current task; caller must ``reset_request_context`` in ``finally``."""
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
