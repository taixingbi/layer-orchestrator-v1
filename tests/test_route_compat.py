"""Route detail ↔ legacy flat route mapping."""

from app.schemas.route import (
    InternalIntentRoute,
    ToolRoute,
    legacy_route_from_detail,
    route_detail_from_legacy,
    route_detail_to_dict,
    routes_equivalent,
)


def test_legacy_route_internal_intent():
    detail = InternalIntentRoute(name="identity", confidence=0.99, reason="test")
    assert legacy_route_from_detail(detail) == "direct_reply"


def test_legacy_route_rag_private_kb():
    detail = ToolRoute(name="rag_private_kb", confidence=1.0, reason="kb")
    assert legacy_route_from_detail(detail) == "tool"


def test_legacy_route_github():
    detail = ToolRoute(name="github_search", repo="layer-orchestrator-v1", confidence=0.9)
    assert legacy_route_from_detail(detail) == "tool"


def test_route_detail_from_legacy_rag():
    detail = route_detail_from_legacy("rag")
    assert isinstance(detail, ToolRoute)
    assert detail.name == "rag_private_kb"


def test_route_detail_to_dict():
    detail = ToolRoute(name="web_search", confidence=0.8, reason="news")
    d = route_detail_to_dict(detail)
    assert d["type"] == "tool"
    assert d["name"] == "web_search"


def test_routes_equivalent_rag_alias():
    detail = ToolRoute(name="rag_private_kb", confidence=1.0, reason="kb")
    assert routes_equivalent("rag", "tool", detail)
    assert not routes_equivalent("tool", "direct_reply", detail)


def test_eval_payload_route_match_uses_rag_alias():
    from app.api.routes import _router_eval_payload
    from app.core.intent_router import RouterDecision

    decision = RouterDecision(
        rewritten_question="What is Taixing Bi's current role?",
        route="tool",
        route_detail={"type": "tool", "name": "rag_private_kb", "confidence": 1.0, "reason": "kb"},
        can_answer_directly=False,
        direct_answer=None,
        reason="kb",
    )
    evaluation = _router_eval_payload(
        decision,
        question="What is Taixing Bi's current role?",
        history=[],
        expected_route="rag",
    )
    assert evaluation["actual_route"] == "tool"
    assert evaluation["route_match"] is True
    assert evaluation["checks"]["route_match"] is True
