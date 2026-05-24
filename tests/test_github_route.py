"""Deterministic github_repo_search routing."""

from app.core.github_route import match_github_repo_search
from app.core.intent_router import RouterDecision, maybe_override_for_github_repo
from app.core.router import resolve_route
from app.schemas.route import ToolRoute


def test_match_github_repo_search_huntai_gateway():
    hit = match_github_repo_search("in HuntAI, how to design gateway?")
    assert hit is not None
    assert hit.name == "github_repo_search"
    assert hit.confidence == 0.99


def test_match_github_repo_search_layer_orchestrator():
    hit = match_github_repo_search("why split orchestrator and gateway in layer-orchestrator-v1?")
    assert hit is not None
    assert hit.repo == "taixingbi/layer-orchestrator-v1"


def test_match_github_repo_search_negative_visa():
    assert match_github_repo_search("what is taixing visa status in us?") is None


def test_resolve_route_github_skips_llm_path():
    pre = resolve_route("in HuntAI, how to design gateway?", [])
    assert pre is not None
    detail, answer, rewrite = pre
    assert isinstance(detail, ToolRoute)
    assert detail.name == "github_repo_search"
    assert answer == ""
    assert "gateway" in rewrite.lower()


def test_maybe_override_rag_to_github():
    decision = RouterDecision(
        rewritten_question="huntai gateway design",
        route="rag",
        reason="llm chose rag",
    )
    out = maybe_override_for_github_repo(decision, "in HuntAI, how to design gateway?")
    assert out.route == "tool"
    assert out.route_detail["name"] == "github_repo_search"
    assert "github_repo_keyword" in (out.reason or "")
