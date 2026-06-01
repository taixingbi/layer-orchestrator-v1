"""SSE event type names for the answer stream."""

# First stream frame: session/request/trace ids and conversation threading.
SSE_EVENT_CORRELATION = "correlation"

# Deprecated alias; still accepted by AnswerResponseAccumulator for older clients.
SSE_EVENT_CORRELATION_LEGACY = "request_id"

CORRELATION_SSE_EVENT_TYPES = frozenset(
    {SSE_EVENT_CORRELATION, SSE_EVENT_CORRELATION_LEGACY}
)

CORRELATION_SSE_FIELD_KEYS = (
    "request_id",
    "session_id",
    "trace_id",
    "conversation_id",
    "is_new_conversation",
)
