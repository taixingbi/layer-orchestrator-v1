"""MCP SSE parsing fixtures from tmp.md examples."""

from app.tools.mcp_client import _accumulate_github_sse, _accumulate_progress_events


def test_accumulate_progress_rag_mcp_style():
    events = [
        {"type": "answer_delta", "text": "Hello "},
        {"type": "answer_delta", "text": "world"},
        {"type": "usage", "total": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}},
    ]
    merged = _accumulate_progress_events(events)
    assert merged["answer"] == "Hello world"
    assert merged["usage"]["total"]["prompt_tokens"] == 1


def test_accumulate_github_sse_delta_and_done():
    sse = """event: delta
data: {"text": "##"}

event: delta
data: {"text": " Title"}

event: done
data: {"ok": true, "answer": "## Title", "citations": []}
"""
    merged = _accumulate_github_sse(sse)
    assert merged.get("answer") == "## Title"
    assert merged.get("ok") is True
