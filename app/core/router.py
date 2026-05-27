"""Router integration: canonical RouterDecision + envelope route_detail conversion."""

from __future__ import annotations

from typing import List, Optional, Tuple

from .github_route import match_github_search
from .intent_router import (
    RouterDecision,
    normalize_post_router,
    run_intent_rewrite_router,
)
from ..intents.registry import match_internal_intent
from ..schemas.route import RouteDetail, canonical_to_route_detail

__all__ = [
    "RouterDecision",
    "normalize_post_router",
    "run_intent_rewrite_router",
    "match_internal_intent",
    "decision_to_route_detail",
    "resolve_route",
    "match_github_search",
]


def decision_to_route_detail(decision: RouterDecision) -> RouteDetail:
    """Derive nested route_detail from canonical decision.route (envelope boundary)."""
    route = (decision.route or "rag_private_kb").strip().lower()
    conf = float(decision.confidence) if decision.confidence is not None else 1.0
    return canonical_to_route_detail(
        route,
        confidence=conf,
        reason=decision.reason or "",
        repo=decision.repo,
    )


def resolve_route(
    question: str,
    history: List[Tuple[str, str]],
) -> Optional[Tuple[RouteDetail, str, str]]:
    """Deterministic routes before LLM: internal intents, then github repo search."""
    hit = match_internal_intent(question)
    if hit:
        detail, answer = hit
        rewrite = (question or "").strip()
        return detail, answer, rewrite

    github = match_github_search(question)
    if github is not None:
        rewrite = (question or "").strip()
        return github, "", rewrite

    return None
