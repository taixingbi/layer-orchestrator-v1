"""Stderr JSON logging for Alloy/Loki collection."""

from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .request_context import (
    get_conversation_id,
    get_http_method,
    get_http_path,
    get_http_status,
    get_pipeline_phase,
    get_request_id,
    get_session_id,
)

logger = logging.getLogger("layer_orchestrator")


def _log_tz() -> ZoneInfo:
    raw = (os.environ.get("LOG_TIMEZONE") or "America/New_York").strip()
    if raw.upper() in ("EST", "EDT") or raw == "US/Eastern":
        raw = "America/New_York"
    try:
        return ZoneInfo(raw)
    except ZoneInfoNotFoundError:
        return ZoneInfo("America/New_York")


_LOG_TZ = _log_tz()

# Merged onto JSON when present on the LogRecord (from logger.*(..., extra={...})).
_EXTRA_JSON_FIELDS = (
    "duration_ms",
    "latency_ms",
    "latency_total_ms",
    "backend",
    "gpu",
    "reason",
    "upstream_status",
    "error_type",
    "error_message",
    "missing",
    "status_code",
    "gateway_meta",
    "structured_error",
)


class _RequestContextFilter(logging.Filter):
    """Attach request/session IDs and HTTP method/path/status from context onto each LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:
        rid = get_request_id()
        sid = get_session_id()
        record.request_id = "-" if rid == "-" else rid
        record.session_id = "-" if rid == "-" else sid
        record.method = get_http_method()
        record.path = get_http_path()
        ctx_status = get_http_status()
        if ctx_status != "-":
            record.status = ctx_status
        elif not hasattr(record, "status"):
            record.status = "-"
        if not hasattr(record, "phase"):
            record.phase = get_pipeline_phase()
        # Prefer explicit record.conversation_id (e.g. from http_request_complete + request.state).
        existing = getattr(record, "conversation_id", None)
        if not (isinstance(existing, str) and existing.strip() and existing != "-"):
            record.conversation_id = get_conversation_id()
        return True


class _JsonFormatter(logging.Formatter):
    """One JSON object per line for stderr."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=_LOG_TZ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "phase": getattr(record, "phase", get_pipeline_phase()),
        }
        if hasattr(record, "event"):
            payload["event"] = getattr(record, "event")
        payload["message"] = record.getMessage()
        payload.update(
            {
                "request_id": getattr(record, "request_id", "-"),
                "trace_id": getattr(record, "trace_id", "-"),
                "session_id": getattr(record, "session_id", "-"),
                "conversation_id": getattr(record, "conversation_id", "-"),
                "method": getattr(record, "method", "-"),
                "path": getattr(record, "path", "-"),
                "status": getattr(record, "status", "-"),
            }
        )
        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)
        for key in _EXTRA_JSON_FIELDS:
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        return json.dumps(payload, ensure_ascii=False, default=str)


_JSON_FORMATTER = _JsonFormatter()

_setup_done = False


def _resolve_log_level() -> int:
    name = (os.environ.get("LOG_LEVEL") or "INFO").upper()
    return getattr(logging, name, logging.INFO)


def setup_logging() -> None:
    """Configure ``layer_orchestrator`` logger with JSON logs to stderr."""
    global _setup_done
    if _setup_done:
        return
    _setup_done = True

    level = _resolve_log_level()
    logger.setLevel(level)
    logger.handlers.clear()
    logger.filters.clear()
    logger.propagate = False

    # Filters on handlers so child loggers (e.g. layer_orchestrator.http) still get context fields.
    _ctx_filter = _RequestContextFilter()
    stderr_h = logging.StreamHandler(sys.stderr)
    stderr_h.setLevel(level)
    stderr_h.setFormatter(_JSON_FORMATTER)
    stderr_h.addFilter(_ctx_filter)
    logger.addHandler(stderr_h)

    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    logger.info("structured stderr logging enabled (collector: Alloy)")


def shutdown_logging() -> None:
    """Flush handlers and mark logging as not configured."""
    global _setup_done
    for h in logger.handlers:
        if isinstance(h, logging.StreamHandler):
            h.flush()
    _setup_done = False


def new_request_id() -> str:
    """UUID for ``x-request-id`` when the client does not send one."""
    return str(uuid.uuid4())
