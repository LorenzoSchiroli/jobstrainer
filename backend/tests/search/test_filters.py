from backend.search.filters import SearchFilters, build_filters


def test_only_semantic_query_required():
    f = SearchFilters(semantic_query="python engineer")
    assert f.seniority is None


def test_build_filters_empty_when_all_none():
    assert build_filters(SearchFilters(semantic_query="x")) == []


def test_build_filters_term_bool():
    result = build_filters(SearchFilters(semantic_query="x", is_consulting=True))
    assert {"term": {"is_consulting": True}} in result


def test_build_filters_term_string():
    result = build_filters(SearchFilters(semantic_query="x", seniority="senior"))
    assert {"term": {"seniority": "senior"}} in result


def test_build_filters_range_review_score():
    result = build_filters(SearchFilters(semantic_query="x", min_review_score=4.0))
    assert {"range": {"review_score": {"gte": 4.0}}} in result


def test_build_filters_range_financial_health():
    result = build_filters(SearchFilters(semantic_query="x", min_financial_health_score=3))
    assert {"range": {"financial_health_score": {"gte": 3}}} in result


def test_build_filters_terms_languages():
    result = build_filters(SearchFilters(semantic_query="x", languages_required=["Python", "Go"]))
    assert {"terms": {"languages_required": ["Python", "Go"]}} in result


def test_build_filters_multiple():
    result = build_filters(SearchFilters(semantic_query="x", seniority="senior", is_startup=True, min_review_score=3.5))
    assert len(result) == 3
