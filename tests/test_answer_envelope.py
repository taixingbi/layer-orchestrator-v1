"""Answer envelope (meta / answer / latency_ms / usage / status)."""

from app.observability.usage import USAGE_KEY_RAG, build_usage_payload
from app.schemas.answer_envelope import (
    LATENCY_KEY_RAG,
    build_answer_envelope,
    route_meta_from_detail,
    route_source_after_normalize,
)
from app.schemas.route import InternalIntentRoute, ToolRoute


def test_route_meta_user_profile():
    detail = ToolRoute(name="user_profile", confidence=0.95, reason="kb")
    route, tool = route_meta_from_detail(detail)
    assert route["type"] == "tool"
    assert route["tool"] == "user_profile"
    assert tool["name"] == "user_profile"
    assert tool["type"] == "rag"
    assert tool["key"] == "tool_rag"


def test_route_meta_github_search():
    detail = ToolRoute(name="github_search", confidence=0.99, reason="deterministic")
    route, tool = route_meta_from_detail(detail)
    assert route["tool"] == "github_search"
    assert tool["name"] == "github_search"
    assert tool["type"] == "github"
    assert tool["key"] == "tool_github_search"


def test_route_source_after_normalize():
    assert route_source_after_normalize(pre_deterministic=True, prompt_source=None, reason="") == "deterministic_rule"
    assert (
        route_source_after_normalize(
            pre_deterministic=False,
            prompt_source="versioned_file",
            reason="x [server: github_repo_keyword→tool]",
        )
        == "override_rule"
    )
    assert route_source_after_normalize(pre_deterministic=False, prompt_source="smalltalk_seed", reason="") == "smalltalk_seed"


def test_route_meta_internal_intent_omits_tool():
    detail = InternalIntentRoute(name="help", confidence=1.0, reason="meta question")
    route, tool = route_meta_from_detail(detail, source="llm_router")
    assert route["type"] == "internal_intent"
    assert route["intent"] == "help"
    assert "tool" not in route
    assert route["source"] == "llm_router"
    assert tool is None


def test_build_answer_envelope_shape():
    upstream_usage = {
        "chat": {"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11},
        "total": {"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11},
    }
    usage = build_usage_payload(
        intent_router={"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        tool_rag=upstream_usage,
    )
    detail = ToolRoute(name="user_profile", confidence=1.0)
    out = build_answer_envelope(
        request_id="req-1",
        session_id="s1",
        trace_id="req-1",
        conversation_id="conv-1",
        is_new_conversation=False,
        route_detail=detail,
        rewrite="rewritten",
        answer_text="hello",
        citations=[{"cite_id": 1}],
        follow_up_questions=["q?"],
        latency_ms={"intent_router": {"total": 100}, LATENCY_KEY_RAG: {"total": 200}, "total": 300},
        usage=usage,
        rag_user={"user_id": "u1", "user_roles": "r"},
        ok=True,
    )
    assert out["meta"]["request_id"] == "req-1"
    assert out["meta"]["user"]["id"] == "u1"
    assert out["meta"]["route"]["tool"] == "user_profile"
    assert out["meta"]["tool"]["name"] == "user_profile"
    assert out["meta"]["rewrite"] == "rewritten"
    assert out["answer"]["text"] == "hello"
    assert out["answer"]["citations"][0]["cite_id"] == 1
    assert out["usage"]["total"]["total_tokens"] == 17
    assert out["usage"][USAGE_KEY_RAG] is upstream_usage
    assert out["status"]["ok"] is True
    assert out["status"]["state"] == "completed"
    assert out["status"]["code"] == "ok"
    assert "prompt_tokens" not in out["usage"] or out["usage"].get("prompt_tokens") is None
