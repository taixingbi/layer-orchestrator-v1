"""Shared SSE `state` event shape for orchestrator and LangGraph nodes."""

from datetime import datetime, timezone
from typing import Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def state_event(
    *,
    phase: str,
    status: str,
    ui_message: str,
    started_at: Optional[str] = None,
    ended_at: Optional[str] = None,
    latency_ms: Optional[float] = None,
    metadata: Optional[dict] = None,
) -> dict:
    event = {
        "type": "state",
        "phase": phase,
        "status": status,
        "ui_message": ui_message,
        "message": ui_message,
    }
    if started_at is not None:
        event["started_at"] = started_at
    if ended_at is not None:
        event["ended_at"] = ended_at
    if latency_ms is not None:
        event["latency_ms"] = round(latency_ms, 2)
    if metadata:
        event["metadata"] = metadata
    return event
