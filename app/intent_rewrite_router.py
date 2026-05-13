"""Single LLM call: rewrite + route (rag | direct_reply | clarify | reject) as structured JSON."""
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, field_validator

from .agent_rewrite import (
    CANDIDATE_NAME,
    REWRITE_HISTORY_MAX_LINES,
    format_history_for_prompt,
    normalize_history_turns,
    rewrite_to_third_person,
)
from .config import gateway_llm_invoke_kwargs, get_langsmith_tags, get_llm, settings

_router_log = logging.getLogger("layer_orchestrator.intent_router")

_ROUTER_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
_DEFAULT_ROUTER_PROMPT_ID = "router-v1.00"
_ROUTER_PROMPT_VERSION_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")


def _sanitize_router_prompt_version(version_id: str) -> str:
    v = (version_id or "").strip()
    if not v or len(v) > 256 or ".." in v or "/" in v or "\\" in v or v.startswith("."):
        raise ValueError("invalid router prompt version")
    if not _ROUTER_PROMPT_VERSION_RE.match(v):
        raise ValueError("invalid router prompt version")
    return v


def _render_stored_router_prompt(raw: str) -> str:
    name = (CANDIDATE_NAME or "").strip() or "the candidate"
    return raw.replace("__CANDIDATE_NAME__", name)


_SMALLTALK_SEED_PATH = _ROUTER_PROMPTS_DIR / "smalltalk_examples.json"
_smalltalk_seed_cache: Optional[List[Any]] = None


def _normalize_smalltalk_key(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _load_smalltalk_seed() -> List[Any]:
    """Parse smalltalk_examples.json once; empty list if missing or invalid."""
    global _smalltalk_seed_cache
    if _smalltalk_seed_cache is not None:
        return _smalltalk_seed_cache
    if not _SMALLTALK_SEED_PATH.is_file():
        _router_log.warning(
            "smalltalk_seed_missing",
            extra={"event": "smalltalk_seed_missing", "path": str(_SMALLTALK_SEED_PATH)},
        )
        _smalltalk_seed_cache = []
        return _smalltalk_seed_cache
    try:
        raw = json.loads(_SMALLTALK_SEED_PATH.read_text(encoding="utf-8"))
        _smalltalk_seed_cache = raw if isinstance(raw, list) else []
    except (json.JSONDecodeError, OSError) as e:
        _router_log.warning(
            "smalltalk_seed_load_failed",
            extra={"event": "smalltalk_seed_load_failed", "error": str(e)},
        )
        _smalltalk_seed_cache = []
    return _smalltalk_seed_cache


def _match_smalltalk_seed(latest: str) -> Optional[Tuple[str, str]]:
    """If normalized latest equals a seed user_example, return (intent, rendered_answer)."""
    nq = _normalize_smalltalk_key(latest)
    if not nq:
        return None
    for row in _load_smalltalk_seed():
        if not isinstance(row, dict):
            continue
        intent = str(row.get("intent") or "unknown").strip() or "unknown"
        answer = str(row.get("answer") or "").strip()
        examples = row.get("user_examples")
        if not answer or not isinstance(examples, list):
            continue
        for ex in examples:
            if isinstance(ex, str) and _normalize_smalltalk_key(ex) == nq:
                return intent, _render_stored_router_prompt(answer)
    return None


def _answer_for_smalltalk_intent(intent: str) -> Optional[str]:
    """Return rendered answer for the first JSON row with this intent, or None."""
    key = (intent or "").strip()
    if not key:
        return None
    for row in _load_smalltalk_seed():
        if not isinstance(row, dict):
            continue
        if str(row.get("intent") or "").strip() != key:
            continue
        answer = str(row.get("answer") or "").strip()
        if answer:
            return _render_stored_router_prompt(answer)
    return None


def _normalize_smalltalk_for_patterns(latest: str) -> str:
    """Like seed key, then strip trailing sentence punctuation for regex fullmatch."""
    nq = _normalize_smalltalk_key(latest)
    if not nq:
        return ""
    return re.sub(r"[!?.;:,]+$", "", nq).strip()


# Layer 2 (after exact user_examples): conservative full-string regex → intent id → answer from JSON.
# Order matters; only inputs with len(nq) <= _SMALLTALK_PATTERN_MAX_LEN are considered.
_SMALLTALK_PATTERN_MAX_LEN = 120
_SMALLTALK_PATTERN_RULES: List[Tuple[re.Pattern[str], str]] = [
    (re.compile(r"^tell\s+me\s+about\s+yourself$"), "assistant_intro"),
    (re.compile(r"^tell\s+me\s+more\s+about\s+yourself$"), "assistant_intro"),
    (re.compile(r"^tell\s+me\s+who\s+you\s+are$"), "assistant_intro"),
    (re.compile(r"^(could|would|can)\s+you\s+tell\s+me\s+who\s+you\s+are$"), "assistant_intro"),
    (re.compile(r"^(please\s+)?introduce\s+yourself$"), "assistant_intro"),
    (re.compile(r"^(can|could)\s+you\s+introduce\s+yourself$"), "assistant_intro"),
    (re.compile(r"^what\s+are\s+you$"), "assistant_intro"),
    (re.compile(r"^(may|could|can)\s+i\s+know\s+your\s+name$"), "bot_name"),
    (re.compile(r"^(please\s+)?(tell|give)\s+me\s+your\s+name$"), "bot_name"),
    (re.compile(r"^(i\s+)?(just\s+)?(wanted|want)\s+to\s+know\s+your\s+name$"), "bot_name"),
    (re.compile(r"^may\s+i\s+ask\s+your\s+name$"), "bot_name"),
    (re.compile(r"^what\s+(should|do)\s+i\s+call\s+you$"), "bot_name"),
    (re.compile(r"^what\s+do\s+you\s+call\s+yourself$"), "bot_name"),
    (re.compile(r"^do\s+you\s+have\s+a\s+name$"), "bot_name"),
    (re.compile(r"^who\s+are\s+you$"), "bot_name"),
    (re.compile(r"^how\s+are\s+you\s+(doing|today|feeling|going)$"), "greeting_status"),
    (re.compile(r"^how\s+are\s+ya$"), "greeting_status"),
    (re.compile(r"^how\s+are\s+u$"), "greeting_status"),
    (re.compile(r"^how\s+r\s+u$"), "greeting_status"),
    (re.compile(r"^(how'?s|hows)\s+it\s+going$"), "greeting_status"),
    (re.compile(r"^how\s+can\s+you\s+help(\s+me)?$"), "capabilities"),
    (re.compile(r"^where\s+did\s+you\s+come\s+from$"), "origin"),
]


def _match_smalltalk_patterns(latest: str) -> Optional[Tuple[str, str]]:
    """If normalized question matches a short-utterance pattern, return (intent, rendered_answer)."""
    nq = _normalize_smalltalk_for_patterns(latest)
    if not nq or len(nq) > _SMALLTALK_PATTERN_MAX_LEN:
        return None
    for rx, intent in _SMALLTALK_PATTERN_RULES:
        if rx.fullmatch(nq):
            answer = _answer_for_smalltalk_intent(intent)
            if answer:
                return intent, answer
    return None


def _match_smalltalk_any(latest: str) -> Optional[Tuple[str, str, str]]:
    """Exact seed first, then pattern layer. Returns (intent, answer, prompt_source) or None."""
    hit = _match_smalltalk_seed(latest)
    if hit:
        intent, answer = hit
        return intent, answer, "smalltalk_seed"
    hit = _match_smalltalk_patterns(latest)
    if hit:
        intent, answer = hit
        return intent, answer, "smalltalk_pattern"
    return None


def _read_router_prompt_file(version_id: str) -> Tuple[str, str, Optional[str]]:
    """Return (raw_text, resolved_file_id, requested_id_if_fallback_else_None)."""
    safe = _sanitize_router_prompt_version(version_id)
    path = _ROUTER_PROMPTS_DIR / f"{safe}.txt"
    if path.is_file():
        return path.read_text(encoding="utf-8"), safe, None
    _router_log.warning(
        "router_prompt_file_missing",
        extra={"event": "router_prompt_file_missing", "requested": safe, "fallback": _DEFAULT_ROUTER_PROMPT_ID},
    )
    fb = _ROUTER_PROMPTS_DIR / f"{_DEFAULT_ROUTER_PROMPT_ID}.txt"
    if not fb.is_file():
        raise RuntimeError(
            f"Missing default router prompt file {_DEFAULT_ROUTER_PROMPT_ID}.txt under {_ROUTER_PROMPTS_DIR}"
        )
    return fb.read_text(encoding="utf-8"), _DEFAULT_ROUTER_PROMPT_ID, safe


def _resolve_router_system_content(
    *,
    body_override: Optional[str],
    requested_version: Optional[str],
    default_version: str,
) -> Tuple[str, Dict[str, Any]]:
    if isinstance(body_override, str) and body_override.strip():
        return body_override.strip(), {
            "prompt_source": "body_override",
            "prompt_file": None,
            "prompt_requested_fallback": None,
        }
    raw_default = (default_version or "").strip() or _DEFAULT_ROUTER_PROMPT_ID
    try:
        default_id = _sanitize_router_prompt_version(raw_default)
    except ValueError:
        _router_log.warning(
            "router_prompt_invalid_default",
            extra={"event": "router_prompt_invalid_default", "value": raw_default},
        )
        default_id = _DEFAULT_ROUTER_PROMPT_ID
    req_raw = (requested_version or "").strip()
    version_to_load = req_raw if req_raw else default_id
    try:
        safe_req = _sanitize_router_prompt_version(version_to_load)
    except ValueError:
        _router_log.warning(
            "router_prompt_invalid_version",
            extra={"event": "router_prompt_invalid_version", "value": version_to_load},
        )
        safe_req = default_id
    raw_text, resolved_id, fallback_from = _read_router_prompt_file(safe_req)
    rendered = _render_stored_router_prompt(raw_text)
    return rendered, {
        "prompt_source": "versioned_file",
        "prompt_file": resolved_id,
        "prompt_requested_fallback": fallback_from,
    }


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


# Latest user message: if it matches this and does not name the candidate, prefer direct_reply over rag.
_GENERAL_IMMIGRATION_OR_WORK_AUTH_RE = re.compile(
    r"\b("
    r"h-?4\b|h-?1b?\b|h-?2a\b|h-?2b\b|l-?1a?\b|o-?1\b|\btn\b|ead\b|"
    r"i-?\s*765\b|i-?\s*485\b|i-?\s*140\b|i-?\s*130\b|i-?\s*539\b|"
    r"perm\b|green\s*card|naturalization|citizenship|uscis\b|"
    r"\bvisa\b|renewal|extension|stem\s*opt|\bopt\b|f-?1\b|j-?1\b|advance\s*parole|"
    r"work\s*authorization|work\s*permit|daca\b|asylum\b"
    r")\b",
    re.IGNORECASE,
)

_GENERAL_TOPIC_DIRECT_ANSWER = (
    "This looks like a general U.S. immigration or work-authorization topic, not a question that "
    "should be answered only from your internal document search. For current rules and renewal "
    "steps (including H-4 EAD), use official USCIS/DHS guidance (for example Form I-765 instructions) "
    "and qualified immigration counsel for case-specific advice. "
    "Use the document-backed path when you need citations from your organization's materials."
)


def _latest_question_names_candidate(q: str) -> bool:
    """True if the latest user text likely refers to the named candidate."""
    ql = (q or "").strip().lower()
    if not ql:
        return False
    full = (CANDIDATE_NAME or "").strip().lower()
    if full and full in ql:
        return True
    parts = (CANDIDATE_NAME or "").split()
    if not parts:
        return False
    first = parts[0].lower()
    if len(first) >= 2 and re.search(rf"\b{re.escape(first)}\b", ql):
        return True
    return False


def maybe_override_rag_for_general_question(decision: RouterDecision, latest_question: str) -> RouterDecision:
    """If the router chose rag but the ask is general immigration/process and not about the candidate, use direct_reply."""
    if decision.route != "rag":
        return decision
    q = (latest_question or "").strip()
    if not q or _latest_question_names_candidate(q):
        return decision
    if not _GENERAL_IMMIGRATION_OR_WORK_AUTH_RE.search(q):
        return decision
    suffix = " [server: general_immigration_topic→direct_reply]"
    reason = ((decision.reason or "").strip() + suffix).strip()
    return decision.model_copy(
        update={
            "route": "direct_reply",
            "can_answer_directly": True,
            "direct_answer": _GENERAL_TOPIC_DIRECT_ANSWER,
            "reason": reason,
        },
    )


_SECOND_PERSON_IN_QUESTION_RE = re.compile(r"\b(you|your|yourself)\b", re.IGNORECASE)


def _ensure_rewritten_question_third_person(decision: RouterDecision, latest_question: str) -> RouterDecision:
    """Apply deterministic you→candidate rewrite for RAG queries; fix echoed second-person on other routes."""
    q = (latest_question or "").strip()
    base = (decision.rewritten_question or "").strip() or q
    if decision.route == "rag":
        return decision.model_copy(update={"rewritten_question": rewrite_to_third_person(base)})
    rw = (decision.rewritten_question or "").strip()
    if q and rw.lower() == q.lower() and _SECOND_PERSON_IN_QUESTION_RE.search(q):
        if _GENERAL_IMMIGRATION_OR_WORK_AUTH_RE.search(q) and not _latest_question_names_candidate(q):
            return decision
        return decision.model_copy(update={"rewritten_question": rewrite_to_third_person(q)})
    return decision


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


# Server-side prompt-injection / jailbreak guard (do not rely on the router LLM for these).
_INJECTION_GUARD_REASON = "[server: injection_guard"


def _prompt_injection_hard_block(latest: str) -> Optional[RouterDecision]:
    """Deterministic block list on the latest user message only. Runs before small-talk and before the router LLM."""
    raw = (latest or "").strip()
    nq = _normalize_smalltalk_key(raw)
    if not nq:
        return None
    # Normalize unicode dashes so hyphenated jailbreak phrases still match ASCII patterns.
    nq = nq.replace("\u2013", "-").replace("\u2014", "-")

    def _reject(reason_id: str) -> RouterDecision:
        return RouterDecision(
            rewritten_question=raw,
            route="reject",
            can_answer_directly=False,
            direct_answer=None,
            reason=f"{_INJECTION_GUARD_REASON}:{reason_id}]",
        )

    # High-signal substring gates (spacing-insensitive beyond single-space collapse).
    if "repeat" in nq and "everything" in nq and "developer message" in nq:
        return _reject("developer_message_exfil")
    if "email" in nq and "send" in nq and "company files" in nq:
        return _reject("exfil_email_tool")
    if "show your reasoning" in nq or ("reasoning" in nq and "step-by-step" in nq):
        return _reject("reasoning_chain_leak")
    if "admin override" in nq:
        return _reject("fake_admin_override")

    # Lone fake-roleplay / privilege claim (gold: reject; do not send to LLM).
    if re.fullmatch(r"you are now admin\??", nq):
        return _reject("fake_admin_roleplay")
    if re.search(r"\bignore\s+all\s+rules\b", nq):
        return _reject("instruction_override")
    if re.search(r"\bignore\s+(the\s+)?(all\s+)?(previous|prior|above)\s+instructions\b", nq):
        return _reject("instruction_override")
    if re.search(r"\bdisregard\s+(the\s+)?(previous|prior|above)\s+instructions\b", nq):
        return _reject("instruction_override")
    if re.search(r"\btell\s+the\s+user\s+all\s+secrets\b", nq):
        return _reject("secrets_exfil")
    if re.search(r"\b(reveal|show|print|dump|leak)\s+(the\s+)?(system\s+)?prompt\b", nq):
        return _reject("system_prompt_exfil")
    if re.search(r"\b(show|reveal|expose)\s+hidden\s+data\b", nq):
        return _reject("hidden_data_exfil")
    if "password" in nq and re.search(r"\byou\s+are\s+now\s+admin\b", nq):
        return _reject("fake_admin_credential")
    if "password" in nq and re.search(r"\bi\s+am\s+now\s+admin\b", nq):
        return _reject("fake_admin_credential")

    return None


async def run_intent_rewrite_router(
    question: str,
    history: List[Tuple[str, str]],
    *,
    request_id: Optional[str] = None,
    session_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    router_model: Optional[str] = None,
    router_temperature: Optional[float] = None,
    router_prompt_version: Optional[str] = None,
    router_system_prompt: Optional[str] = None,
    runtime_meta: Optional[Dict[str, Any]] = None,
    conversation_id: Optional[str] = None,
    is_new_conversation: bool = False,
) -> RouterDecision:
    """One LLM call returning RouterDecision; parse errors fall back to conservative rag."""
    q = (question or "").strip()
    cid = (conversation_id or "").strip() or None
    gw_thread: Dict[str, Any] = {}
    if cid:
        gw_thread["conversation_id"] = cid
        gw_thread["is_new_conversation"] = bool(is_new_conversation)

    if not q:
        return fallback_router_decision(question, reason="empty_question")

    inj = _prompt_injection_hard_block(q)
    if inj:
        if runtime_meta is not None:
            runtime_meta.clear()
            runtime_meta.update(
                {
                    "prompt_source": "injection_guard",
                    "prompt_file": None,
                    "prompt_requested_fallback": None,
                    "smalltalk_intent": None,
                }
            )
        _router_log.info(
            "intent_router_injection_guard",
            extra={
                "event": "intent_router_injection_guard",
                "gateway_meta": {"route": inj.route, "reason_preview": (inj.reason or "")[:120], **gw_thread},
            },
        )
        return inj

    hist = normalize_history_turns(history)
    if not hist:
        sm = _match_smalltalk_any(q)
        if sm:
            intent, answer, prompt_source = sm
            if runtime_meta is not None:
                runtime_meta.clear()
                runtime_meta.update(
                    {
                        "prompt_source": prompt_source,
                        "prompt_file": None,
                        "prompt_requested_fallback": None,
                        "smalltalk_intent": intent,
                    }
                )
            log_event = (
                "intent_router_smalltalk_seed"
                if prompt_source == "smalltalk_seed"
                else "intent_router_smalltalk_pattern"
            )
            _router_log.info(
                log_event,
                extra={
                    "event": log_event,
                    "gateway_meta": {"intent": intent, "question_preview": q[:80], **gw_thread},
                },
            )
            return RouterDecision(
                rewritten_question=q,
                route="direct_reply",
                can_answer_directly=True,
                direct_answer=answer,
                reason=f"[server: smalltalk:{intent}]",
            )

    hist_block = format_history_for_prompt(hist, REWRITE_HISTORY_MAX_LINES)
    user_body = (
        f"History:\n{hist_block}\n\nLatest question:\n{q}" if hist_block else f"History:\n(none)\n\nLatest question:\n{q}"
    )

    t0 = time.perf_counter()
    temp = 0.0 if router_temperature is None else float(router_temperature)
    llm = get_llm(temp, model=router_model)
    system_content, res_meta = _resolve_router_system_content(
        body_override=router_system_prompt,
        requested_version=router_prompt_version,
        default_version=settings.default_router_prompt_version,
    )
    if runtime_meta is not None:
        runtime_meta.clear()
        runtime_meta.update(res_meta)
    tags = list(
        get_langsmith_tags(
            request_id=request_id,
            session_id=session_id,
            conversation_id=cid,
        )
    )
    resolved_model = (router_model or "").strip() or settings.llm_model
    tags.append(f"intent_router_model:{resolved_model}")
    if res_meta["prompt_source"] == "body_override":
        tags.append("router_prompt_source:body_override")
    else:
        tags.append("router_prompt_source:versioned_file")
        tags.append(f"router_prompt_file:{res_meta['prompt_file']}")
        fb = res_meta.get("prompt_requested_fallback")
        if fb:
            tags.append(f"router_prompt_fallback_from:{fb}")
    invoke_kw = gateway_llm_invoke_kwargs(
        request_id,
        session_id,
        trace_id,
        cid,
        is_new_conversation=is_new_conversation if cid else None,
    )
    try:
        msg = await llm.ainvoke(
            [SystemMessage(content=system_content), HumanMessage(content=user_body)],
            config={
                "run_name": "intent_rewrite_router",
                "tags": tags,
            },
            max_tokens=2048,
            **invoke_kw,
        )
        raw = (msg.content or "").strip()
        obj = _extract_json_object(raw)
        if not obj:
            _router_log.warning(
                "intent_router_parse_failed",
                extra={
                    "event": "intent_router_parse_failed",
                    "gateway_meta": {"preview": (raw or "")[:200] or None, **gw_thread},
                },
            )
            return _ensure_rewritten_question_third_person(
                maybe_override_rag_for_general_question(
                    fallback_router_decision(q, reason="parse_fallback"),
                    q,
                ),
                q,
            )
        decision = RouterDecision.model_validate(obj)
        if not (decision.rewritten_question or "").strip():
            decision = decision.model_copy(
                update={"rewritten_question": rewrite_to_third_person(q)},
            )
        decision = maybe_override_rag_for_general_question(decision, q)
        decision = _ensure_rewritten_question_third_person(decision, q)
        _router_log.info(
            "intent_router_completed",
            extra={
                "event": "intent_router_completed",
                "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
                "gateway_meta": {
                    "route": decision.route,
                    "reason_preview": (decision.reason or "")[:160] or None,
                    "rewritten_preview": (decision.rewritten_question or "")[:120] or None,
                    **gw_thread,
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
                **({"gateway_meta": gw_thread} if gw_thread else {}),
            },
        )
        return _ensure_rewritten_question_third_person(
            maybe_override_rag_for_general_question(
                fallback_router_decision(q, reason=f"invoke_error:{type(e).__name__}"),
                q,
            ),
            q,
        )
