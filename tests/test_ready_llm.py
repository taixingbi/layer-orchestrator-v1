"""LLM gateway readiness probe uses non-streaming chat completions."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.clients.ready import check_llm_gateway


def _mock_response(*, status_code: int, text: str, content_type: str = "application/json") -> MagicMock:
    r = MagicMock(spec=httpx.Response)
    r.status_code = status_code
    r.text = text
    r.headers = {"content-type": content_type}

    def _json():
        return json.loads(text)

    r.json = _json
    return r


@pytest.mark.asyncio
async def test_llm_readiness_posts_stream_false():
    completion = json.dumps(
        {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "P"}}],
        }
    )
    client = AsyncMock(spec=httpx.AsyncClient)
    client.post = AsyncMock(return_value=_mock_response(status_code=200, text=completion))

    with patch("app.clients.ready.normalized_llm_base_url", return_value="http://llm.test/v1"):
        with patch("app.clients.ready.settings") as mock_settings:
            mock_settings.llm_model = "test-model"
            result = await check_llm_gateway(client)

    assert result["ok"] is True
    assert client.post.await_args.kwargs["json"]["stream"] is False


@pytest.mark.asyncio
async def test_llm_readiness_sse_without_stream_false_would_fail():
    sse_body = 'data: {"choices":[{"delta":{"content":"P"}}]}\n\ndata: [DONE]\n'
    client = AsyncMock(spec=httpx.AsyncClient)
    client.post = AsyncMock(
        return_value=_mock_response(
            status_code=200,
            text=sse_body,
            content_type="text/event-stream",
        ),
    )

    with patch("app.clients.ready.normalized_llm_base_url", return_value="http://llm.test/v1"):
        with patch("app.clients.ready.settings") as mock_settings:
            mock_settings.llm_model = "test-model"
            result = await check_llm_gateway(client)

    assert result["ok"] is False
    assert result["error"] == "invalid_json"
