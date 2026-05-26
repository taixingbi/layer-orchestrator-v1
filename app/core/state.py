"""Shared SSE `state` event shape for orchestrator and LangGraph nodes."""

from datetime import datetime, timezone
from typing import Dict, List, Optional

_TERMINAL_STATE_STATUSES = frozenset({"completed", "failed", "skipped"})


def state_slice_from_event(event: dict) -> dict:
    return {
        "phase": event.get("phase"),
        "status": event.get("status"),
        "ui_message": event.get("ui_message") or event.get("message"),
        "started_at": event.get("started_at"),
        "ended_at": event.get("ended_at"),
        "latency_ms": event.get("latency_ms"),
        "metadata": dict(event.get("metadata") or {}),
    }


def merge_phase_states(existing: dict, incoming: dict) -> dict:
    out = dict(existing)
    ex_st = out.get("status")
    in_st = incoming.get("status")
    out["metadata"] = {**(out.get("metadata") or {}), **(incoming.get("metadata") or {})}
    if ex_st in _TERMINAL_STATE_STATUSES:
        if out.get("started_at") is None and incoming.get("started_at"):
            out["started_at"] = incoming["started_at"]
        return out
    if in_st in _TERMINAL_STATE_STATUSES:
        out["status"] = in_st
        out["ui_message"] = incoming.get("ui_message") or out.get("ui_message")
        if incoming.get("ended_at") is not None:
            out["ended_at"] = incoming["ended_at"]
        if incoming.get("latency_ms") is not None:
            out["latency_ms"] = incoming["latency_ms"]
        out["started_at"] = incoming.get("started_at") or out.get("started_at")
        return out
    out["status"] = in_st or ex_st
    out["ui_message"] = incoming.get("ui_message") or out.get("ui_message")
    if incoming.get("started_at"):
        out["started_at"] = incoming["started_at"]
    return out


class PhaseStateCollector:
    """Track pipeline `state` events for latency_ms summary (same merge rules as SSE accumulator)."""

    def __init__(self) -> None:
        self._by_phase: Dict[str, dict] = {}
        self._order: List[str] = []

    def record(self, event: dict) -> None:
        if event.get("type") != "state":
            return
        phase = event.get("phase")
        if not phase:
            return
        incoming = state_slice_from_event(event)
        if phase not in self._by_phase:
            self._order.append(phase)
            self._by_phase[phase] = incoming
        else:
            self._by_phase[phase] = merge_phase_states(self._by_phase[phase], incoming)

    def terminal_states(self) -> List[dict]:
        return [
            self._by_phase[p]
            for p in self._order
            if self._by_phase[p].get("status") in _TERMINAL_STATE_STATUSES
        ]


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
