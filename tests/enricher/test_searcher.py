from unittest.mock import MagicMock, patch

from enricher.searcher import search_company_urls


def test_search_returns_website_and_glassdoor():
    website_hit = [{"href": "https://acme.com", "title": "Acme Corp"}]
    glassdoor_hit = [{"href": "https://www.glassdoor.com/Overview/acme", "title": "Acme Glassdoor"}]

    with patch("enricher.searcher.DDGS") as mock_ddgs:
        instance = MagicMock()
        mock_ddgs.return_value.__enter__.return_value = instance
        instance.text.side_effect = [website_hit, glassdoor_hit]

        result = search_company_urls("Acme", "Berlin")

    assert result["website"] == "https://acme.com"
    assert result["glassdoor"] == "https://www.glassdoor.com/Overview/acme"


def test_search_omits_missing_sources():
    with patch("enricher.searcher.DDGS") as mock_ddgs:
        instance = MagicMock()
        mock_ddgs.return_value.__enter__.return_value = instance
        instance.text.return_value = []

        result = search_company_urls("Unknown Corp", "Nowhere")

    assert result == {}


def test_search_returns_partial_when_one_source_missing():
    website_hit = [{"href": "https://acme.com", "title": "Acme"}]

    with patch("enricher.searcher.DDGS") as mock_ddgs:
        instance = MagicMock()
        mock_ddgs.return_value.__enter__.return_value = instance
        instance.text.side_effect = [website_hit, []]

        result = search_company_urls("Acme", "Berlin")

    assert result == {"website": "https://acme.com"}
