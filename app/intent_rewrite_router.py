"""Single LLM call: rewrite + route (rag | direct_reply | clarify | reject) as structured JSON."""
import json
import logging
import re
import time
from typing import List, Literal, Optional, Tuple

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, field_validator

from .agent_rewrite import (
    CANDIDATE_NAME,
    REWRITE_HISTORY_MAX_LINES,
    format_history_for_prompt,
    normalize_history_turns,
    rewrite_to_third_person,
)
from .config import gateway_llm_invoke_kwargs, get_langsmith_tags, get_llm

_router_log = logging.getLogger("layer_orchestrator.intent_router")

ROUTER_SYSTEM = f"""You are the orchestrator router.

Use conversation history only to rewrite the latest user question.

Return JSON only, with no markdown fences, no other text:
{{
  "rewritten_question": string,
  "route": "rag" | "direct_reply" | "clarify" | "reject",
  "can_answer_directly": boolean,
  "direct_answer": string | null,
  "reason": string
}}

Routing priority (apply in order):
1) **direct_reply** — Use when the latest question is **general** (common public knowledge: definitions, how a visa or benefit category works, typical processes, renewal requirements in general, greetings, math/coding trivia, etc.) OR when it is **not about {CANDIDATE_NAME}** in a way that needs their profile or your employer documents. Set can_answer_directly true, put a concise helpful direct_answer (note uncertainty; suggest official sources or counsel for immigration/legal topics). rewritten_question may paraphrase the user ask; it is not used for retrieval on this route.
2) **rag** — Use when the user needs **{CANDIDATE_NAME}-specific** facts (their status, dates, employer-internal HR/policy, résumé or performance claims, project-internal details) or answers that must be **grounded in the knowledge base with citations**, not invented. Set can_answer_directly false, direct_answer null. Produce a standalone search-friendly rewritten_question.
3) **clarify** / **reject** — Same as before.

Additional rules:
- Never put {CANDIDATE_NAME}-specific or document-only factual claims in direct_answer; those belong in rag with retrieval.
- History may mention {CANDIDATE_NAME} or a visa class; if the **latest question** only asks a **general** follow-up (e.g. renewal rules for that visa type, not "what did we file for {CANDIDATE_NAME}?"), use **direct_reply**, not rag.
- If the latest question depends on history for meaning, still choose direct_reply vs rag by whether the answer should be general vs candidate/doc-grounded.
- If the question is ambiguous, use route "clarify" and put what you need in direct_answer or a short prompt.
- If the request is unsafe or disallowed, use route "reject" with a brief refusal in direct_answer.
- Keep rewritten_question short and search-friendly (especially for rag)."""

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
