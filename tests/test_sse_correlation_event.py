"""SSE correlation event type and legacy alias."""

from app.core.sse import AnswerResponseAccumulator
from app.core.sse_events import SSE_EVENT_CORRELATION, SSE_EVENT_CORRELATION_LEGACY


def _correlation_payload(**overrides):
    base = {
        "request_id": "req-1",
        "session_id": "sess-1",
        "trace_id": "trc-1",
        "conversation_id": "conv-1",
        "is_new_conversation": False,
    }
    base.update(overrides)
    return base


def test_correlation_event_merges_all_fields():
    acc = AnswerResponseAccumulator(
        request_id="req-init",
        session_id=None,
        trace_id="req-init",
        conversation_id="conv-init",
        is_new_conversation=True,
    )
    acc.apply({"type": SSE_EVENT_CORRELATION, **_correlation_payload()})
    done = acc.finalize(ok=True)
    meta = done["meta"]
    assert meta["request_id"] == "req-1"
    assert meta["session_id"] == "sess-1"
    assert meta["trace_id"] == "trc-1"
    assert meta["conversation_id"] == "conv-1"
    assert meta["is_new_conversation"] is False


def test_legacy_request_id_event_type_still_merges_fields():
    acc = AnswerResponseAccumulator(
        request_id="req-init",
        session_id=None,
        trace_id="req-init",
        conversation_id="conv-init",
        is_new_conversation=True,
    )
    acc.apply({"type": SSE_EVENT_CORRELATION_LEGACY, **_correlation_payload(is_new_conversation=True)})
    done = acc.finalize(ok=True)
    assert done["meta"]["request_id"] == "req-1"
    assert done["meta"]["is_new_conversation"] is True
