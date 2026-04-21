import time
from unittest.mock import MagicMock, patch
from retriever.sources.arbeitnow_source import ArbeitnowSource

_NOW = time.time()

MOCK_RESPONSE = {
    "data": [
        {
            "title": "Python Developer",
            "company_name": "TechCorp",
            "location": "Berlin, Germany",
            "url": "https://arbeitnow.com/jobs/python-dev-123",
            "created_at": int(_NOW - 3600),  # 1 hour ago — within 3 days
        },
        {
            "title": "Softwareentwickler",  # German title — should be discarded
            "company_name": "GmbH AG",
            "location": "Munich",
            "url": "https://arbeitnow.com/jobs/sw-456",
            "created_at": int(_NOW - 3600),
        },
        {
            "title": "Data Engineer",
            "company_name": "OldCorp",
            "location": "Amsterdam",
            "url": "https://arbeitnow.com/jobs/de-789",
            "created_at": int(_NOW - 7 * 24 * 3600),  # 7 days ago — too old
        },
    ]
}


def _mock_get(response):
    mock = MagicMock()
    mock.json.return_value = response
    mock.raise_for_status = MagicMock()
    return mock


def test_returns_matching_english_offers_within_days():
    with patch("retriever.sources.arbeitnow_source.requests.get", return_value=_mock_get(MOCK_RESPONSE)):
        results = ArbeitnowSource().fetch("python", days=3)

    assert len(results) == 1
    assert results[0].title == "Python Developer"
    assert results[0].source == "arbeitnow"
    assert results[0].company == "TechCorp"


def test_returns_empty_on_network_error():
    with patch("retriever.sources.arbeitnow_source.requests.get", side_effect=Exception("timeout")):
        assert ArbeitnowSource().fetch("python", days=3) == []
