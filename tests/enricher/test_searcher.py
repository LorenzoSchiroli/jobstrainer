from unittest.mock import patch

from enricher.searcher import search_company_urls


def test_search_returns_website_and_glassdoor_snippets():
    website_hits = [{"href": "https://acme.com", "title": "Acme Corp", "body": ""}]
    glassdoor_hits = [
        {"href": "https://www.glassdoor.com/Overview/acme", "title": "Acme", "body": "Great culture. 4.2 stars based on 35 reviews."},
    ]

    def mock_search(query, max_results):
        if "glassdoor" in query:
            return glassdoor_hits
        return website_hits

    with patch("enricher.searcher._search", side_effect=mock_search):
        urls, snippets = search_company_urls("Acme", "Berlin")

    assert urls["website"] == "https://acme.com"
    assert "glassdoor" not in urls
    assert any("4.2" in s for s in snippets)


def test_search_omits_missing_sources():
    with patch("enricher.searcher._search", return_value=[]):
        urls, snippets = search_company_urls("Unknown Corp", "Nowhere")

    assert urls == {}
    assert snippets == []


def test_search_handles_search_exception_gracefully():
    glassdoor_hits = [
        {"href": "https://www.glassdoor.com/Overview/acme", "title": "Acme", "body": "Nice culture. 4.1 stars."},
    ]

    def mock_search(query, max_results):
        if "glassdoor" in query:
            return glassdoor_hits
        raise Exception("rate limited")

    with patch("enricher.searcher._search", side_effect=mock_search):
        urls, snippets = search_company_urls("Acme", "Berlin")

    assert "website" not in urls
    assert any("4.1" in s for s in snippets)


def test_search_returns_partial_when_glassdoor_empty():
    website_hits = [{"href": "https://acme.com", "title": "Acme", "body": ""}]

    def mock_search(query, max_results):
        if "glassdoor" in query:
            return []
        return website_hits

    with patch("enricher.searcher._search", side_effect=mock_search):
        urls, snippets = search_company_urls("Acme", "Berlin")

    assert urls == {"website": "https://acme.com"}
    assert snippets == []
