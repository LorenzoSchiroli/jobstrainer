from unittest.mock import AsyncMock
from backend.search.retrieval import build_hybrid_query, hybrid_retrieve
from backend.search.filters import SearchFilters
from backend.opensearch_client import PIPELINE_NAME


def test_build_hybrid_query_has_two_legs():
    q = build_hybrid_query("python", [0.1] * 384, SearchFilters(semantic_query="python"))
    legs = q["query"]["hybrid"]["queries"]
    assert len(legs) == 2
    assert "match" in legs[0]["bool"]["must"]
    assert "knn" in legs[1]["bool"]["must"]
    assert q["size"] == 50


def test_build_hybrid_query_applies_filters_to_both_legs():
    f = SearchFilters(semantic_query="x", seniority="senior", is_consulting=False)
    q = build_hybrid_query("x", [0.0] * 384, f)
    for leg in q["query"]["hybrid"]["queries"]:
        assert len(leg["bool"]["filter"]) == 2


async def test_hybrid_retrieve_uses_pipeline():
    mock_os = AsyncMock()
    mock_os.search.return_value = {"hits": {"hits": [{"_source": {"job_id": "abc"}}]}}
    result = await hybrid_retrieve(mock_os, [0.1] * 384, SearchFilters(semantic_query="python"))
    kwargs = mock_os.search.call_args.kwargs
    assert kwargs["params"]["search_pipeline"] == PIPELINE_NAME
    assert result == [{"_source": {"job_id": "abc"}}]
