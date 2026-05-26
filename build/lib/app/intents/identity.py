"""Assistant identity intent."""

import re

IDENTITY_ANSWER = "I'm HuntAI, your personal AI assistant for Taixing Bi."

_IDENTITY_PATTERNS = (
    re.compile(r"^what(?:'s| is) your name\??$", re.I),
    re.compile(r"^who are you\??$", re.I),
    re.compile(r"^what are you\??$", re.I),
    re.compile(r"^tell me who you are\??$", re.I),
    re.compile(r"^(?:can you |could you |please )?introduce yourself\??$", re.I),
    re.compile(r"^tell me about yourself\??$", re.I),
)


def _normalize(q: str) -> str:
    return " ".join((q or "").strip().lower().split())


def match_identity(question: str) -> bool:
    nq = _normalize(question)
    if not nq:
        return False
    return any(p.match(nq) for p in _IDENTITY_PATTERNS)
