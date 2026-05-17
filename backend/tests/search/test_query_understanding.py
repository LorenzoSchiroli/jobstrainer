import json
from unittest.mock import MagicMock
from backend.search.query_understanding import extract_filters, get_groq_client
from backend.search.filters import SearchFilters


def _mock_groq(response: dict) -> MagicMock:
    msg = MagicMock()
    msg.content = json.dumps(response)
    choice = MagicMock()
    choice.message = msg
    completion = MagicMock()
    completion.choices = [choice]
    client = MagicMock()
    client.chat.completions.create.return_value = completion
    return client


async def test_returns_search_filters():
    groq = _mock_groq({"semantic_query": "senior python remote", "seniority": "senior", "location_type": "remote"})
    result = await extract_filters(groq, cv_text="5yr Python", query="senior python remote")
    assert isinstance(result, SearchFilters)
    assert result.semantic_query == "senior python remote"
    assert result.seniority == "senior"
    assert result.location_type == "remote"


async def test_uses_json_mode():
    groq = _mock_groq({"semantic_query": "engineer"})
    await extract_filters(groq, cv_text="cv", query="q")
    kwargs = groq.chat.completions.create.call_args.kwargs
    assert kwargs["response_format"] == {"type": "json_object"}


async def test_falls_back_to_query_when_semantic_query_missing():
    groq = _mock_groq({})
    result = await extract_filters(groq, cv_text="cv", query="fallback query")
    assert result.semantic_query == "fallback query"


def test_get_groq_client(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    assert get_groq_client() is not None
