"""Capabilities intent."""

import re

CAPABILITIES_ANSWER = (
    "I can route questions about Taixing Bi and your materials to search-backed answers, "
    "answer general topics when appropriate, search huntAi GitHub repositories, and look up "
    "public web information when needed."
)

_CAP_PATTERNS = (
    re.compile(r"^what can you do\??$", re.I),
    re.compile(r"^what do you do\??$", re.I),
    re.compile(r"^what can you help with\??$", re.I),
    re.compile(r"^what are your capabilities\??$", re.I),
)


def _normalize(q: str) -> str:
    return " ".join((q or "").strip().lower().split())


def match_capabilities(question: str) -> bool:
    nq = _normalize(question)
    if not nq:
        return False
    return any(p.match(nq) for p in _CAP_PATTERNS)
