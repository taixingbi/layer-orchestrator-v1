"""MCP SSE parsing fixtures from tmp.md examples."""

import json

import pytest

from app.tools.mcp_client import (
    _accumulate_github_sse,
    _accumulate_progress_events,
    _parse_mcp_sse_lines,
)


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


@pytest.mark.asyncio
async def test_parse_mcp_sse_lines_streams_deltas():
    sse_lines = [
        "event: message",
        'data: {"params": {"message": "{\\"type\\": \\"answer_delta\\", \\"text\\": \\"Hi\\"}"}}',
        "",
        "event: message",
        'data: {"params": {"message": "{\\"type\\": \\"answer_delta\\", \\"text\\": \\" there\\"}"}}',
        "",
    ]
    deltas: list[str] = []

    async def _lines():
        for line in sse_lines:
            yield line

    result = await _parse_mcp_sse_lines(_lines(), on_delta=deltas.append)
    assert deltas == ["Hi", " there"]
    assert result.answer == "Hi there"


@pytest.mark.asyncio
async def test_parse_mcp_sse_github_done_latency_with_deltas():
    """GitHub MCP: answer from deltas, latency_ms only on done event."""
    sse_lines = [
        "event: delta",
        'data: {"text": "Repo overview"}',
        "",
        "event: done",
        'data: {"ok": true, "latency_ms": {"github_readme": 237, "github_search": 218, "chat": 3303, "follow_up_chat": 1081, "total": 4849}}',
        "",
    ]
    deltas: list[str] = []

    async def _lines():
        for line in sse_lines:
            yield line

    result = await _parse_mcp_sse_lines(_lines(), on_delta=deltas.append)
    assert deltas == ["Repo overview"]
    assert result.answer == "Repo overview"
    assert result.latency_ms == {
        "github_readme": 237,
        "github_search": 218,
        "chat": 3303,
        "follow_up_chat": 1081,
        "total": 4849,
    }


@pytest.mark.asyncio
async def test_tool_result_from_json_github_latency_passthrough():
    from app.tools.mcp_client import _tool_result_from_json_payload

    mcp_latency = {
        "github_readme": 286,
        "github_search": 117,
        "chat": 3435,
        "follow_up_chat": 1193,
        "total": 5062,
    }
    payload = {
        "result": {
            "content": [
                {
                    "text": json.dumps(
                        {
                            "ok": True,
                            "answer": "Repo overview",
                            "latency_ms": mcp_latency,
                        }
                    )
                }
            ]
        }
    }
    result = await _tool_result_from_json_payload(payload)
    assert result.answer == "Repo overview"
    assert result.latency_ms == mcp_latency


@pytest.mark.asyncio
async def test_github_repo_search_latency_end_to_end():
    """MCP SSE latency_ms → pipeline metadata → done summary github-search."""
    from app.core.sse import build_latency_ms_summary

    sse_lines = [
        "event: delta",
        'data: {"text": "Repo overview"}',
        "",
        "event: done",
        'data: {"ok": true, "latency_ms": {"github_readme": 286, "github_search": 117, "chat": 3435, "follow_up_chat": 1193, "total": 5062}}',
        "",
    ]

    async def _lines():
        for line in sse_lines:
            yield line

    tool_result = await _parse_mcp_sse_lines(_lines())
    assert tool_result.latency_ms is not None

    states = [
        {
            "phase": "intent_router",
            "status": "completed",
            "started_at": "2026-01-01T12:00:00Z",
            "ended_at": "2026-01-01T12:00:01.999Z",
            "latency_ms": 1999.91,
        },
        {
            "phase": "github-search",
            "status": "completed",
            "started_at": "2026-01-01T12:00:02.000Z",
            "ended_at": "2026-01-01T12:00:04.691Z",
            "latency_ms": 2691.0,
            "metadata": {
                "tool": "github_repo_search",
                "github_latency_ms": tool_result.latency_ms,
            },
        },
    ]
    out = build_latency_ms_summary(states)
    assert out["tool-github-search"] is tool_result.latency_ms
    assert out["tool-github-search"]["total"] == 5062
    assert out["intent_router"] == {"total": 1999.91}


def test_accumulate_progress_github_latency_phases():
    events = [
        {"type": "latency", "phase": "github_readme", "ms": 237},
        {"type": "latency", "phase": "github_search", "ms": 218},
        {"type": "latency", "phase": "chat", "ms": 3303},
        {"type": "latency", "phase": "follow_up_chat", "ms": 1081},
        {"type": "latency", "phase": "total", "ms": 4849},
    ]
    merged = _accumulate_progress_events(events)
    assert merged["latency_ms"]["github_readme"] == 237
    assert merged["latency_ms"]["total"] == 4849
