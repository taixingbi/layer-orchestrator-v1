"""Stderr JSON logging plus optional Grafana Loki via tb-loki-central-logger.

Pattern aligned with layer-rag-query-v1 ``app/logging_config.py``:
https://github.com/taixingbi/layer-rag-query-v1/blob/main/app/logging_config.py
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import queue
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import __version__
from .request_context import (
    get_http_method,
    get_http_path,
    get_http_status,
    get_request_id,
    get_session_id,
)

logger = logging.getLogger("layer_orchestrator")

_LOKI_PUSH_ERRORS_LOGGED = 0
_LOKI_PUSH_ERROR_LOG_CAP = 5

try:
    from tb_loki_central_logger import LokiClient, basic_auth_from_env
except ImportError:  # optional dependency
    LokiClient = None  # type: ignore[misc, assignment]

    def basic_auth_from_env():  # type: ignore[misc]
        return None


if LokiClient is not None:

    class _LokiClientNoSystemProxy(LokiClient):
        """Same as LokiClient but does not use HTTP(S)_PROXY (broken tunnels often return 403)."""

        _opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def _send(self, body: bytes) -> None:
            req = urllib.request.Request(
                self.endpoint,
                data=body,
                headers=self._http_headers,
                method="POST",
            )
            with self._lock:
                try:
                    with self._opener.open(req, timeout=self.timeout) as resp:
                        resp.read()
                except urllib.error.HTTPError as e:
                    detail = e.read().decode("utf-8", errors="replace")
                    raise RuntimeError(
                        f"Loki push failed: HTTP {e.code} {e.reason}. Response: {detail}"
                    ) from e
                except urllib.error.URLError as e:
                    raise RuntimeError(f"Loki push failed: {e}") from e

    def _loki_client_cls() -> type:
        v = os.getenv("LOKI_IGNORE_SYSTEM_PROXY", "").strip().lower()
        if v in ("1", "true", "yes", "on"):
            return _LokiClientNoSystemProxy
        return LokiClient
else:

    def _loki_client_cls() -> type:  # type: ignore[misc]
        raise RuntimeError("tb_loki_central_logger not installed")


_LOKI_LEVEL = {
    "DEBUG": "debug",
    "INFO": "info",
    "WARNING": "warn",
    "ERROR": "error",
    "CRITICAL": "critical",
}


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
    "trace_id",
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
    "event",
)


class _SyncLokiHandler(logging.Handler):
    """Ship each record with LokiClient in emit(); used only from a QueueListener worker thread."""

    def __init__(
        self,
        *,
        labels: dict[str, str],
        basic_auth: tuple[str, str],
        timeout: int = 15,
    ) -> None:
        super().__init__()
        if LokiClient is None:
            raise RuntimeError("LokiClient unavailable")
        self._client = _loki_client_cls()(
            labels=labels,
            timeout=timeout,
            basic_auth=basic_auth,
        )

    def emit(self, record: logging.LogRecord) -> None:
        global _LOKI_PUSH_ERRORS_LOGGED
        try:
            level = _LOKI_LEVEL.get(record.levelname, "info")
            message = self.format(record)
            self._client.push(message, level=level, labels={"logger": record.name})
        except Exception as e:
            _LOKI_PUSH_ERRORS_LOGGED += 1
            n = _LOKI_PUSH_ERRORS_LOGGED
            if n <= _LOKI_PUSH_ERROR_LOG_CAP:
                print(
                    f"layer_orchestrator: Loki push failed: {e}; "
                    f"logs still go to stderr. "
                    f"If you use a proxy, try LOKI_IGNORE_SYSTEM_PROXY=1 in `.env`.",
                    file=sys.stderr,
                )
            elif n == _LOKI_PUSH_ERROR_LOG_CAP + 1:
                print(
                    "layer_orchestrator: further Loki push errors suppressed",
                    file=sys.stderr,
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
        return True


class _JsonFormatter(logging.Formatter):
    """One JSON object per line for stderr and Loki."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=_LOG_TZ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "session_id": getattr(record, "session_id", "-"),
            "method": getattr(record, "method", "-"),
            "path": getattr(record, "path", "-"),
            "status": getattr(record, "status", "-"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)
        for key in _EXTRA_JSON_FIELDS:
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        return json.dumps(payload, ensure_ascii=False, default=str)


_JSON_FORMATTER = _JsonFormatter()

_loki_listener: logging.handlers.QueueListener | None = None
_loki_queue_handler: logging.handlers.QueueHandler | None = None
_loki_worker_handler: _SyncLokiHandler | None = None

_setup_done = False


def _resolve_log_level() -> int:
    name = (os.environ.get("LOG_LEVEL") or "INFO").upper()
    return getattr(logging, name, logging.INFO)


def setup_logging() -> None:
    """Configure ``layer_orchestrator`` logger: stderr JSON, optional Loki queue + worker when Grafana env is set."""
    global _loki_listener, _loki_queue_handler, _loki_worker_handler, _setup_done
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

    auth = basic_auth_from_env() if LokiClient is not None else None
    if auth is not None:
        log_queue: queue.Queue[logging.LogRecord] = queue.Queue(-1)
        _loki_queue_handler = logging.handlers.QueueHandler(log_queue)
        _loki_queue_handler.setLevel(level)
        logger.addHandler(_loki_queue_handler)

        env_label = (
            os.environ.get("ORCHESTRATOR_ENV")
            or os.environ.get("GATEWAY_ENV")
            or os.environ.get("ENV", "dev")
        )
        _loki_worker_handler = _SyncLokiHandler(
            labels={
                "service": "layer-orchestrator",
                "component": "api",
                "env": env_label,
                "version": __version__,
            },
            basic_auth=auth,
        )
        _loki_worker_handler.setLevel(level)
        _loki_worker_handler.setFormatter(_JSON_FORMATTER)
        _loki_worker_handler.addFilter(_ctx_filter)
        _loki_listener = logging.handlers.QueueListener(
            log_queue,
            _loki_worker_handler,
            respect_handler_level=True,
        )
        _loki_listener.start()
        logger.info("centralized Loki logging enabled")
    else:
        if LokiClient is None:
            logger.info("Loki disabled (tb-loki-central-logger not installed)")
        else:
            logger.info(
                "Loki disabled (set GRAFANA_CLOUD_API_KEY to ship logs to Grafana)"
            )


def shutdown_logging() -> None:
    """Stop the Loki queue listener and detach Loki handlers."""
    global _loki_listener, _loki_queue_handler, _loki_worker_handler, _setup_done
    if _loki_listener is not None:
        _loki_listener.stop()
        _loki_listener = None
    if _loki_queue_handler is not None:
        logger.removeHandler(_loki_queue_handler)
        _loki_queue_handler.close()
        _loki_queue_handler = None
    if _loki_worker_handler is not None:
        _loki_worker_handler.close()
        _loki_worker_handler = None
    for h in logger.handlers:
        if isinstance(h, logging.StreamHandler):
            h.flush()
    _setup_done = False


def new_request_id() -> str:
    """UUID for ``x-request-id`` when the client does not send one."""
    return str(uuid.uuid4())
