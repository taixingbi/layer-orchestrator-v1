"""Correlation id helpers and MCP header parity."""

from app.core.correlation import new_session_id, trace_id_log_fields
from app.tools.mcp_client import _mcp_headers


def test_new_session_id_prefix():
    sid = new_session_id()
    assert sid.startswith("ses_")


def test_trace_id_log_fields_defaulted():
    fields = trace_id_log_fields(
        request_id="req-1",
        trace_id="req-1",
        trace_id_from_header=False,
    )
    assert fields["trace_id"] == "req-1"
    assert fields["trace_id_source"] == "request_id"


def test_trace_id_log_fields_from_header():
    fields = trace_id_log_fields(
        request_id="req-1",
        trace_id="trc-9",
        trace_id_from_header=True,
    )
    assert fields["trace_id"] == "trc-9"
    assert fields["trace_id_source"] == "header"


def test_mcp_headers_include_is_new_conversation():
    headers = _mcp_headers(
        request_id="req-1",
        session_id="ses-1",
        trace_id="trc-1",
        conversation_id="conv-1",
        is_new_conversation=True,
    )
    assert headers["X-Conversation-Id"] == "conv-1"
    assert headers["X-Is-New-Conversation"] == "true"
