"""EntityRewrite: Taixing third-person + LLM rewrite for retrieval."""
import logging
import re
import time
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage

from .config import gateway_llm_invoke_kwargs, get_langsmith_tags, get_llm

CANDIDATE_NAME = "Taixing Bi"
_rewrite_log = logging.getLogger("layer_orchestrator.agent_rewrite")


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


_SYSTEM = """Rewrite the user's question to be clearer and more specific for retrieval.
Keep it concise. Return only the rewritten question, nothing else."""


async def rewrite_query(
    query: str,
    *,
    request_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> str:
    """EntityRewrite: third-person (Taixing) + LLM rewrite for retrieval. Call after IntentGate (no smalltalk)."""
    if not query or not query.strip():
        return query
    t0 = time.perf_counter()
    _rewrite_log.debug(
        "rewrite_invoke_started",
        extra={"event": "rewrite_invoke_started", "gateway_meta": {"query_len": len(query or "")}},
    )
    query = rewrite_to_third_person(query)
    llm = get_llm()
    invoke_kw = gateway_llm_invoke_kwargs(request_id, session_id)
    msg = await llm.ainvoke(
        [SystemMessage(content=_SYSTEM), HumanMessage(content=query)],
        config={
            "run_name": "agent_rewrite",
            "tags": get_langsmith_tags(request_id=request_id, session_id=session_id),
        },
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
    return rewritten if rewritten else query
