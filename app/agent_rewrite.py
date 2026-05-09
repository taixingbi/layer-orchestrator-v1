"""EntityRewrite: Taixing third-person + LLM rewrite for retrieval."""
import logging
import re
import time
from typing import List, Optional, Tuple

from langchain_core.messages import HumanMessage, SystemMessage

from .config import gateway_llm_invoke_kwargs, get_langsmith_tags, get_llm

CANDIDATE_NAME = "Taixing Bi"
HISTORY_CAP = 20
REWRITE_HISTORY_MAX_LINES = 6
ANSWER_HISTORY_MAX_LINES = 4

_rewrite_log = logging.getLogger("layer_orchestrator.agent_rewrite")

_REWRITE_CONTEXT_SYSTEM = """Rewrite the user's latest question into a standalone search query.
Use conversation history only to resolve references.
Do not answer the question.
Do not add facts that are not implied by the conversation.
Return only the rewritten question."""

def rewrite_to_third_person(question: str) -> str:
    """Rewrite second-person references (you, your, etc.) to third person (candidate name)."""
    q = question
    # Order matters: longer/phrase patterns before "you" so e.g. "your" → "Taixing Bi's", "are you" → "is Taixing Bi"
    replacements = [
        (r"\byour\b", f"{CANDIDATE_NAME}'s"),
        (r"\byourself\b", CANDIDATE_NAME),
        (r"\bare you\b", f"is {CANDIDATE_NAME}"),
        (r"\bdo you\b", f"does {CANDIDATE_NAME}"),
        (r"\bhave you\b", f"has {CANDIDATE_NAME}"),
        (r"\bcan you\b", f"can {CANDIDATE_NAME}"),
        (r"\byou\b", CANDIDATE_NAME),
    ]
    for pattern, repl in replacements:
        q = re.sub(pattern, repl, q, flags=re.IGNORECASE)
    return q


def normalize_history_turns(turns: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    """Strip contents and cap length (last HISTORY_CAP turns)."""
    out: List[Tuple[str, str]] = []
    for role, content in turns:
        r = (role or "").strip().lower()
        c = (content or "").strip()
        if r not in ("user", "assistant") or not c:
            continue
        out.append((r, c))
    return out[-HISTORY_CAP:]


def format_history_for_prompt(turns: List[Tuple[str, str]], max_turns: int) -> str:
    """Format turns as User:/Assistant: lines (last max_turns only)."""
    chunk = turns[-max_turns:] if max_turns > 0 else turns
    lines: List[str] = []
    for role, content in chunk:
        label = "User" if role == "user" else "Assistant"
        lines.append(f"{label}: {content}")
    return "\n".join(lines)


def history_snippet_for_answer(
    history: List[Tuple[str, str]],
    current_question_raw: str,
    max_turns: int = ANSWER_HISTORY_MAX_LINES,
) -> str:
    """Short transcript for the final answer prompt (prior turns + current user message)."""
    if not history and not (current_question_raw or "").strip():
        return ""
    turns = list(history) + [("user", (current_question_raw or "").strip())]
    return format_history_for_prompt(turns, max_turns)


async def rewrite_query_with_context(
    current_question: str,
    history: List[Tuple[str, str]],
    *,
    request_id: Optional[str] = None,
    session_id: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> str:
    """Standalone retrieval query using optional prior turns + latest question (after third-person pass)."""
    if not current_question or not current_question.strip():
        return current_question
    t0 = time.perf_counter()
    hist = normalize_history_turns(history)
    cq = rewrite_to_third_person(current_question.strip())
    hist_block = format_history_for_prompt(hist, REWRITE_HISTORY_MAX_LINES)
    if hist_block:
        user_body = f"Conversation history:\n{hist_block}\n\nLatest question:\n{cq}"
    else:
        user_body = f"Latest question:\n{cq}"
    _rewrite_log.debug(
        "rewrite_invoke_started",
        extra={
            "event": "rewrite_invoke_started",
            "gateway_meta": {"query_len": len(current_question or ""), "history_turns": len(hist)},
        },
    )
    llm = get_llm()
    invoke_kw = gateway_llm_invoke_kwargs(request_id, session_id, trace_id)
    msg = await llm.ainvoke(
        [SystemMessage(content=_REWRITE_CONTEXT_SYSTEM), HumanMessage(content=user_body)],
        config={
            "run_name": "agent_rewrite",
            "tags": get_langsmith_tags(request_id=request_id, session_id=session_id),
        },
        max_tokens=100,
        **invoke_kw,
    )
    rewritten = (msg.content or "").strip()
    _rewrite_log.debug(
        "rewrite_invoke_completed",
        extra={
            "event": "rewrite_invoke_completed",
            "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
            "gateway_meta": {
                "rewritten_len": len(rewritten or ""),
                "rewritten_preview": (rewritten or "")[:120] or None,
            },
        },
    )
    return rewritten if rewritten else cq


async def rewrite_query(
    query: str,
    *,
    request_id: Optional[str] = None,
    session_id: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> str:
    """EntityRewrite without prior history (backward-compatible entrypoint)."""
    return await rewrite_query_with_context(
        query,
        [],
        request_id=request_id,
        session_id=session_id,
        trace_id=trace_id,
    )
