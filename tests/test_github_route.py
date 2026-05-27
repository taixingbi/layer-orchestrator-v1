"""Deterministic github_search routing."""

from app.core.github_route import match_github_search
from app.core.intent_router import RouterDecision, maybe_override_for_github_search
from app.schemas.route import ToolRoute, parse_route_detail


def test_match_github_search_huntai_gateway():
    hit = match_github_search("in HuntAI, how to design gateway?")
    assert hit is not None
    assert hit.name == "github_search"


def test_match_github_search_layer_orchestrator():
    hit = match_github_search("why split orchestrator and gateway in layer-orchestrator-v1?")
    assert hit is not None
    assert hit.repo == "taixingbi/layer-orchestrator-v1"


def test_match_github_search_negative_visa():
    assert match_github_search("what is taixing visa status in us?") is None


def test_override_forces_github_search():
    decision = RouterDecision(
        route="rag",
        route_detail=ToolRoute(name="user_profile", confidence=0.9).model_dump(),
    )
    detail = parse_route_detail(decision.route_detail)
    assert detail.name == "user_profile"
    out = maybe_override_for_github_search(decision, "in HuntAI, how to design gateway?")
    assert out.route == "tool"
    assert out.route_detail["name"] == "github_search"
    assert "github_repo_keyword" in (out.reason or "")


def test_parse_route_detail_rejects_github_repo_search():
    raw = {"type": "tool", "name": "github_repo_search", "confidence": 0.9}
    detail = parse_route_detail(raw)
    assert detail is None
