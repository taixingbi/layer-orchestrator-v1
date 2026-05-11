"""Prometheus metrics for HTTP and orchestrator pipeline."""

from typing import Any, Optional

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

_HTTP_LATENCY_BUCKETS = (0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0)
_PIPELINE_LATENCY_BUCKETS = (
    0.01,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.0,
    5.0,
    10.0,
    20.0,
    30.0,
    60.0,
)

HTTP_REQUESTS_TOTAL = Counter(
    "orchestrator_http_requests_total",
    "Total HTTP requests handled by the orchestrator.",
    ("method", "path", "status"),
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "orchestrator_http_request_duration_seconds",
    "HTTP request latency in seconds.",
    ("method", "path"),
    buckets=_HTTP_LATENCY_BUCKETS,
)

ORCHESTRATOR_ROUTE_TOTAL = Counter(
    "orchestrator_route_decisions_total",
    "Route decisions emitted by the intent router.",
    ("route",),
)
ORCHESTRATOR_ERRORS_TOTAL = Counter(
    "orchestrator_pipeline_errors_total",
    "Pipeline-level errors emitted by orchestrator stream events.",
    ("kind",),
)
ORCHESTRATOR_TIMEOUTS_TOTAL = Counter(
    "orchestrator_timeouts_total",
    "Timeouts observed in orchestrator handling.",
    ("kind",),
)
ORCHESTRATOR_ROUTER_DURATION_SECONDS = Histogram(
    "orchestrator_router_duration_seconds",
    "Intent router phase duration.",
    buckets=_PIPELINE_LATENCY_BUCKETS,
)
ORCHESTRATOR_RAG_DURATION_SECONDS = Histogram(
    "orchestrator_rag_duration_seconds",
    "RAG phase duration.",
    buckets=_PIPELINE_LATENCY_BUCKETS,
)


def _to_seconds(latency_ms: Any) -> Optional[float]:
    if isinstance(latency_ms, (int, float)):
        return max(0.0, float(latency_ms) / 1000.0)
    return None


def observe_http(method: str, path: str, status_code: int, latency_s: float) -> None:
    status = str(int(status_code))
    HTTP_REQUESTS_TOTAL.labels(method=method, path=path, status=status).inc()
    HTTP_REQUEST_DURATION_SECONDS.labels(method=method, path=path).observe(max(0.0, latency_s))


def observe_pipeline_event(event: dict) -> None:
    et = event.get("type")
    if et == "route":
        route = str(event.get("route") or "unknown").strip() or "unknown"
        ORCHESTRATOR_ROUTE_TOTAL.labels(route=route).inc()
        return
    if et == "state":
        phase = str(event.get("phase") or "")
        status = str(event.get("status") or "")
        latency_s = _to_seconds(event.get("latency_ms"))
        if status == "completed" and latency_s is not None:
            if phase == "intent_router":
                ORCHESTRATOR_ROUTER_DURATION_SECONDS.observe(latency_s)
            elif phase == "rag_query":
                ORCHESTRATOR_RAG_DURATION_SECONDS.observe(latency_s)
        return
    if et == "error":
        ORCHESTRATOR_ERRORS_TOTAL.labels(kind="event_error").inc()


def inc_timeout(kind: str) -> None:
    ORCHESTRATOR_TIMEOUTS_TOTAL.labels(kind=kind).inc()


def metrics_payload() -> bytes:
    return generate_latest()


def metrics_content_type() -> str:
    return CONTENT_TYPE_LATEST
