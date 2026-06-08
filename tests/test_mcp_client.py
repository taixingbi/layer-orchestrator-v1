"""MCP SSE parsing — RAG progress + GitHub MCP v2 (meta / delta / done)."""

import json

import pytest

from app.tools.mcp_client import (
    _accumulate_github_sse,
    _accumulate_progress_events,
    _normalize_mcp_tool_payload,
    _parse_mcp_sse_lines,
    _tool_result_from_json_payload,
)

GITHUB_DONE_V2 = {
    "meta": {
        "request_id": "req-mcp-stream-1",
        "route": {"type": "tool", "tool": "github_search", "source": "deterministic_rule"},
        "tool": {"name": "github_search", "type": "github", "version": "v1"},
        "github": {"scope": "all", "repos": ["taixingbi/layer-orchestrator-v1"]},
    },
    "answer": {
        "format": "blocks",
        "text": "## Introduction to huntAi Project\n\nThe huntAi project involves several repositories.",
        "blocks": [
            {"type": "heading", "text": "Introduction to huntAi Project", "cite_ids": []},
            {
                "type": "paragraph",
                "text": "The huntAi project involves several repositories.",
                "cite_ids": [1, 4],
            },
        ],
        "notes": ["Routing detail not documented"],
        "citations": [
            {"cite_id": 1, "source": "layer-mcp-github-v1 README"},
            {"cite_id": 4, "source": "layer-orchestrator-v1 README"},
        ],
    },
    "follow_up_questions": ["What is the main function of layer-orchestrator-v1?"],
    "latency_ms": {
        "total": 8577,
        "tool_github_search": {
            "retrieve_rerank": 3095,
            "chat": 4310,
            "follow_up_chat": 1125,
            "total": 8577,
        },
    },
    "usage": {
        "total": {"prompt_tokens": 399, "completion_tokens": 52, "total_tokens": 451},
    },
    "status": {"ok": True, "state": "completed", "code": "ok"},
}


def test_normalize_github_mcp_v2_payload():
    norm = _normalize_mcp_tool_payload(GITHUB_DONE_V2)
    assert "Introduction to huntAi" in norm["answer"]
    assert norm["answer_format"] == "blocks"
    assert norm["answer_blocks"][0]["type"] == "heading"
    assert norm["answer_notes"] == ["Routing detail not documented"]
    assert len(norm["citations"]) == 2
    assert norm["latency_ms"]["retrieve_rerank"] == 3095
    assert norm["latency_ms"]["total"] == 8577
    assert norm["usage"]["total"]["total_tokens"] == 451
    assert norm["metadata"]["mcp_meta"]["github"]["scope"] == "all"


def test_accumulate_progress_rag_mcp_style():
    events = [
        {"type": "answer_delta", "text": "Hello "},
        {"type": "answer_delta", "text": "world"},
        {"type": "usage", "total": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}},
    ]
    merged = _accumulate_progress_events(events)
    assert merged["answer"] == "Hello world"
    assert merged["usage"]["total"]["prompt_tokens"] == 1


def test_accumulate_progress_rag_block_event():
    events = [
        {
            "type": "rag",
            "collection": "taixing_knowledge",
            "retrieval": {"retrieved_chunks": 40, "reranked_chunks": 10, "context_chunks": 5},
        }
    ]
    merged = _accumulate_progress_events(events)
    assert merged["rag"]["collection"] == "taixing_knowledge"
    assert merged["rag"]["retrieval"]["context_chunks"] == 5


def test_accumulate_github_sse_v2_delta_and_done():
    done_json = json.dumps(GITHUB_DONE_V2, separators=(",", ":"))
    sse = f"""event: meta
data: {json.dumps({"meta": GITHUB_DONE_V2["meta"]})}

event: answer_delta
data: {{"text": "##"}}

event: answer_delta
data: {{"text": " Intro"}}

event: done
data: {done_json}
"""
    merged = _accumulate_github_sse(sse)
    assert merged["answer"].startswith("## Intro")
    assert merged["latency_ms"]["chat"] == 4310
    assert merged["follow_up_questions"][0].startswith("What is")


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
async def test_parse_mcp_sse_github_v2_stream():
    """GitHub MCP: meta → answer_delta (text) → done envelope."""
    done_line = json.dumps(GITHUB_DONE_V2, separators=(",", ":"))
    sse_lines = [
        "event: meta",
        f'data: {json.dumps({"meta": GITHUB_DONE_V2["meta"]})}',
        "",
        "event: answer_delta",
        'data: {"text": "Repo "}',
        "",
        "event: answer_delta",
        'data: {"text": "overview"}',
        "",
        "event: done",
        f"data: {done_line}",
        "",
    ]
    deltas: list[str] = []

    async def _lines():
        for line in sse_lines:
            yield line

    result = await _parse_mcp_sse_lines(_lines(), on_delta=deltas.append)
    assert deltas == ["Repo ", "overview"]
    assert result.answer.startswith("## Introduction")
    assert result.answer_format == "blocks"
    assert result.answer_blocks[0]["type"] == "heading"
    assert result.latency_ms == GITHUB_DONE_V2["latency_ms"]["tool_github_search"]
    assert result.usage["total"]["total_tokens"] == 451
    assert len(result.citations) == 2
    assert result.follow_up_questions


@pytest.mark.asyncio
async def test_tool_result_from_json_buffered_github_v2():
    payload = {"jsonrpc": "2.0", "id": "1", "result": GITHUB_DONE_V2}
    result = await _tool_result_from_json_payload(payload)
    assert "Introduction to huntAi" in result.answer
    assert result.latency_ms["retrieve_rerank"] == 3095


@pytest.mark.asyncio
async def test_tool_result_from_json_structured_content_github_v2():
    payload = {"jsonrpc": "2.0", "id": "1", "result": {"structuredContent": GITHUB_DONE_V2}}
    result = await _tool_result_from_json_payload(payload)
    assert result.latency_ms["total"] == 8577


@pytest.mark.asyncio
async def test_github_search_latency_end_to_end():
    """MCP v2 latency_ms.tool_github_search → pipeline metadata → client envelope."""
    from app.core.sse import build_latency_ms_summary
    from app.schemas.answer_envelope import LATENCY_KEY_GITHUB_SEARCH

    tool_latency = GITHUB_DONE_V2["latency_ms"]["tool_github_search"]
    done_line = json.dumps(GITHUB_DONE_V2, separators=(",", ":"))
    sse_lines = [
        "event: answer_delta",
        'data: {"answer": {"text": "chunk"}}',
        "",
        "event: done",
        f"data: {done_line}",
        "",
    ]

    async def _lines():
        for line in sse_lines:
            yield line

    tool_result = await _parse_mcp_sse_lines(_lines())
    assert tool_result.latency_ms == tool_latency

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
                "tool": "github_search",
                "github_latency_ms": tool_result.latency_ms,
            },
        },
    ]
    out = build_latency_ms_summary(states)
    assert out[LATENCY_KEY_GITHUB_SEARCH] is tool_result.latency_ms
    assert out[LATENCY_KEY_GITHUB_SEARCH]["total"] == 8577
    assert out[LATENCY_KEY_GITHUB_SEARCH]["retrieve_rerank"] == 3095
    assert out["intent_router"] == {"total": 1999.91}


def test_accumulate_progress_github_legacy_latency_phases():
    """Legacy RAG-style progress latency events still merge."""
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
