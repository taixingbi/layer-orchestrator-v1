"""Web search (Tavily) formatting — mocked, no live API."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tools.web_search import _format_results_as_answer, _results_to_citations, run_web_search


def test_format_results_with_answer():
    results = [{"title": "A", "content": "snippet", "url": "https://a.com"}]
    text = _format_results_as_answer(results, "Summary from Tavily.")
    assert text == "Summary from Tavily."


def test_format_results_without_answer():
    results = [{"title": "A", "content": "snippet text", "url": "https://a.com"}]
    text = _format_results_as_answer(results, None)
    assert "[1]" in text
    assert "snippet" in text


def test_results_to_citations():
    results = [{"title": "T", "content": "body", "url": "https://x.com"}]
    cites = _results_to_citations(results)
    assert cites[0]["cite_id"] == 1
    assert cites[0]["source"] == "web"
    assert cites[0]["url"] == "https://x.com"


@pytest.mark.asyncio
async def test_run_web_search_mocked():
    mock_response = {
        "answer": "Mock answer.",
        "results": [{"title": "R", "content": "c", "url": "https://r.com"}],
    }
    mock_client = MagicMock()
    mock_client.search = AsyncMock(return_value=mock_response)
    with patch("app.tools.web_search.settings") as mock_settings:
        mock_settings.tavily_api_key = "test-key"
        mock_settings.tavily_search_depth = "basic"
        mock_settings.tavily_max_results = 5
        with patch("app.tools.web_search._tavily_client", return_value=mock_client):
            result = await run_web_search("test query")
    assert result.answer == "Mock answer."
    assert len(result.citations) == 1
