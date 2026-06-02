"""FastAPI route handlers."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from ..config import has_langsmith_credentials, resolve_router_model, settings
from ..core.normalize import (
    header_ids,
    header_rag_user,
    max_request_body_bytes,
    reject_body_correlation_fields,
    trace_id_from_header,
    request_timeout_s,
    resolve_effective_conversation_id,
    stream_idle_timeout_s,
    validate_answer_body_limits,
    validate_eval_router_body_limits,
)
from ..core.router import decision_to_route_detail, normalize_post_router, run_intent_rewrite_router
from ..core.sse import SSE_HEADERS, answer_json, sse_feedback_gen, sse_stream_answer_gen
from ..core.intent_router import RouterDecision
from ..observability.feedback import FEEDBACK_TYPES, FeedbackBody, submit_langsmith_feedback
from ..observability.metrics import inc_timeout, metrics_content_type, metrics_payload
from ..clients.ready import run_readiness
from ..observability.context import bind_conversation_logging_context
from ..schemas.request import (
    AnswerBody,
    EvalRouterBody,
    history_from_answer_body,
    history_from_eval_body,
)
from ..schemas.route import (
    CANONICAL_ROUTES,
    is_internal_route,
    normalize_gold_expected_route,
    route_detail_to_dict,
    routes_equivalent,
)

router = APIRouter()
v1_router = APIRouter(prefix="/v1")
_http_log = logging.getLogger("layer_orchestrator.http")


def _router_eval_payload(
    decision: RouterDecision,
    *,
    question: str,
    history: List[tuple],
    expected_route: Optional[str],
) -> dict:
    route_detail = decision_to_route_detail(decision)
    actual_route = decision.route
    exp = (
        normalize_gold_expected_route(expected_route)
        if isinstance(expected_route, str) and expected_route.strip()
        else None
    )

    checks: Dict[str, bool] = {
        "has_rewrite": bool((decision.rewritten_question or "").strip()),
        "route_valid": actual_route in CANONICAL_ROUTES,
        "static_answer_ok": (
            not is_internal_route(actual_route)
            or actual_route in ("reject",)
            or bool((decision.static_answer or "").strip())
            or actual_route in ("greeting", "identity", "help", "capabilities")
        ),
    }
    if exp is not None:
        checks["route_match"] = routes_equivalent(exp, actual_route)
    else:
        checks["route_match"] = True
    if history:
        checks["history_followup_rewritten"] = (
            (decision.rewritten_question or "").strip().lower() != (question or "").strip().lower()
        )
    else:
        checks["history_followup_rewritten"] = True
    notes: List[str] = []
    if not checks["has_rewrite"]:
        notes.append("rewritten_question is empty")
    if not checks["route_valid"]:
        notes.append("route is not in allowed set")
    if exp is not None and not checks["route_match"]:
        notes.append(f"route mismatch: expected {exp}, got {actual_route}")
    if not checks["static_answer_ok"]:
        notes.append("internal route returned empty static_answer")
    if history and not checks["history_followup_rewritten"]:
        notes.append("history exists but rewritten_question did not change from question")
    all_checks_pass = all(checks.values())
    route_match = checks["route_match"] if exp is not None else None
    return {
        "expected_route": exp,
        "actual_route": actual_route,
        "route_detail": route_detail_to_dict(route_detail),
        "route_source": decision.source,
        "route_match": route_match,
        "all_checks_pass": all_checks_pass,
        "checks": checks,
        "notes": notes,
    }


@v1_router.post("/orchestrator/answer")
async def orchestrator_answer(body: AnswerBody, request: Request):
    """Unified endpoint: stream=true (default) returns SSE; stream=false returns aggregated JSON."""
    raw_bytes = await request.body()
    conversation_id, is_new_conversation = resolve_effective_conversation_id(body.conversation_id)
    request.state.conversation_id = conversation_id
    async with bind_conversation_logging_context(conversation_id, is_new_conversation):
        validate_answer_body_limits(body, len(raw_bytes), conversation_id=conversation_id)
        try:
            raw_body = json.loads(raw_bytes)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="invalid JSON body")
        reject_body_correlation_fields(raw_body)
        session_id, request_id, trace_id = header_ids(request)
        trace_from_hdr = trace_id_from_header(request)
        rag_user = header_rag_user(request)
        hist = history_from_answer_body(body)
        req_timeout = request_timeout_s()
        idle_timeout = stream_idle_timeout_s()
    if body.stream:
        return StreamingResponse(
            sse_stream_answer_gen(
                body.question,
                session_id=session_id,
                request_id=request_id,
                trace_id=trace_id,
                trace_id_from_header=trace_from_hdr,
                rag_user=rag_user,
                history=hist,
                conversation_id=conversation_id,
                is_new_conversation=is_new_conversation,
                request_timeout_s=req_timeout,
                stream_idle_timeout_s=idle_timeout,
            ),
            media_type="text/event-stream",
            headers=SSE_HEADERS,
        )
    async with bind_conversation_logging_context(conversation_id, is_new_conversation):
        try:
            result = await asyncio.wait_for(
                answer_json(
                    body.question,
                    session_id=session_id,
                    request_id=request_id,
                    trace_id=trace_id,
                    trace_id_from_header=trace_from_hdr,
                    rag_user=rag_user,
                    history=hist,
                    conversation_id=conversation_id,
                    is_new_conversation=is_new_conversation,
                ),
                timeout=req_timeout,
            )
        except asyncio.TimeoutError:
            inc_timeout("request")
            return JSONResponse(
                {
                    "status": "error",
                    "error": "request timeout exceeded",
                    "request_id": request_id,
                    "session_id": session_id,
                    "trace_id": trace_id,
                    "conversation_id": conversation_id,
                    "is_new_conversation": is_new_conversation,
                },
                status_code=504,
            )
        status_code = 200 if (result.get("status") or {}).get("ok") else 500
        return JSONResponse(result, status_code=status_code)


@v1_router.post("/orchestrator/eval/router")
async def orchestrator_eval_router(request: Request):
    """Evaluate intent router decision only (no tool execution)."""
    raw_bytes = await request.body()
    if len(raw_bytes) > max_request_body_bytes():
        raise HTTPException(
            status_code=413,
            detail=(
                f"request body too large: {len(raw_bytes)} bytes > "
                f"{max_request_body_bytes()} bytes (MAX_REQUEST_BODY_MB={settings.max_request_body_mb})"
            ),
        )
    try:
        raw_obj = json.loads(raw_bytes)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid JSON body")
    if not isinstance(raw_obj, dict):
        raise HTTPException(status_code=400, detail="JSON body must be an object")
    reject_body_correlation_fields(raw_obj)
    body = EvalRouterBody.model_validate(raw_obj)
    conversation_id, is_new_conversation = resolve_effective_conversation_id(body.conversation_id)
    request.state.conversation_id = conversation_id
    validate_eval_router_body_limits(body, conversation_id=conversation_id)
    session_id, request_id, trace_id = header_ids(request)
    async with bind_conversation_logging_context(conversation_id, is_new_conversation):
        hist = history_from_eval_body(body)
        resolved_temp = 0.0 if body.router_temperature is None else float(body.router_temperature)
        resolved_model = resolve_router_model(body.router_model)
        run_meta: Dict[str, Any] = {}
        decision = await run_intent_rewrite_router(
            body.question,
            hist,
            request_id=request_id,
            session_id=session_id,
            trace_id=trace_id,
            router_model=body.router_model,
            router_temperature=body.router_temperature,
            router_prompt_version=body.router_prompt_version,
            router_system_prompt=body.router_prompt_override,
            runtime_meta=run_meta,
            conversation_id=conversation_id,
            is_new_conversation=is_new_conversation,
        )
        decision = normalize_post_router(decision, latest_question=body.question, history=hist)
        evaluation = _router_eval_payload(
            decision,
            question=body.question,
            history=hist,
            expected_route=body.expected_route,
        )
        route_detail = decision_to_route_detail(decision)
        prompt_override_used = bool((body.router_prompt_override or "").strip())
        return {
            "request_id": request_id,
            "session_id": session_id,
            "trace_id": trace_id,
            "conversation_id": conversation_id,
            "is_new_conversation": is_new_conversation,
            "router": {
                "model": resolved_model,
                "temperature": resolved_temp,
                "prompt_version": body.router_prompt_version,
                "prompt_source": run_meta.get("prompt_source"),
                "prompt_file": run_meta.get("prompt_file"),
                "prompt_fallback_from": run_meta.get("prompt_requested_fallback"),
                "smalltalk_intent": run_meta.get("smalltalk_intent"),
                "prompt_override_used": prompt_override_used,
            },
            "decision": {
                "rewritten_question": decision.rewritten_question,
                "route": decision.route,
                "confidence": decision.confidence,
                "source": decision.source,
                "route_detail": route_detail_to_dict(route_detail),
                "static_answer": decision.static_answer,
                "reason": decision.reason,
            },
            "evaluation": evaluation,
            "status": "ok",
        }


@v1_router.post("/feedback")
async def submit_feedback(body: FeedbackBody, request: Request):
    """Submit feedback on an agent response; always returns SSE."""
    session_id, request_id, trace_id = header_ids(request)
    if body.feedback_type and body.feedback_type not in FEEDBACK_TYPES:
        msg = f"feedback_type must be one of: {', '.join(sorted(FEEDBACK_TYPES))}"
        return StreamingResponse(
            sse_feedback_gen(
                request_id=request_id,
                session_id=session_id,
                trace_id=trace_id,
                status="error",
                message=msg,
            ),
            media_type="text/event-stream",
            headers=SSE_HEADERS,
        )
    run_id_for_feedback = body.agent_graph_run_id or body.trace_id or body.request_id
    logging.getLogger("layer_orchestrator.feedback").info(
        "feedback_received",
        extra={
            "gateway_meta": {
                "rating": body.rating,
                "feedback_type": body.feedback_type,
                "question_preview": (body.question or "")[:80] or None,
                "comment_preview": (body.comment or "")[:80] or None,
            },
        },
    )
    if run_id_for_feedback and has_langsmith_credentials():
        await asyncio.to_thread(
            submit_langsmith_feedback,
            agent_graph_run_id=run_id_for_feedback,
            rating=body.rating,
            feedback_type=body.feedback_type,
            comment=body.comment,
        )
    return StreamingResponse(
        sse_feedback_gen(
            request_id=request_id,
            session_id=session_id,
            trace_id=trace_id,
            status="ok",
            message="Feedback received",
        ),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.get("/health")
def health() -> dict:
    """Liveness: process up (no dependency checks). Use GET /version for build metadata."""
    return {"status": "ok"}


@router.get("/version")
def version() -> dict:
    from app.build_info import version_payload

    return version_payload()


@router.get("/ready")
async def ready():
    all_ok, body = await run_readiness()
    status_code = 200 if all_ok else 503
    return JSONResponse(body, status_code=status_code)


@router.get("/metrics")
def metrics():
    return Response(content=metrics_payload(), media_type=metrics_content_type())
