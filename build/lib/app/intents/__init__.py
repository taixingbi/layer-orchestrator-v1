"""Internal intent handlers (deterministic answers, no downstream calls)."""

from .identity import IDENTITY_ANSWER, match_identity
from .greeting import match_greeting
from .help import HELP_ANSWER, match_help
from .capabilities import CAPABILITIES_ANSWER, match_capabilities
from .registry import match_internal_intent, resolve_intent_answer

__all__ = [
    "IDENTITY_ANSWER",
    "HELP_ANSWER",
    "CAPABILITIES_ANSWER",
    "match_identity",
    "match_greeting",
    "match_help",
    "match_capabilities",
    "match_internal_intent",
    "resolve_intent_answer",
]
