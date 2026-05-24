"""Stream / non-stream response aggregation."""

from app.core.sse import AnswerResponseAccumulator, build_latency_ms_summary


def test_accumulator_terminal_done_matches_non_stream_fields():
    acc = AnswerResponseAccumulator(
        request_id="req_1",
        session_id="sess_1",
        trace_id="req_1",
        conversation_id="conv_1",
        is_new_conversation=False,
    )
    acc.apply(
        {
            "type": "rewrite",
            "text": "What is Taixing's visa status?",
        }
    )
    acc.apply(
        {
            "type": "route",
            "route": "tool",
            "route_detail": {"type": "tool", "name": "user_profile"},
            "text": "What is Taixing's visa status?",
        }
    )
    acc.apply(
        {
            "type": "state",
            "phase": "intent_router",
            "status": "completed",
            "started_at": "2026-05-23T10:00:00+00:00",
            "ended_at": "2026-05-23T10:00:02+00:00",
            "latency_ms": 2000.0,
            "metadata": {},
        }
    )
    acc.apply(
        {
            "type": "state",
            "phase": "rag",
            "status": "completed",
            "started_at": "2026-05-23T10:00:02+00:00",
            "ended_at": "2026-05-23T10:00:04+00:00",
            "latency_ms": 1500.0,
            "metadata": {
                "tool": "user_profile",
                "rag_latency_ms": {"embed": 10.0, "chat": 100.0, "total": 110.0},
            },
        }
    )
    usage = {
        "prompt_tokens": 100,
        "completion_tokens": 10,
        "total_tokens": 110,
        "tool-rag": {"total": {"prompt_tokens": 80, "completion_tokens": 8, "total_tokens": 88}},
    }
    acc.apply(
        {
            "type": "answer",
            "text": "O-1 valid through 2027.",
            "citations": [{"doc_id": "visa"}],
            "follow_up_questions": ["Renewal date?"],
            "usage": usage,
        }
    )
    acc.apply({"type": "done", "usage": usage})

    done = acc.as_response(status="ok", event_type="done")
    assert done["type"] == "done"
    assert done["status"] == "ok"
    assert done["route"] == "tool"
    assert done["route_detail"]["name"] == "user_profile"
    assert done["rewrite"] == "What is Taixing's visa status?"
    assert done["answer"] == "O-1 valid through 2027."
    assert done["citations"] == [{"doc_id": "visa"}]
    assert done["follow_up_questions"] == ["Renewal date?"]
    assert done["usage"] == usage
    assert done["latency_ms"]["intent_router"] == {"total": 2000.0}
    assert done["latency_ms"]["tool-rag"] == {"embed": 10.0, "chat": 100.0, "total": 110.0}


def test_accumulator_error_matches_non_stream_fields():
    acc = AnswerResponseAccumulator(
        request_id="req_1",
        session_id=None,
        trace_id="req_1",
        conversation_id="conv_1",
        is_new_conversation=True,
    )
    acc.apply({"type": "route", "route": "tool", "route_detail": {"type": "tool", "name": "github_repo_search"}})
    err = acc.as_response(status="error", event_type="error", error="Error: RuntimeError: boom")
    assert err["type"] == "error"
    assert err["status"] == "error"
    assert err["error"] == "Error: RuntimeError: boom"
    assert err["route"] == "tool"
    assert "latency_ms" in err


def test_build_latency_ms_summary_unchanged():
    states = [
        {
            "phase": "intent_router",
            "status": "completed",
            "started_at": "2026-05-23T10:00:00+00:00",
            "ended_at": "2026-05-23T10:00:02+00:00",
            "latency_ms": 2000.0,
            "metadata": {},
        }
    ]
    out = build_latency_ms_summary(states)
    assert out["total"] == 2000.0
    assert out["intent_router"] == {"total": 2000.0}
