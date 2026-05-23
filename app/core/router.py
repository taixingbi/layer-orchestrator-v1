"""Router integration: legacy RouterDecision + route_detail conversion."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .intent_router import (
    RouterDecision,
    normalize_post_router,
    run_intent_rewrite_router,
)
from ..intents.registry import match_internal_intent
from ..schemas.route import (
    InternalIntentRoute,
    RouteDetail,
    ToolRoute,
    legacy_route_from_detail,
    parse_route_detail,
    route_detail_to_dict,
)

__all__ = [
    "RouterDecision",
    "normalize_post_router",
    "run_intent_rewrite_router",
    "match_internal_intent",
    "decision_to_route_detail",
    "resolve_route",
]


def decision_to_route_detail(decision: RouterDecision) -> RouteDetail:
    """Convert legacy RouterDecision to nested route_detail."""
    raw = getattr(decision, "route_detail", None)
    parsed = parse_route_detail(raw)
    if parsed is not None:
        return parsed
    route = (decision.route or "rag").strip().lower()
    reason = decision.reason or ""
    if route == "rag":
        return ToolRoute(name="user_profile", confidence=1.0, reason=reason)
    if route == "tool":
        return ToolRoute(name="github_repo_search", confidence=1.0, reason=reason)
    if route == "clarify":
        return InternalIntentRoute(name="clarify", confidence=1.0, reason=reason)
    if route == "reject":
        return InternalIntentRoute(name="reject", confidence=1.0, reason=reason)
    return InternalIntentRoute(name="help", confidence=1.0, reason=reason or "direct_reply")


def resolve_route(
    question: str,
    history: List[Tuple[str, str]],
) -> Optional[Tuple[RouteDetail, str, str]]:
    """Deterministic internal intent before LLM. Returns (route_detail, answer, rewrite) or None."""
    hit = match_internal_intent(question)
    if not hit:
        return None
    detail, answer = hit
    rewrite = (question or "").strip()
    return detail, answer, rewrite
