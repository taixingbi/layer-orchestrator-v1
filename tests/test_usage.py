"""Unit tests for usage normalization and RAG SSE parsing."""

from app.clients.rag_http import _parse_sse_response_text
from app.observability.usage import (
    USAGE_KEY_GITHUB_SEARCH,
    USAGE_KEY_RAG,
    build_usage_payload,
    usage_from_rag_json,
)


def test_usage_from_rag_json_passthrough():
    upstream = {
        "usage": {
            "chat": {"prompt_tokens": 886, "completion_tokens": 31, "total_tokens": 917},
            "follow_up_chat": {"prompt_tokens": 277, "completion_tokens": 73, "total_tokens": 350},
            "total": {"prompt_tokens": 1163, "completion_tokens": 104, "total_tokens": 1267},
        }
    }
    detail = usage_from_rag_json(upstream)
    assert detail is upstream["usage"]
    assert detail["total"]["prompt_tokens"] == 1163


def test_build_usage_payload_merges_router_and_tool_rag():
    upstream = {
        "chat": {"prompt_tokens": 886, "completion_tokens": 31, "total_tokens": 917},
        "total": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110},
    }
    payload = build_usage_payload(
        intent_router={"prompt_tokens": 50, "completion_tokens": 5, "total_tokens": 55},
        tool_rag=upstream,
    )
    assert payload["prompt_tokens"] == 150
    assert payload["total_tokens"] == 165
    assert payload["intent_router"]["prompt_tokens"] == 50
    assert payload[USAGE_KEY_RAG] is upstream
    assert "rag" not in payload


def test_build_usage_payload_github_passthrough():
    upstream = {
        "github_search": {"prompt_tokens": 200, "completion_tokens": 20, "total_tokens": 220},
        "chat": {"prompt_tokens": 800, "completion_tokens": 80, "total_tokens": 880},
        "total": {"prompt_tokens": 1000, "completion_tokens": 100, "total_tokens": 1100},
    }
    payload = build_usage_payload(
        intent_router={"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11},
        tool_github_search=upstream,
    )
    assert payload["total_tokens"] == 1111
    assert payload[USAGE_KEY_GITHUB_SEARCH] is upstream


def test_parse_sse_response_text_usage_and_answer():
    sse = """event: answer_delta
data: {"text": "Hello"}

event: usage
data: {"total": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}}

event: done
data: {}
"""
    parsed = _parse_sse_response_text(sse)
    assert parsed["answer"] == "Hello"
    assert parsed["usage"]["total"]["prompt_tokens"] == 1
