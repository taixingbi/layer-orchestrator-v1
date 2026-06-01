"""Correlation id helpers for HTTP ingress, logging, and outbound headers."""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional


def new_session_id() -> str:
    """Gateway-aligned session id when the client omits ``X-Session-Id`` (``sess_<hex>``)."""
    return f"sess_{uuid.uuid4().hex[:12]}"


def trace_id_log_fields(
    *,
    request_id: str,
    trace_id: Optional[str],
    trace_id_from_header: bool,
) -> Dict[str, Any]:
    """Log ``trace_id`` plus ``trace_id_source`` (header vs defaulted to request_id)."""
    tid = (trace_id or request_id or "-").strip() or "-"
    return {
        "trace_id": tid,
        "trace_id_source": "header" if trace_id_from_header else "request_id",
    }
