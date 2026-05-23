"""Help / usage intent."""

import re

HELP_ANSWER = (
    "Ask about Taixing Bi's profile, visa status, work authorization, or your organization's "
    "materials. I can also answer general immigration concepts, search GitHub repos in the huntAi "
    "project, or look up current public information on the web when needed."
)

_HELP_PATTERNS = (
    re.compile(r"^help\??$", re.I),
    re.compile(r"^what should i ask( you)?\??$", re.I),
    re.compile(r"^what can i ask( you)?\??$", re.I),
    re.compile(r"^what questions can i ask( you)?\??$", re.I),
    re.compile(r"^how do i use (this|you)\??$", re.I),
)


def _normalize(q: str) -> str:
    return " ".join((q or "").strip().lower().split())


def match_help(question: str) -> bool:
    nq = _normalize(question)
    if not nq:
        return False
    return any(p.match(nq) for p in _HELP_PATTERNS)
