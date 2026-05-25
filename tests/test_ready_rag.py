"""RAG readiness probe treats empty retrieval as healthy."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.clients.ready import check_rag_http, run_readiness


def _mock_response(*, status_code: int, text: str) -> MagicMock:
    r = MagicMock(spec=httpx.Response)
    r.status_code = status_code
    r.text = text
    r.headers = {"content-type": "application/json"}

    def _json():
        return json.loads(text)

    r.json = _json
    return r


@pytest.mark.asyncio
async def test_rag_no_chunks_400_is_ok():
    body = json.dumps({"detail": "No chunks retrieved for this query."})
    client = AsyncMock(spec=httpx.AsyncClient)
    client.post = AsyncMock(
        return_value=_mock_response(status_code=400, text=body),
    )
    with patch("app.clients.ready.settings") as mock_settings:
        mock_settings.rag_http_base_url = "http://rag.test"
        mock_settings.rag_collection_base = "test"
        mock_settings.readiness_rag_question = "."
        result = await check_rag_http(client)
    assert result["ok"] is True
    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_rag_unrelated_400_is_fail():
    body = json.dumps({"detail": "Invalid collection"})
    client = AsyncMock(spec=httpx.AsyncClient)
    client.post = AsyncMock(
        return_value=_mock_response(status_code=400, text=body),
    )
    with patch("app.clients.ready.settings") as mock_settings:
        mock_settings.rag_http_base_url = "http://rag.test"
        mock_settings.rag_collection_base = "test"
        mock_settings.readiness_rag_question = "."
        result = await check_rag_http(client)
    assert result["ok"] is False


@pytest.mark.asyncio
async def test_rag_500_is_fail():
    client = AsyncMock(spec=httpx.AsyncClient)
    client.post = AsyncMock(
        return_value=_mock_response(status_code=500, text="internal error"),
    )
    with patch("app.clients.ready.settings") as mock_settings:
        mock_settings.rag_http_base_url = "http://rag.test"
        mock_settings.rag_collection_base = "test"
        mock_settings.readiness_rag_question = "."
        result = await check_rag_http(client)
    assert result["ok"] is False


@pytest.mark.asyncio
async def test_run_readiness_ok_when_rag_no_chunks():
    llm_ok = {"ok": True, "status": "ok", "latency_ms": 1.0}
    rag_ok = {"ok": True, "status": "ok", "latency_ms": 2.0}
    with patch("app.clients.ready.check_llm_gateway", AsyncMock(return_value=llm_ok)):
        with patch("app.clients.ready.check_rag_http", AsyncMock(return_value=rag_ok)):
            all_ok, body = await run_readiness()
    assert all_ok is True
    assert body["status"] == "ok"
