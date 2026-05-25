# main.py — FastAPI orchestrator entrypoint
import contextlib
import logging
import time

from .config import settings
from .observability.logging import new_request_id, setup_logging, shutdown_logging
from .observability.metrics import observe_http
from .observability.context import (
    bind_pipeline_phase,
    bind_request_context,
    reset_request_context,
    set_http_status,
)

setup_logging()

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.requests import Request

from .api.routes import router, v1_router
from .core.normalize import max_request_body_bytes

_http_log = logging.getLogger("layer_orchestrator.http")


def _latency_ms(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000, 2)


@contextlib.asynccontextmanager
async def _lifespan(_app: FastAPI):
    try:
        yield
    finally:
        from .clients.rag_http import aclose_rag_http_client
        from .tools.mcp_client import aclose_mcp_client

        await aclose_rag_http_client()
        await aclose_mcp_client()
        shutdown_logging()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=_lifespan,
)


@app.middleware("http")
async def _http_request_logging_middleware(request: Request, call_next):
    if request.url.path in ("/health", "/ready", "/metrics", "/version"):
        t0 = time.perf_counter()
        response = await call_next(request)
        observe_http(
            method=request.method,
            path=request.url.path,
            status_code=int(response.status_code),
            latency_s=(time.perf_counter() - t0),
        )
        return response
    if request.url.path == "/v1/orchestrator/answer":
        raw_cl = (request.headers.get("content-length") or "").strip()
        if raw_cl:
            try:
                cl = int(raw_cl)
                if cl > max_request_body_bytes():
                    return JSONResponse(
                        {
                            "status": "error",
                            "error": (
                                f"request body too large: {cl} bytes > {max_request_body_bytes()} bytes "
                                f"(MAX_REQUEST_BODY_MB={settings.max_request_body_mb})"
                            ),
                        },
                        status_code=413,
                    )
            except ValueError:
                pass

    request_id = request.headers.get("x-request-id") or new_request_id()
    session_id = request.headers.get("x-session-id")
    trace_id = request.headers.get("x-trace-id") or request_id
    request.state.request_id = request_id
    request.state.session_id = session_id
    request.state.trace_id = trace_id
    hdr = request.headers

    def _strip_opt(h):
        if h is None:
            return None
        s = h.strip()
        return s if s else None

    request.state.user_id = _strip_opt(hdr.get("x-user-id"))
    request.state.user_roles = _strip_opt(hdr.get("x-user-roles"))
    request.state.user_groups = _strip_opt(hdr.get("x-user-groups"))
    request.state.user_teams = _strip_opt(hdr.get("x-user-teams"))
    path = request.url.path
    method = request.method
    ctx = bind_request_context(
        request_id=request_id,
        session_id=session_id,
        method=method,
        path=path,
    )
    try:
        async with bind_pipeline_phase("http"):
            _http_log.info("http_request_start", extra={"trace_id": trace_id})
            t0 = time.perf_counter()
            try:
                response = await call_next(request)
            except Exception:
                latency_ms = _latency_ms(t0)
                observe_http(method=method, path=path, status_code=500, latency_s=latency_ms / 1000.0)
                _http_log.error(
                    "http_request_error",
                    extra={
                        "latency_ms": latency_ms,
                        "trace_id": trace_id,
                        "error_type": "unhandled_exception",
                    },
                )
                raise
            latency_ms = _latency_ms(t0)
            observe_http(
                method=method,
                path=path,
                status_code=int(response.status_code),
                latency_s=latency_ms / 1000.0,
            )
            response.headers["X-Request-Id"] = request_id
            set_http_status(str(response.status_code))
            http_extra = {
                "latency_ms": latency_ms,
                "status_code": response.status_code,
                "trace_id": trace_id,
            }
            cid = getattr(request.state, "conversation_id", None)
            if isinstance(cid, str) and cid.strip():
                http_extra["conversation_id"] = cid.strip()
            _http_log.info("http_request_complete", extra=http_extra)
            return response
    finally:
        reset_request_context(ctx)


app.include_router(router)
app.include_router(v1_router)
