from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from ingestion.offer.scraping.sources.adzuna_source import AdzunaSource

_recent = (datetime.now() - timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ")

MOCK_RESPONSE = {
    "results": [
        {
            "title": "Machine Learning Engineer",
            "company": {"display_name": "DataCo"},
            "location": {"display_name": "London, UK"},
            "redirect_url": "https://adzuna.co.uk/jobs/details/123",
            "created": _recent,
            "description": "Develop ML models and pipelines.",
        }
    ]
}


def _mock_get(response):
    mock = MagicMock()
    mock.json.return_value = response
    mock.raise_for_status = MagicMock()
    return mock


def test_returns_offers_with_valid_keys():
    with patch.dict("os.environ", {"ADZUNA_APP_ID": "fake_id", "ADZUNA_APP_KEY": "fake_key"}):
        with patch("offer.scraping.sources.adzuna_source.requests.get", return_value=_mock_get(MOCK_RESPONSE)):
            results = AdzunaSource().fetch("machine learning", hours=72)

    assert len(results) > 0
    assert results[0].title == "Machine Learning Engineer"
    assert results[0].source == "adzuna"


def test_returns_empty_when_keys_missing():
    with patch.dict("os.environ", {}, clear=True):
        results = AdzunaSource().fetch("machine learning", hours=72)
    assert results == []


def test_returns_empty_on_http_error():
    with patch.dict("os.environ", {"ADZUNA_APP_ID": "id", "ADZUNA_APP_KEY": "key"}):
        with patch("offer.scraping.sources.adzuna_source.requests.get", side_effect=Exception("403")):
            results = AdzunaSource().fetch("python", hours=72)
    assert results == []


def test_description_is_populated():
    with patch.dict("os.environ", {"ADZUNA_APP_ID": "fake_id", "ADZUNA_APP_KEY": "fake_key"}):
        with patch("offer.scraping.sources.adzuna_source.requests.get", return_value=_mock_get(MOCK_RESPONSE)):
            results = AdzunaSource().fetch("machine learning", hours=72)

    assert results[0].description == "Develop ML models and pipelines."
