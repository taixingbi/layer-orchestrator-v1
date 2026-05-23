"""Internal intent registry: deterministic match before LLM router."""

from typing import Optional, Tuple

from ..schemas.route import InternalIntentRoute, RouteDetail
from .capabilities import CAPABILITIES_ANSWER, match_capabilities
from .greeting import match_greeting
from .help import HELP_ANSWER, match_help
from .identity import IDENTITY_ANSWER, match_identity


def resolve_intent_answer(name: str) -> str:
    answers = {
        "identity": IDENTITY_ANSWER,
        "help": HELP_ANSWER,
        "capabilities": CAPABILITIES_ANSWER,
    }
    return answers.get(name, "")


def match_internal_intent(question: str) -> Optional[Tuple[RouteDetail, str]]:
    """Return (route_detail, answer_text) when a deterministic intent matches."""
    if match_identity(question):
        return (
            InternalIntentRoute(
                name="identity",
                confidence=0.99,
                reason="User asks assistant identity",
            ),
            IDENTITY_ANSWER,
        )
    greeting = match_greeting(question)
    if greeting:
        intent_name, answer = greeting
        return (
            InternalIntentRoute(
                name="greeting",
                confidence=0.99,
                reason=f"Matched greeting intent {intent_name}",
            ),
            answer,
        )
    if match_help(question):
        return (
            InternalIntentRoute(name="help", confidence=0.99, reason="User asks for help"),
            HELP_ANSWER,
        )
    if match_capabilities(question):
        return (
            InternalIntentRoute(
                name="capabilities",
                confidence=0.99,
                reason="User asks about capabilities",
            ),
            CAPABILITIES_ANSWER,
        )
    return None
