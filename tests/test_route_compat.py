"""Route detail ↔ canonical route mapping."""

from app.schemas.route import (
    CANONICAL_ROUTES,
    InternalIntentRoute,
    ToolRoute,
    canonical_from_route_detail,
    canonical_to_route_detail,
    legacy_route_from_detail,
    normalize_legacy_route_to_canonical,
    route_detail_from_legacy,
    route_detail_to_dict,
    routes_equivalent,
)


def test_legacy_route_internal_intent():
    detail = InternalIntentRoute(name="identity", confidence=0.99, reason="test")
    assert legacy_route_from_detail(detail) == "direct_reply"
    assert canonical_from_route_detail(detail) == "identity"


def test_legacy_route_rag_private_kb():
    detail = ToolRoute(name="rag_private_kb", confidence=1.0, reason="kb")
    assert legacy_route_from_detail(detail) == "tool"
    assert canonical_from_route_detail(detail) == "rag_private_kb"


def test_canonical_to_route_detail():
    detail = canonical_to_route_detail("github_search", confidence=0.9, reason="gh", repo="org/repo")
    assert isinstance(detail, ToolRoute)
    assert detail.name == "github_search"
    assert detail.repo == "org/repo"


def test_normalize_legacy_rag():
    assert normalize_legacy_route_to_canonical("rag") == "rag_private_kb"
    assert normalize_legacy_route_to_canonical("tool", {"type": "tool", "name": "rag_private_kb"}) == "rag_private_kb"


def test_routes_equivalent_gold_alias():
    assert routes_equivalent("rag", "rag_private_kb")
    assert routes_equivalent("rag_private_kb", "rag_private_kb")
    assert not routes_equivalent("github_search", "rag_private_kb")


def test_eval_payload_route_match_canonical():
    from app.api.routes import _router_eval_payload
    from app.core.intent_router import RouterDecision

    decision = RouterDecision(
        rewritten_question="What is Taixing Bi's current role?",
        route="rag_private_kb",
        confidence=0.98,
        source="llm_router",
        static_answer=None,
        reason="kb",
    )
    evaluation = _router_eval_payload(
        decision,
        question="What is Taixing Bi's current role?",
        history=[],
        expected_route="rag_private_kb",
    )
    assert evaluation["actual_route"] == "rag_private_kb"
    assert evaluation["route_match"] is True
    assert evaluation["checks"]["route_match"] is True
