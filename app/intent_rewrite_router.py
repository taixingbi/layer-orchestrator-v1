"""Single LLM call: rewrite + route (rag | direct_reply | clarify | reject) as structured JSON."""
import json
import logging
import re
import time
from typing import List, Literal, Optional, Tuple

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, field_validator

from .agent_rewrite import (
    REWRITE_HISTORY_MAX_LINES,
    format_history_for_prompt,
    normalize_history_turns,
    rewrite_to_third_person,
)
from .config import gateway_llm_invoke_kwargs, get_langsmith_tags, get_llm

_router_log = logging.getLogger("layer_orchestrator.intent_router")

ROUTER_SYSTEM = """You are the orchestrator router.

Use conversation history only to rewrite the latest user question.

Return JSON only, with no markdown fences, no other text:
{
  "rewritten_question": string,
  "route": "rag" | "direct_reply" | "clarify" | "reject",
  "can_answer_directly": boolean,
  "direct_answer": string | null,
  "reason": string
}

Rules:
- If the user asks about private, user-specific, project-internal, or document-grounded knowledge, set route to "rag", can_answer_directly false, direct_answer null.
- If the user only greets or asks a simple common public question (no private data), you may set route to "direct_reply" with a short direct_answer.
- If the latest question depends on history, rewrite it as a standalone search-friendly rewritten_question (for rag) or a clear paraphrase (for other routes).
- Short conversational follow-ups that only need high-level, widely known guidance (e.g. travel considerations after visa class was already stated in history)—not employer-internal facts, not citations from a knowledge base, not personalized legal advice—may use route "direct_reply" with a brief direct_answer; note uncertainty and suggest consulting official sources or counsel when appropriate.
- Do not put private or document-specific factual answers in direct_answer; those must go through "rag".
- If the question is ambiguous, use route "clarify" and put what you need in direct_answer or a short prompt.
- If the request is unsafe or disallowed, use route "reject" with a brief refusal in direct_answer.
- Keep rewritten_question short and search-friendly."""

# Phrases on the **latest user message only** that force RAG if the model chose direct_reply (defense in depth).
# Rewritten_question often injects visa tokens from history for search; do not use it here or follow-ups get forced to rag.
# Word-boundary matching avoids substring false positives (e.g. "ead" inside "instead").
_SENSITIVE_HINTS: frozenset[str] = frozenset(
    (
        "visa",
        "h4",
        "ead",
        "work authorization",
        "sponsorship",
        "salary",
        "compensation",
    )
)


def _sensitive_hint_regex_fragment(hint: str) -> str:
    if " " in hint.strip():
        inner = r"\s+".join(re.escape(w) for w in hint.split())
        return rf"\b(?:{inner})\b"
    return rf"\b{re.escape(hint)}\b"


_SENSITIVE_PATTERN = re.compile(
    "|".join(
        _sensitive_hint_regex_fragment(h)
        for h in sorted(_SENSITIVE_HINTS, key=len, reverse=True)
    ),
    re.IGNORECASE,
)

_VALID_ROUTES = frozenset({"rag", "direct_reply", "clarify", "reject"})


class RouterDecision(BaseModel):
    model_config = ConfigDict(extra="ignore")

    rewritten_question: str = ""
    route: Literal["rag", "direct_reply", "clarify", "reject"] = "rag"
    can_answer_directly: bool = False
    direct_answer: Optional[str] = None
    reason: str = ""

    @field_validator("route", mode="before")
    @classmethod
    def normalize_route(cls, v: object) -> str:
        if v is None:
            return "rag"
        s = str(v).strip().lower()
        if s in _VALID_ROUTES:
            return s
        return "rag"

    @field_validator("can_answer_directly", mode="before")
    @classmethod
    def coerce_bool(cls, v: object) -> bool:
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.strip().lower() in ("true", "1", "yes", "y")
        return bool(v)


def _strip_json_fences(raw: str) -> str:
    t = raw.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.IGNORECASE)
        t = re.sub(r"\s*```\s*$", "", t)
    return t.strip()


def _extract_json_object(raw: str) -> Optional[dict]:
    t = _strip_json_fences(raw)
    try:
        obj = json.loads(t)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    start = t.find("{")
    end = t.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(t[start : end + 1])
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def fallback_router_decision(question: str, *, reason: str = "parse_fallback") -> RouterDecision:
    q = (question or "").strip()
    rq = rewrite_to_third_person(q) if q else ""
    return RouterDecision(
        rewritten_question=rq or q,
        route="rag",
        can_answer_directly=False,
        direct_answer=None,
        reason=reason,
    )


def _sensitive_topics_match(blob: str) -> bool:
    return bool(_SENSITIVE_PATTERN.search(blob))


def apply_direct_reply_guard(decision: RouterDecision, latest_question: str) -> RouterDecision:
    """If route is direct_reply but the user's latest text looks like a sensitive topic, force rag."""
    if decision.route != "direct_reply":
        return decision
    blob = (latest_question or "").lower()
    if _sensitive_topics_match(blob):
        extra = " [server: forced rag for sensitive topic]"
        return RouterDecision(
            rewritten_question=decision.rewritten_question or rewrite_to_third_person(latest_question.strip()),
            route="rag",
            can_answer_directly=False,
            direct_answer=None,
            reason=(decision.reason or "").strip() + extra,
        )
    return decision


def normalize_post_router(decision: RouterDecision) -> RouterDecision:
    """Empty direct_reply answer → clarify-style response."""
    if decision.route != "direct_reply":
        return decision
    if (decision.direct_answer or "").strip():
        return decision
    msg = f"Please add more detail. ({decision.reason or 'Unclear request.'})"
    return RouterDecision(
        rewritten_question=decision.rewritten_question,
        route="clarify",
        can_answer_directly=False,
        direct_answer=msg,
        reason=(decision.reason or "") + " [server: empty direct_reply → clarify]",
    )


async def run_intent_rewrite_router(
    question: str,
    history: List[Tuple[str, str]],
    *,
    request_id: Optional[str] = None,
    session_id: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> RouterDecision:
    """One LLM call returning RouterDecision; parse errors fall back to conservative rag."""
    q = (question or "").strip()
    if not q:
        return fallback_router_decision(question, reason="empty_question")

    hist = normalize_history_turns(history)
    hist_block = format_history_for_prompt(hist, REWRITE_HISTORY_MAX_LINES)
    user_body = (
        f"History:\n{hist_block}\n\nLatest question:\n{q}" if hist_block else f"History:\n(none)\n\nLatest question:\n{q}"
    )

    t0 = time.perf_counter()
    llm = get_llm()
    invoke_kw = gateway_llm_invoke_kwargs(request_id, session_id, trace_id)
    try:
        msg = await llm.ainvoke(
            [SystemMessage(content=ROUTER_SYSTEM), HumanMessage(content=user_body)],
            config={
                "run_name": "intent_rewrite_router",
                "tags": get_langsmith_tags(request_id=request_id, session_id=session_id),
            },
            max_tokens=512,
            **invoke_kw,
        )
        raw = (msg.content or "").strip()
        obj = _extract_json_object(raw)
        if not obj:
            _router_log.warning(
                "intent_router_parse_failed",
                extra={
                    "event": "intent_router_parse_failed",
                    "gateway_meta": {"preview": (raw or "")[:200] or None},
                },
            )
            return fallback_router_decision(q, reason="parse_fallback")
        decision = RouterDecision.model_validate(obj)
        if not (decision.rewritten_question or "").strip():
            decision = decision.model_copy(
                update={"rewritten_question": rewrite_to_third_person(q)},
            )
        _router_log.info(
            "intent_router_completed",
            extra={
                "event": "intent_router_completed",
                "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
                "gateway_meta": {
                    "route": decision.route,
                    "reason_preview": (decision.reason or "")[:160] or None,
                    "rewritten_preview": (decision.rewritten_question or "")[:120] or None,
                },
            },
        )
        return decision
    except Exception as e:
        _router_log.error(
            "intent_router_invoke_failed",
            extra={
                "event": "intent_router_invoke_failed",
                "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
        )
        return fallback_router_decision(q, reason=f"invoke_error:{type(e).__name__}")
