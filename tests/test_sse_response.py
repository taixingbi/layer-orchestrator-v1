"""Stream terminal events match non-stream envelope."""

from app.core.sse import AnswerResponseAccumulator
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
                "tool": "user_profile",
                "rag_latency_ms": {"embed": 1.0, "total": 10.0},
            },
        },
    ]


def test_stream_done_matches_non_stream_envelope():
    acc = AnswerResponseAccumulator(
        request_id="req-1",
        session_id="sess-1",
        trace_id="req-1",
        conversation_id="conv-1",
        is_new_conversation=False,
        rag_user={"user_id": "u1"},
    )
    for ev in _sample_states():
        acc.apply({"type": "state", **ev})
    acc.apply({"type": "rewrite", "text": "rewritten q"})
    acc.apply(
        {
            "type": "route",
            "route_detail": {"type": "tool", "name": "user_profile", "confidence": 0.98},
            "route_source": "llm_router",
        }
    )
    usage = build_usage_payload(
        intent_router={"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        tool_rag={"total": {"prompt_tokens": 90, "completion_tokens": 9, "total_tokens": 99}},
    )
    acc.apply(
        {
            "type": "answer_delta",
            "answer": {"text": "answer body", "citations": [{"doc_id": "d1"}]},
            "follow_up_questions": ["q1"],
            "usage": usage,
        }
    )
    done = acc.enrich_terminal_event({"type": "done"})
    assert done["type"] == "done"
    assert done["status"]["ok"] is True
    assert done["status"]["code"] == "ok"
    assert done["meta"]["route"]["tool"] == "user_profile"
    assert done["meta"]["route"]["source"] == "llm_router"
    assert done["meta"]["rewrite"] == "rewritten q"
    assert done["answer"]["text"] == "answer body"
    assert done["usage"][USAGE_KEY_RAG]["total"]["total_tokens"] == 99
    assert done["latency_ms"][LATENCY_KEY_RAG]["total"] == 10.0

    non_stream = acc.finalize(ok=True)
    assert done["meta"] == non_stream["meta"]
    assert done["answer"] == non_stream["answer"]
    assert done["usage"] == non_stream["usage"]
    assert done["latency_ms"] == non_stream["latency_ms"]


def test_answer_delta_text_chunks_concatenate():
    acc = AnswerResponseAccumulator(
        request_id="req-1",
        session_id=None,
        trace_id="req-1",
        conversation_id="conv-1",
        is_new_conversation=False,
    )
    acc.apply({"type": "answer_delta", "text": "Hello "})
    acc.apply({"type": "answer_delta", "text": "world"})
    done = acc.finalize(ok=True, code="ok")
    assert done["answer"]["text"] == "Hello world"


def test_stream_error_envelope():
    acc = AnswerResponseAccumulator(
        request_id="req-1",
        session_id=None,
        trace_id="req-1",
        conversation_id="conv-1",
        is_new_conversation=True,
    )
    acc.apply({"type": "route", "route_detail": {"type": "tool", "name": "user_profile"}})
    err = acc.enrich_terminal_event({"type": "error", "text": "Error: ValueError: boom"})
    assert err["type"] == "error"
    assert err["status"]["ok"] is False
    assert err["status"]["code"] == "error"
    assert err["error"] == "Error: ValueError: boom"
    assert err["meta"]["route"]["tool"] == "user_profile"
