"""Judge agent: evaluate answer quality; if not good, provide feedback for retry."""
from typing import Optional, Tuple

from .config import gateway_llm_invoke_kwargs, get_langsmith_tags, get_llm

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

async def evaluate_answer(
    question: str,
    answer: str,
    *,
    evidence: Optional[str] = None,
    request_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Tuple[bool, Optional[str]]:
    """Evaluate answer quality. Returns (passed, feedback). If passed, feedback is None.
    evidence: optional tool outputs, e.g. '[E1] ... [E2] ...' for citation checking."""
    if not answer or not answer.strip():
        return False, "Answer is empty."
    llm = get_llm()
    tags = get_langsmith_tags(request_id=request_id, session_id=session_id)
    invoke_kw = gateway_llm_invoke_kwargs(request_id, session_id)
    evidence_block = f"\n\nEvidence (tool outputs), numbered as [E1], [E2], ...:\n{evidence}" if evidence else "\n\nEvidence: (none)"
    resp = await llm.ainvoke(
        JUDGE_PROMPT + f"\nQuestion: {question}\n\nAnswer: {answer}" + evidence_block,
        config={"run_name": "Answer Judge", "tags": tags},
        **invoke_kw,
    )
    text = (resp.content or "").strip().upper()
    if text.startswith("GOOD"):
        return True, None
    if text.startswith("NOT_GOOD"):
        reason = text.split(":", 1)[-1].strip() if ":" in text else "Answer needs improvement."
        return False, reason
    return True, None  # default pass on parse failure
