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


def test_legacy_route_user_profile():
    detail = ToolRoute(name="user_profile", confidence=1.0, reason="kb")
    assert legacy_route_from_detail(detail) == "tool"


def test_legacy_route_github():
    detail = ToolRoute(name="github_repo_search", repo="layer-orchestrator-v1", confidence=0.9)
    assert legacy_route_from_detail(detail) == "tool"


def test_route_detail_from_legacy_rag():
    detail = route_detail_from_legacy("rag")
    assert isinstance(detail, ToolRoute)
    assert detail.name == "user_profile"


def test_route_detail_to_dict():
    detail = ToolRoute(name="web_search", confidence=0.8, reason="news")
    d = route_detail_to_dict(detail)
    assert d["type"] == "tool"
    assert d["name"] == "web_search"


def test_routes_equivalent_rag_alias():
    detail = ToolRoute(name="user_profile", confidence=1.0, reason="kb")
    assert routes_equivalent("rag", "tool", detail)
    assert not routes_equivalent("tool", "direct_reply", detail)
