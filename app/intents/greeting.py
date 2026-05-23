"""Greeting intents (from smalltalk seed)."""

import json
import re
from pathlib import Path
from typing import Optional, Tuple

from ..core.rewrite import CANDIDATE_NAME

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_SEED_PATH = _PROMPTS_DIR / "smalltalk_examples.json"

_GREETING_INTENTS = frozenset(
    {
        "greeting_named",
        "greeting_hi",
        "greeting_hello_hey",
        "greeting_there",
        "greeting_time_of_day",
        "greeting_status",
    }
)

_GREETING_PATTERNS = (
    (re.compile(r"^(hi|hello|hey)( there)?[!?.]*$", re.I), "greeting_hello_hey"),
    (re.compile(r"^good (morning|afternoon|evening|day)[!?.]*$", re.I), "greeting_time_of_day"),
    (re.compile(r"^how are you\??$", re.I), "greeting_status"),
)


def _normalize(q: str) -> str:
    return " ".join((q or "").strip().lower().split())


def _load_seed() -> list:
    try:
        with open(_SEED_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return []


def _render_answer(template: str) -> str:
    return template.replace("__CANDIDATE_NAME__", CANDIDATE_NAME)


def match_greeting(question: str) -> Optional[Tuple[str, str]]:
    """Return (intent_name, answer) if question matches a greeting."""
    nq = _normalize(question)
    if not nq:
        return None
    for entry in _load_seed():
        intent = entry.get("intent") or ""
        if intent not in _GREETING_INTENTS:
            continue
        examples = entry.get("user_examples") or []
        norm_examples = {_normalize(str(x)) for x in examples}
        if nq in norm_examples:
            ans = _render_answer(str(entry.get("answer") or ""))
            return intent, ans
    for pattern, intent in _GREETING_PATTERNS:
        if pattern.match(nq):
            for entry in _load_seed():
                if entry.get("intent") == intent:
                    return intent, _render_answer(str(entry.get("answer") or ""))
            return intent, f"Hello! How can I help you today with questions about {CANDIDATE_NAME}?"
    return None
