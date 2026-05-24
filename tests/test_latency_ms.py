"""latency_ms summary aggregation."""

from app.core.sse import build_latency_ms_summary


def test_build_latency_ms_summary_nested_rag_service():
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
                "rag_latency_ms": {
                    "embed": 45.2,
                    "retrieve": 312.0,
                    "chat": 890.5,
                    "follow_up_chat": 520.1,
                    "total": 1767.8,
                },
            },
        },
    ]
    out = build_latency_ms_summary(states)
    rag = out["rag"]["orchestrator"]
    assert out["total"] == 4918.0
    assert out["intent_router"] == {"total": 2040.27}
    assert rag["wall"] == 2877.88
    assert rag["embed"] == 45.2
    assert rag["retrieve"] == 312.0
    assert rag["chat"] == 890.5
    assert rag["follow_up_chat"] == 520.1
    assert rag["total"] == 1767.8


def test_build_latency_ms_summary_mcp_tool_latency_key():
    states = [
        {
            "phase": "rag",
            "status": "completed",
            "latency_ms": 100.0,
            "metadata": {
                "tool": "user_profile",
                "tool_latency_ms": {"chat": 50.0, "total": 50.0},
            },
        },
    ]
    out = build_latency_ms_summary(states)
    rag = out["rag"]["orchestrator"]
    assert rag["wall"] == 100.0
    assert rag["chat"] == 50.0
    assert rag["total"] == 50.0


def test_build_latency_ms_summary_github_mcp():
    states = [
        {
            "phase": "intent_router",
            "status": "completed",
            "started_at": "2026-01-01T12:00:00Z",
            "ended_at": "2026-01-01T12:00:02.040Z",
            "latency_ms": 2040.27,
        },
        {
            "phase": "github",
            "status": "completed",
            "started_at": "2026-01-01T12:00:02.040Z",
            "ended_at": "2026-01-01T12:00:06.889Z",
            "latency_ms": 4849.0,
            "metadata": {
                "tool": "github_repo_search",
                "tool_latency_ms": {
                    "github_readme": 237,
                    "github_search": 218,
                    "chat": 3303,
                    "follow_up_chat": 1081,
                    "total": 4849,
                },
            },
        },
    ]
    out = build_latency_ms_summary(states)
    github = out["github"]["orchestrator"]
    assert out["total"] == 6889.0
    assert out["intent_router"] == {"total": 2040.27}
    assert github["wall"] == 4849.0
    assert github["github_readme"] == 237
    assert github["github_search"] == 218
    assert github["chat"] == 3303
    assert github["follow_up_chat"] == 1081
    assert github["total"] == 4849


def test_build_latency_ms_summary_github_legacy_tool_phase():
    states = [
        {
            "phase": "tool",
            "status": "completed",
            "latency_ms": 5062.0,
            "metadata": {
                "tool": "github_repo_search",
                "tool_latency_ms": {
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
    github = out["github"]["orchestrator"]
    assert "tool" not in out
    assert github["wall"] == 5062.0
    assert github["github_readme"] == 286
    assert github["total"] == 5062
