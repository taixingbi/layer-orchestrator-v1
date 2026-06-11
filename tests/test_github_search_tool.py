"""Orchestrator github_search MCP call."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.tools.github_search import run_github_search


@pytest.mark.asyncio
async def test_run_github_search_args_question_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.tools.github_search.settings.mcp_github_base_url",
        "http://mcp:8000",
    )

    with patch("app.tools.github_search.call_mcp_tool", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = type("R", (), {"answer": "ok"})()
        await run_github_search(
            "introduce this huntAi project",
            request_id="req-1",
            session_id="ses-1",
            trace_id="trc-1",
            conversation_id="conv-1",
        )

    mock_call.assert_awaited_once()
    args = mock_call.await_args.kwargs["arguments"]
    assert args == {
        "question": "introduce this huntAi project",
        "conversation_id": "conv-1",
    }
