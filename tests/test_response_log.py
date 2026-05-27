"""final_response_emitted gateway_meta matches client answer envelope."""

from app.core.sse import AnswerResponseAccumulator
from app.observability.response_log import build_final_response_log
from app.observability.usage import USAGE_KEY_RAG, build_usage_payload
from app.schemas.answer_envelope import LATENCY_KEY_RAG


def _sample_states():
    return [
        {
            "phase": "intent_router",
            "status": "completed",
            "started_at": "2026-05-23T10:00:00+00:00",
            "ended_at": "2026-05-23T10:00:02+00:00",
            "latency_ms": 2000.0,
            "metadata": {},
        },
        {
            "phase": "rag",
            "status": "completed",
            "started_at": "2026-05-23T10:00:02+00:00",
            "ended_at": "2026-05-23T10:00:04+00:00",
            "metadata": {
                "tool": "rag_private_kb",
                "rag_latency_ms": {"embed": 1.0, "total": 10.0},
            },
        },
    ]


def test_build_final_response_log_matches_accumulator_finalize():
    states = _sample_states()
    usage = build_usage_payload(
        intent_router={"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        tool_rag={"total": {"prompt_tokens": 90, "completion_tokens": 9, "total_tokens": 99}},
    )
    route_detail = {"type": "tool", "name": "rag_private_kb", "confidence": 0.98, "reason": "kb"}

    logged = build_final_response_log(
        request_id="req-1",
        session_id="sess-1",
        trace_id="req-1",
        conversation_id="conv-1",
        is_new_conversation=False,
        route_detail=route_detail,
        route_source="llm_router",
        rewrite_text="rewritten q",
        answer_text="answer body",
        citations=[{"cite_id": 1, "chunk_id": "c1"}],
        follow_up_questions=["q1"],
        usage=usage,
        phase_states=states,
        route_initial="tool",
        route_initial_detail=route_detail,
        route_final="tool",
        route_final_detail=route_detail,
        answer_source="tool:rag_private_kb",
    )

    acc = AnswerResponseAccumulator(
        request_id="req-1",
        session_id="sess-1",
        trace_id="req-1",
        conversation_id="conv-1",
        is_new_conversation=False,
    )
    for ev in states:
        acc.apply({"type": "state", **ev})
    acc.apply({"type": "rewrite", "text": "rewritten q"})
    acc.apply({"type": "route", "route_detail": route_detail, "route_source": "llm_router"})
    acc.apply({"type": "answer_delta", "text": "answer body"})
    acc.apply(
        {
            "type": "done",
            "citations": [{"cite_id": 1, "chunk_id": "c1"}],
            "follow_up_questions": ["q1"],
            "usage": usage,
        }
    )
    expected = acc.finalize(ok=True, code="ok")

    assert logged["response"] == expected
    assert logged["routing"]["route_final"] == "tool"
    assert logged["routing"]["answer_source"] == "tool:rag_private_kb"
    assert logged["routing"]["override_applied"] is False
    assert logged["response"]["meta"]["route"]["tool"] == "rag_private_kb"
    assert logged["response"]["answer"]["text"] == "answer body"
    assert logged["response"]["usage"][USAGE_KEY_RAG]["total"]["total_tokens"] == 99
    assert logged["response"]["latency_ms"][LATENCY_KEY_RAG]["total"] == 10.0


def test_build_final_response_log_failed_envelope():
    logged = build_final_response_log(
        request_id="req-2",
        session_id=None,
        trace_id="req-2",
        conversation_id="conv-2",
        is_new_conversation=True,
        route_detail={"type": "tool", "name": "rag_private_kb", "confidence": 1.0},
        route_source="llm_router",
        rewrite_text="q",
        answer_text="",
        usage={"total": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}},
        phase_states=[],
        route_initial="tool",
        route_initial_detail={"type": "tool", "name": "rag_private_kb"},
        route_final="tool",
        route_final_detail={"type": "tool", "name": "rag_private_kb"},
        answer_source="tool:rag_private_kb",
        ok=False,
        error="Error: ValueError: boom",
        state="failed",
        code="error",
    )
    assert logged["response"]["status"]["ok"] is False
    assert logged["response"]["error"] == "Error: ValueError: boom"
    assert "routing" in logged
    assert "response" in logged
