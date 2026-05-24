"""latency_ms summary aggregation."""

from app.core.sse import build_latency_ms_summary


def test_build_latency_ms_summary_nested_rag_service():
    mcp_latency = {
        "embed": 45.2,
        "retrieve": 312.0,
        "chat": 890.5,
        "follow_up_chat": 520.1,
        "total": 1767.8,
    }
    states = [
        {
            "phase": "intent_router",
            "status": "completed",
            "started_at": "2026-01-01T12:00:00Z",
            "ended_at": "2026-01-01T12:00:02.040Z",
            "latency_ms": 2040.27,
        },
        {
            "phase": "rag",
            "status": "completed",
            "started_at": "2026-01-01T12:00:02.040Z",
            "ended_at": "2026-01-01T12:00:04.918Z",
            "latency_ms": 2877.88,
            "metadata": {
                "tool": "user_profile",
                "rag_latency_ms": mcp_latency,
            },
        },
    ]
    out = build_latency_ms_summary(states)
    assert out["tool-rag"] is mcp_latency
    assert "orchestrator" not in out["tool-rag"]


def test_build_latency_ms_summary_mcp_tool_latency_key():
    mcp_latency = {"chat": 50.0, "total": 50.0}
    states = [
        {
            "phase": "rag",
            "status": "completed",
            "latency_ms": 100.0,
            "metadata": {
                "tool": "user_profile",
                "tool_latency_ms": mcp_latency,
            },
        },
    ]
    out = build_latency_ms_summary(states)
    assert out["tool-rag"] is mcp_latency


def test_build_latency_ms_summary_github_mcp():
    states = [
        {
            "phase": "intent_router",
            "status": "completed",
            "started_at": "2026-01-01T12:00:00Z",
            "ended_at": "2026-01-01T12:00:02.040Z",
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
                "github_latency_ms": {
                    "github_readme": 286,
                    "github_search": 117,
                    "chat": 3435,
                    "follow_up_chat": 1193,
                    "total": 5062,
                },
            },
        },
    ]
    out = build_latency_ms_summary(states)
    github = out["tool-github-search"]
    assert out["total"] == 4691.0
    assert out["intent_router"] == {"total": 1999.91}
    assert github["github_readme"] == 286
    assert github["github_search"] == 117
    assert github["chat"] == 3435
    assert github["follow_up_chat"] == 1193
    assert github["total"] == 5062
    assert "orchestrator" not in github


def test_build_latency_ms_summary_github_mcp_passthrough_exact():
    mcp_latency = {
        "github_readme": 286,
        "github_search": 117,
        "chat": 3435,
        "follow_up_chat": 1193,
        "total": 5062,
    }
    states = [
        {
            "phase": "github-search",
            "status": "completed",
            "metadata": {
                "tool": "github_repo_search",
                "github_latency_ms": mcp_latency,
            },
        },
    ]
    out = build_latency_ms_summary(states)
    assert out["tool-github-search"] is mcp_latency


def test_build_latency_ms_summary_github_legacy_tool_latency_ms():
    mcp_latency = {"github_readme": 286, "total": 5062}
    states = [
        {
            "phase": "tool",
            "status": "completed",
            "metadata": {
                "tool": "github_repo_search",
                "tool_latency_ms": mcp_latency,
            },
        },
    ]
    out = build_latency_ms_summary(states)
    assert out["tool-github-search"] is mcp_latency


def test_build_latency_ms_summary_tavily_web_search():
    mcp_latency = {"web_search": 842.15}
    states = [
        {
            "phase": "tool",
            "status": "completed",
            "metadata": {
                "tool": "web_search",
                "tool_latency_ms": mcp_latency,
            },
        },
    ]
    out = build_latency_ms_summary(states)
    assert out["tool-tavily-search"] is mcp_latency
