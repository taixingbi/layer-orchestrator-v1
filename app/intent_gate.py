"""IntentGate: agent-based smalltalk detection → free reply."""
from typing import Optional

from .config import gateway_llm_invoke_kwargs, get_langsmith_tags, get_llm

INTENT_GATE_PROMPT = """You are an intent classifier. Reply with YES or NO on the first line.
If YES (message is only smalltalk/greeting with no real question), add a second line: a brief friendly first-person reply as Taixing Bi. Use this line: "Feel free to ask me about my experience, visa status, skills, or background!" (you may add a short greeting before it if you like).

YES = smalltalk/greeting only, with no real question (hi, hello, hey, how are you, what's up, good morning).
NO = asks for specific info, or a real request, or is mixed (e.g. greeting + question like "hi, what's your visa?"). If the message mixes smalltalk with any real question, reply NO.

User message:
"""


async def get_canned_answer(
    query: str,
    *,
    request_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Optional[str]:
    """If the agent classifies query as smalltalk, return its free reply; else None."""
    if not query or not query.strip():
        return None
    llm = get_llm()
    invoke_kw = gateway_llm_invoke_kwargs(request_id, session_id)
    resp = await llm.ainvoke(
        INTENT_GATE_PROMPT + query.strip(),
        config={
            "run_name": "intent_gate",
            "tags": get_langsmith_tags(request_id=request_id, session_id=session_id),
        },
        **invoke_kw,
    )
    text = (resp.content or "").strip()
    if text.upper().startswith("YES"):
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        reply = lines[1] if len(lines) > 1 else None
        return reply if reply else None
    return None
