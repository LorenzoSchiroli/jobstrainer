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
    assert q["size"] == 20


def test_build_hybrid_query_soft_applies_boosts_to_both_legs():
    f = SearchFilters(semantic_query="x", seniority="senior", is_consulting=False)
    q = build_hybrid_query("x", [0.0] * 384, f)
    for leg in q["query"]["hybrid"]["queries"]:
        assert len(leg["bool"]["should"]) == 2
    assert "post_filter" not in q


def test_build_hybrid_query_strict_uses_post_filter():
    f = SearchFilters(semantic_query="x", is_startup=True)
    q = build_hybrid_query("x", [0.0] * 384, f, strict=True)
    assert "post_filter" in q
    assert {"term": {"is_startup": True}} in q["post_filter"]["bool"]["filter"]
    for leg in q["query"]["hybrid"]["queries"]:
        assert "filter" not in leg["bool"]
        assert "should" not in leg["bool"]


def test_build_hybrid_query_strict_uses_large_prefetch():
    f = SearchFilters(semantic_query="x", is_startup=True)
    q = build_hybrid_query("x", [0.0] * 384, f, strict=True)
    assert q["size"] == 200


def test_build_hybrid_query_strict_no_post_filter_when_no_clauses():
    q = build_hybrid_query("x", [0.0] * 384, SearchFilters(semantic_query="x"), strict=True)
    assert "post_filter" not in q


async def test_hybrid_retrieve_uses_pipeline():
    mock_os = AsyncMock()
    mock_os.search.return_value = {"hits": {"hits": [{"_source": {"job_id": "abc"}}]}}
    result = await hybrid_retrieve(mock_os, [0.1] * 384, SearchFilters(semantic_query="python"))
    kwargs = mock_os.search.call_args.kwargs
    assert kwargs["params"]["search_pipeline"] == PIPELINE_NAME
    assert result == [{"_source": {"job_id": "abc"}}]
