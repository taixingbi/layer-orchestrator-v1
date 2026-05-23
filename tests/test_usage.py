"""Unit tests for usage normalization and RAG SSE parsing."""

from app.clients.rag_http import _parse_sse_response_text
from app.observability.usage import build_usage_payload, usage_from_rag_json


def test_usage_from_rag_json_nested():
    data = {
        "usage": {
            "chat": {"prompt_tokens": 886, "completion_tokens": 31, "total_tokens": 917},
            "follow_up_chat": {"prompt_tokens": 277, "completion_tokens": 73, "total_tokens": 350},
            "total": {"prompt_tokens": 1163, "completion_tokens": 104, "total_tokens": 1267},
        }
    }
    detail = usage_from_rag_json(data)
    assert detail is not None
    assert detail["prompt_tokens"] == 1163
    assert detail["chat"]["prompt_tokens"] == 886
    assert detail["follow_up_chat"]["total_tokens"] == 350


def test_build_usage_payload_merges_router_and_rag():
    rag = usage_from_rag_json(
        {
            "usage": {
                "total": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110},
            }
        }
    )
    payload = build_usage_payload(
        intent_router={"prompt_tokens": 50, "completion_tokens": 5, "total_tokens": 55},
        rag=rag,
    )
    assert payload["prompt_tokens"] == 150
    assert payload["total_tokens"] == 165
    assert payload["intent_router"]["prompt_tokens"] == 50
    assert payload["rag"]["prompt_tokens"] == 100


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
