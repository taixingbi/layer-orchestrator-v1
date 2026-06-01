"""Judge agent: evaluate answer quality; if not good, provide feedback for retry."""
import logging
import time
from typing import Optional, Tuple

from ..config import gateway_llm_invoke_kwargs, get_langsmith_tags, get_llm

JUDGE_PROMPT = """You are a strict judge.

You will be given:
- Question
- Answer
- Evidence (tool outputs), numbered as [E1], [E2], ...

Pass criteria:
1) The answer addresses the question.
2) If Evidence is non-empty, every key factual claim MUST be supported by at least one citation like [E1] or [E2].
3) The answer must NOT introduce facts that are not in Evidence.
4) If Evidence is insufficient, the answer must say so and limit itself to what Evidence supports.

Return ONLY one line:
- GOOD
- NOT_GOOD: <brief reason>
"""
_judge_log = logging.getLogger("layer_orchestrator.agent_judge")

async def evaluate_answer(
    question: str,
    answer: str,
    *,
    evidence: Optional[str] = None,
    request_id: Optional[str] = None,
    session_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    is_new_conversation: bool = False,
) -> Tuple[bool, Optional[str]]:
    """Evaluate answer quality. Returns (passed, feedback). If passed, feedback is None.
    evidence: optional tool outputs, e.g. '[E1] ... [E2] ...' for citation checking."""
    if not answer or not answer.strip():
        return False, "Answer is empty."
    t0 = time.perf_counter()
    _judge_log.debug(
        "judge_invoke_started",
        extra={
            "event": "judge_invoke_started",
            "gateway_meta": {
                "question_len": len(question or ""),
                "answer_len": len(answer or ""),
                "has_evidence": bool(evidence),
            },
        },
    )
    cid = (conversation_id or "").strip() or None
    # Uses LLM_MODEL via get_llm() default (not ROUTER_MODEL).
    llm = get_llm()
    tags = get_langsmith_tags(request_id=request_id, session_id=session_id, conversation_id=cid)
    invoke_kw = gateway_llm_invoke_kwargs(
        request_id,
        session_id,
        trace_id,
        cid,
        is_new_conversation=is_new_conversation if cid else None,
    )
    evidence_block = f"\n\nEvidence (tool outputs), numbered as [E1], [E2], ...:\n{evidence}" if evidence else "\n\nEvidence: (none)"
    resp = await llm.ainvoke(
        JUDGE_PROMPT + f"\nQuestion: {question}\n\nAnswer: {answer}" + evidence_block,
        config={"run_name": "Answer Judge", "tags": tags},
        **invoke_kw,
    )
    text = (resp.content or "").strip().upper()
    _judge_log.debug(
        "judge_invoke_completed",
        extra={
            "event": "judge_invoke_completed",
            "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
            "gateway_meta": {"result_preview": text[:120] or None},
        },
    )
    if text.startswith("GOOD"):
        _judge_log.debug("judge_parse_good", extra={"event": "judge_parse_good"})
        return True, None
    if text.startswith("NOT_GOOD"):
        reason = text.split(":", 1)[-1].strip() if ":" in text else "Answer needs improvement."
        _judge_log.debug(
            "judge_parse_not_good",
            extra={"event": "judge_parse_not_good", "gateway_meta": {"reason_preview": reason[:120] or None}},
        )
        return False, reason
    _judge_log.debug("judge_parse_fallback_pass", extra={"event": "judge_parse_fallback_pass"})
    return True, None  # default pass on parse failure
