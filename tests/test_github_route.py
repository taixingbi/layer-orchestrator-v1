"""Deterministic github_search routing."""

from app.core.github_route import match_github_search
from app.core.intent_router import RouterDecision, maybe_override_for_github_search


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
        route="rag_private_kb",
        confidence=0.9,
        reason="kb",
    )
    out = maybe_override_for_github_search(decision, "in HuntAI, how to design gateway?")
    assert out.route == "github_search"
    assert "github_repo_keyword" in (out.reason or "")


def test_empty_question_fallback_clarify():
    import asyncio

    from app.core.intent_router import run_intent_rewrite_router

    decision = asyncio.run(run_intent_rewrite_router("", []))
    assert decision.route == "clarify"
    assert decision.source == "fallback"
